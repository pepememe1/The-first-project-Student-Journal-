#!/bin/bash
# Откат GradeBookAI: прежняя выкладка кода или база из ночной копии (27.10.2026).
# Его зовёт кнопка «Откат бэкап» на рабочем столе; руками — так же.
#
#   gb_restore.sh list               копии базы, новые сверху
#   gb_restore.sh db <N|файл> [--dry] вернуть базу из копии N (или файла); --dry — только план
#   gb_restore.sh code               вернуть прежнюю выкладку сервера и сайта; повтор — обратно
#
# Что важно и почему:
#   • текущая база не удаляется: перед подменой она уезжает в /root/gb-backups/pre-restore-*/
#     и сама попадает в `list` — передумал, вернул её тем же скриптом;
#   • якорь `.gradebook_server.db.sync-anchor.json` НЕ трогаем (§4.45): по нему служба на
#     старте увидит, что база помолодела, и сменит поколение синка сама;
#   • пока база подменяется, включён жёсткий рубильник (люди видят страницу работ, а не
#     ошибку), а сторожу тревог сказано не перезапускать журнал;
#   • журнал не поднялся с копией — прежняя база возвращается на место автоматически.
set -euo pipefail

#Пути переопределяются окружением только ради проверки в песочнице (копии в /tmp, без
#службы): настоящий откат на бою прогнать нельзя — он сменил бы поколение синка всем.
DEPLOY=${GB_DEPLOY:-/root/gb-deploy}
DB=${GB_DB:-$DEPLOY/server/gradebook_server.db}
ENV=${GB_ENV:-/root/gb-deploy/server/.env}
BACK=${GB_BACK:-/root/gb-backups}
PY=/root/gb-deploy/venv/bin/python
LOG=${GB_LOG:-/var/log/gb-backup.log}
SWITCH_CMD=${GB_SWITCH_CMD:-bash /root/gb-deploy/maintenance/gb_maintenance.sh}
PAUSE=${GB_PAUSE:-/run/gb-alarm.pause}
SERVICE=${GB_SERVICE-gradebook}
HEALTH=${GB_HEALTH:-http://127.0.0.1:8000/health}

log() { echo "$(date -Is) $*" >> "$LOG"; }
svc() { if [ -n "$SERVICE" ]; then systemctl "$1" "$SERVICE"; fi; }
health() { curl -s -m 5 -o /dev/null -w '%{http_code}' "$HEALTH" || true; }
wait_up() { for _ in $(seq 1 45); do [ "$(health)" = 200 ] && return 0; sleep 2; done; return 1; }
when() { TZ=Asia/Irkutsk date -d "@$(stat -c %Y "$1")" '+%d.%m.%Y %H:%M'; }
pause_alarm() { echo $(( $(date +%s) + $1 )) > "$PAUSE"; }

snapshots() {
  ls -1t "$BACK"/auto/gradebook_*.db 2>/dev/null || true
  ls -1t "$BACK"/pre-restore-*/gradebook_server.db 2>/dev/null || true
}

list() {
  local i=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    i=$((i + 1))
    case "$f" in
      */pre-restore-*) kind="база до прошлого отката" ;;
      *)               kind="ночная копия" ;;
    esac
    printf '%3d  %s  %6s  %s\n' "$i" "$(when "$f")" "$(du -h "$f" | cut -f1)" "$kind"
  done < <(snapshots)
  [ "$i" -gt 0 ] || echo "копий нет"
}

