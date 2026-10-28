#!/bin/bash
# apply_release.sh — применить выкладку НА СЕРВЕРЕ (28.10.2026).
#
# Одна реализация подмены, смоука и отката для всех путей выкладки: ручной
# (deploy-server.sh, deploy-web.sh кладут сюда свежую копию этого файла) и автодеплоя
# из CI (deploy/ci/gb-ci-deploy зовёт установленную копию). Две копии этой логики
# разошлись бы молча — ровно так раньше уезжала половина кода.
#
#   apply_release.sh <каталог> <коммит> <откуда>
#
# В каталоге — app/ и root/ (сервер) и/или webdist/ (сайт): что есть, то и выкладывается.
# Каждая часть: атомарная подмена → смоук → не прошёл — прежняя версия возвращается сама,
# письмо уходит сразу, код выхода 1. Итог пишется в /root/gb-deploy/DEPLOYED.json — по нему
# CI проверяет, что новая выкладка продолжает историю того, что уже на бою.
set -uo pipefail
STAGE=$1
COMMIT=${2:-unknown}
SOURCE=${3:-вручную}
D=/root/gb-deploy
PY="$D/venv/bin/python"
export OPENSSL_CONF="$D/gost-prov.cnf"

notify() {   # kind заголовок строка...
  local kind=$1 title=$2
  shift 2
  local args=()
  for l in "$@"; do args+=(--line "$l"); done
  (cd "$D/server" && "$PY" -m app.alarm --kind "$kind" --title "$title" "${args[@]}" >/dev/null 2>&1) || true
}

record() {   # часть ok
  "$PY" - "$D/DEPLOYED.json" "$1" "$2" "$COMMIT" "$SOURCE" <<'PYEOF'
import json, sys, time
path, part, ok, commit, source = sys.argv[1:6]
try:
    state = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    state = {}
if ok == "1":
    state[part] = {"commit": commit, "source": source, "ts": time.time()}
json.dump(state, open(path, "w", encoding="utf-8"), ensure_ascii=False)
PYEOF
}

health() { curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health; }

wait_health() {
  for _ in $(seq 1 30); do [ "$(health)" = 200 ] && return 0; sleep 2; done
  return 1
}

clear_pycache() {
  # Чужие .pyc прежней версии однажды уже давали «поведение старого кода при новом
  # файле». venv не трогаем: его байткод свой и только ускоряет старт.
  find "$D" -path "$D/venv" -prune -o -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
}

# ── сервер ──────────────────────────────────────────────────────────────────────────
apply_server() {
  test -f "$STAGE/app/main.py" || { echo "в выкладке нет app/main.py — не подменяю"; return 1; }
  # Прежние корневые модули — в архив: откат вернёт их вместе с app.old, иначе старое
  # приложение встало бы на новые модули.
  (cd "$STAGE/root" && find . -type f) > "$STAGE/root.list"
  tar -C "$D" -czf "$D/root.old.tgz" --ignore-failed-read -T "$STAGE/root.list" 2>/dev/null || true
  # Корневые модули — ПЕРВЫМИ: под новым приложением модуль обязан быть тоже новым.
  cp -r "$STAGE/root/." "$D/" || { echo "корневые модули не скопировались"; return 1; }
  rm -rf "$D/server/app.old"
  mv "$D/server/app" "$D/server/app.old" 2>/dev/null || true
  mv "$STAGE/app" "$D/server/app" || { mv "$D/server/app.old" "$D/server/app"; return 1; }
  clear_pycache
  systemctl restart gradebook

  # Смоук: то, что ломалось на деле — служба не встала (ImportError), главная не
  # отдаётся, API отвечает не тем кодом.
  local fails="" code
  check() {
    code=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000$1")
    [ "$code" = "$2" ] || fails="$fails $1=$code(ждали $2)"
  }
  if wait_health; then
    check / 200
    check /app/updates 200
    check /web/admin/net-takoy 404
    # При мягком рубильнике закрытый адрес отвечает 503 до проверки входа — не поломка.
    if curl -s -m 5 http://127.0.0.1:8000/app/maintenance | grep -q '"on": *false'; then
      check /web/admin/audit/integrity 401
    fi
  else
    fails=" /health не ответил за 60 с"
  fi
  if [ -z "$fails" ]; then
    echo "  сервер: смоук пройден (/health, /, /app/updates, коды API)"
    record server 1
    return 0
  fi

  echo "  СЕРВЕР: СМОУК НЕ ПРОШЁЛ:$fails — возвращаю прежнюю выкладку"
  rm -rf "$D/server/app.failed"
  mv "$D/server/app" "$D/server/app.failed" && mv "$D/server/app.old" "$D/server/app"
  [ -f "$D/root.old.tgz" ] && tar -C "$D" -xzf "$D/root.old.tgz"
  clear_pycache
  systemctl restart gradebook
  local state="прежняя выкладка вернулась и отвечает"
  wait_health || state="журнал НЕ поднялся и после отката"
  echo "  $state; неудачная выкладка лежит в server/app.failed"
  notify manual "Выкладка не прошла проверку и откачена" "Откуда: $SOURCE, коммит ${COMMIT:0:12}." \
    "Не ответило:$fails" "$state. Неудачный код — $D/server/app.failed."
  return 1
}

# ── сайт ────────────────────────────────────────────────────────────────────────────
apply_web() {
  test -f "$STAGE/webdist/index.html" || { echo "в выкладке нет index.html — не подменяю"; return 1; }
  # Свежим файлам — сегодняшнее время. Архив релиза воспроизводим, и время в нём одно на
  # все файлы — 1980 год; уборка «старше 14 дней» ниже стёрла бы весь новый сайт (первый
  # автодеплой 28.10.2026: бандл 404, смоук откатил). Старые чанки копируются ПОСЛЕ, с -p,
  # и своё время сохраняют.
  find "$STAGE/webdist" -type f -exec touch {} +
  # Старые чанки остаются жить (дефект 23.08.2026): у человека открыта вкладка со старой
  # сборкой, а ленивые части грузятся отдельными файлами. Имена содержат хеш содержимого,
  # поэтому старые и новые лежат рядом без конфликтов; --update=none — совпало имя, значит
  # совпало и содержимое; -p — время файла сохраняется, иначе уборка ниже не наступит
  # никогда. Ошибку не глушим: без старых чанков вернулся бы немой 404.
  if [ -d "$D/webdist/assets" ]; then
    cp -rp --update=none "$D/webdist/assets/." "$STAGE/webdist/assets/" || return 1
  fi
  rm -rf "$D/webdist.old"
  mv "$D/webdist" "$D/webdist.old" 2>/dev/null || true
  mv "$STAGE/webdist" "$D/webdist"
  # Старше двух недель чанки уже никому не нужны: за это время закрывают любую вкладку.
  find "$D/webdist/assets" -type f -mtime +14 -delete 2>/dev/null || true

  publish_static
  local b code
  b=$(curl -s -m 8 http://127.0.0.1:8000/ | grep -oE "index-[A-Za-z0-9_-]+\.js" | head -1)
  if [ -f /var/www/gb-maintenance/maintenance.on ] && [ -n "$b" ]; then
    echo "  сайт: жёсткий рубильник включён — снаружи 503, проверен только бандл $b"
    record web 1
    return 0
  fi
  code=$( [ -n "$b" ] && curl -s -m 15 -o /dev/null -w "%{http_code}" "https://esstu-gradebook.ru/assets/$b" )
  if [ -n "$b" ] && [ "$code" = 200 ]; then
    echo "  сайт: смоук пройден — бандл $b отдаётся снаружи"
    record web 1
    return 0
  fi
  echo "  САЙТ: СМОУК НЕ ПРОШЁЛ: бандл «${b:-нет в главной}», код $code — возвращаю прежний"
  rm -rf "$D/webdist.failed"
  mv "$D/webdist" "$D/webdist.failed" && mv "$D/webdist.old" "$D/webdist"
  publish_static
  notify manual "Выкладка сайта не прошла проверку и откачена" \
    "Откуда: $SOURCE, коммит ${COMMIT:0:12}." \
    "Бандл «${b:-нет}», код снаружи $code. Неудачная сборка — $D/webdist.failed."
  return 1
}

publish_static() {
  # Caddy отдаёт статику сам, минуя Python, но ходит под пользователем caddy, а /root
  # закрыт — нужна вторая копия в /var/www. Делается здесь же, одним действием с
  # выкладкой: разъехавшиеся копии — наш родной класс аварии. У assets нет --delete:
  # там файлы старых сборок, нужные открытым вкладкам.
  install -d -m 755 -o caddy -g caddy /var/www/gradebook
  for d in fonts icons mascot easter maintenance; do
    test -d "$D/webdist/$d" && rsync -a --delete "$D/webdist/$d/" "/var/www/gradebook/$d/"
  done
  rsync -a "$D/webdist/assets/" "/var/www/gradebook/assets/"
  find /var/www/gradebook/assets -type f -mtime +14 -delete 2>/dev/null || true
  # Жмём один раз при выкладке, а не на каждый запрос; уже сжатое (woff2, webp) не трогаем.
  # Только новые файлы: архивы прежних сборок уже лежат, пересжимать их — минуты процессора.
  find /var/www/gradebook -type f \( -name "*.js" -o -name "*.css" -o -name "*.svg" \
       -o -name "*.json" -o -name "*.webmanifest" -o -name "*.txt" \) -size +1k -print0 |
    while IFS= read -r -d "" f; do
      [ "$f.zst" -nt "$f" ] && [ "$f.gz" -nt "$f" ] && continue
      zstd -19 -q -f --keep "$f" -o "$f.zst"
      gzip -9 -kf "$f"
    done
  chown -R caddy:caddy /var/www/gradebook
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
}

rc=0
parts=""
if [ -d "$STAGE/app" ]; then
  if apply_server; then parts="журнал, главная, API"; else rc=1; fi
fi
if [ "$rc" = 0 ] && [ -d "$STAGE/webdist" ]; then
  if apply_web; then parts="${parts:+$parts, }бандл сайта снаружи"; else rc=1; fi
fi
if [ "$rc" = 0 ] && [ "${SOURCE#CI}" != "$SOURCE" ]; then
  # Каждая выкладка из CI — письмом (решение 28.10.2026): человек должен знать, что код
  # на бою сменился без него.
  notify deploy "Выкладка из CI прошла: ${COMMIT:0:12}" "$SOURCE" \
    "Смоук пройден: $parts." \
    "Откат, если понадобится: кнопка «Откат бэкап» или gb_restore.sh code."
fi
exit $rc