verify() {   # открыть копию ключом базы: целостность и пользователи
  local key
  key=$(grep -E '^GRADEBOOK_DB_KEY=' "$ENV" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')
  GB_KEY="$key" OPENSSL_CONF=/root/gb-deploy/gost-prov.cnf "$PY" - "$1" <<'PYEOF'
import os, sys, sqlcipher3
c = sqlcipher3.connect(sys.argv[1])
c.execute("PRAGMA key = \"x'%s'\"" % os.environ["GB_KEY"])
ok = c.execute("PRAGMA integrity_check").fetchone()[0]
assert ok == "ok", "integrity_check=%r" % ok
print(c.execute("SELECT count(*) FROM users").fetchone()[0])
PYEOF
}

restore_db() {
  local pick="$1" dry="${2:-}" src
  if [[ "$pick" =~ ^[0-9]+$ ]]; then
    src=$(snapshots | sed -n "${pick}p")
  else
    src=$(readlink -f "$pick")
  fi
  [ -n "$src" ] && [ -f "$src" ] || { echo "нет копии «$pick» — смотри: $0 list" >&2; exit 2; }
  [[ "$src" == "$BACK"/* ]] || { echo "восстанавливаю только из $BACK" >&2; exit 2; }
  echo "копия: $src ($(when "$src") по времени колледжа)"
  users=$(verify "$src") || { echo "КОПИЯ БИТАЯ или не открывается ключом — отказ" >&2; exit 3; }
  echo "копия цела: integrity_check ok, пользователей $users"
  ts=$(date +%Y%m%d_%H%M%S)
  keep="$BACK/pre-restore-$ts"
  if [ "$dry" = "--dry" ]; then
    echo "ПЛАН (ничего не меняю): рубильник → стоп журнала → нынешняя база в $keep → копия на место → старт → рубильник выкл."
    exit 0
  fi
  pause_alarm 900
  was_on=0
  [ -f /var/www/gb-maintenance/maintenance.on ] && was_on=1
  [ "$was_on" = 1 ] || $SWITCH_CMD on
  svc stop
  #mktemp, а не имя по секунде: два отката в одну секунду (песочница) клали базу поверх
  #сохранённой первым.
  keep=$(mktemp -d "$keep-XXXX")
  for f in "$DB" "$DB-wal" "$DB-shm"; do if [ -e "$f" ]; then mv "$f" "$keep/"; fi; done
  cp "$src" "$DB"
  chmod 600 "$DB"
  svc start
  if wait_up; then
    log "RESTORE: база из $src, прежняя — $keep"
    echo "ГОТОВО: база возвращена к копии от $(when "$src")."
    echo "прежняя база сохранена: $keep (вернуть: $0 db $keep/gradebook_server.db)"
    rc=0
  else
    echo "ЖУРНАЛ НЕ ПОДНЯЛСЯ с этой копией — возвращаю прежнюю базу" >&2
    svc stop
    rm -f "$DB" "$DB-wal" "$DB-shm"
    for f in "$keep"/*; do mv "$f" "$(dirname "$DB")/"; done
    rmdir "$keep"
    svc start
    if wait_up; then echo "прежняя база на месте, журнал работает" >&2; fi
    log "RESTORE FAIL: $src не поднялся, прежняя база возвращена"
    rc=1
  fi
  [ "$was_on" = 1 ] || $SWITCH_CMD off
  rm -f "$PAUSE"
  exit "$rc"
}

swap() {   # поменять местами каталог и его .old
  local cur="$1"
  [ -d "$cur.old" ] || { echo "нет $cur.old — откатывать не к чему" >&2; return 1; }
  mv "$cur" "$cur.swap"
  mv "$cur.old" "$cur"
  mv "$cur.swap" "$cur.old"
}

rollback_code() {
  [ -d "$DEPLOY/server/app.old" ] || { echo "прежней выкладки нет (app.old)" >&2; exit 2; }
  pause_alarm 300
  swap "$DEPLOY/server/app"
  swap "$DEPLOY/webdist" || true
  find "$DEPLOY/server/app" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  svc restart
  if wait_up; then
    bundle=$(grep -oE 'index-[A-Za-z0-9_-]+\.js' "$DEPLOY/webdist/index.html" | head -1 || true)
    log "ROLLBACK: код переключён на выкладку от $(when "$DEPLOY/server/app")"
    echo "ГОТОВО: работает выкладка сервера от $(when "$DEPLOY/server/app"), сайт ${bundle:-?}."
    echo "вернуть новую обратно: запусти откат кода ещё раз."
    rc=0
  else
    echo "С ПРЕЖНЕЙ ВЫКЛАДКОЙ ЖУРНАЛ НЕ ПОДНЯЛСЯ — возвращаю как было" >&2
    swap "$DEPLOY/server/app"
    swap "$DEPLOY/webdist" || true
    svc restart
    wait_up && echo "вернул, журнал работает" >&2
    rc=1
  fi
  rm -f "$PAUSE"
  exit "$rc"
}

case "${1:-list}" in
  list) list ;;
  db)   restore_db "${2:?укажи номер копии из list}" "${3:-}" ;;
  code) rollback_code ;;
  *)    echo "использование: $0 list | db <N|файл> [--dry] | code" >&2; exit 2 ;;
esac
