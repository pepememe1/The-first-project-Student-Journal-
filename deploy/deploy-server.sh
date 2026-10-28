#!/usr/bin/env bash
# deploy-server.sh — НАДЁЖНЫЙ деплой СЕРВЕРНОГО кода на VPS.
#
# Проблема, которую решает: до сих пор серверный код заливался вручную — scp
# ОДНОГО файла (обычно server/app/routers/web.py, см. web/deploy/update-vps.ps1),
# который правили чаще остальных. Как только правки легли в ДРУГОЙ файл, тот
# скрипт их молча не заливал: сервер отвечал 404/405 на новые эндпоинты, хотя
# локально всё было готово и протестировано. Здесь — ВЕСЬ server/app/ одним
# архивом (атомарная схема: пакуем → заливаем ОДНИМ файлом → распаковываем в
# .new → mv на место, с откатом на .old).
#
# 🔥 КОРНЕВЫЕ ОБЩИЕ МОДУЛИ ЕДУТ ЭТИМ ЖЕ АРХИВОМ, И СПИСОК ИХ НЕ ХРАНИТСЯ.
# Куплено дефектом 28.08.2026: `server/app` начал импортировать НОВЫЙ корневой
# `teacher_match.py`, а скрипт вёз только `server/app` — на бою это был бы не
# «фича не работает», а ImportError при старте, то есть журнал не поднялся бы
# вовсе. Ровно тот же класс аварии ронял прод дважды до этого (`webdata.py`,
# `weather.py`, `study_hours.py`): человек помнил про архив с приложением и
# забывал про отдельный scp корневого модуля.
# ⚠️ Список ВЫВОДИТСЯ ИЗ ИМПОРТОВ `server/app`, а не лежит здесь копией. Копия —
# это снимок значения: она молча устаревает ровно в тот день, когда добавили
# новый общий модуль, то есть отказывает именно тогда, когда нужна. Здесь забыть
# нечего по построению: появился импорт — модуль поехал.
#
# НЕ трогаем: server/.env (JWT-секрет, ключ SQLCipher) и БД — они на уровень
# ВЫШЕ server/app/, в архив не попадают в принципе.
#
# Запуск локально из Git Bash:  bash deploy/deploy-server.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${GB_VPS_KEY:-$HOME/.ssh/gb_vps_ed25519}"
VPS="${GB_VPS:-root@194.226.120.74}"
O="-i $KEY -o BatchMode=yes -o ConnectTimeout=25"

echo "== [1/5] Какие корневые модули нужны серверу =="
# Берём голову импорта (`import X` / `from X import ...`) во всём server/app и
# оставляем те имена, которым в КОРНЕ репозитория соответствует файл .py или
# пакет. Стандартная библиотека и пакеты venv отсеиваются сами — их в корне нет.
MODS="$(grep -rhoE '^[[:space:]]*(import|from)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' \
          "$ROOT/server/app" --include='*.py' \
        | awk '{print $2}' | sort -u \
        | while read -r m; do
            # ⚠️ `if`, а не `[ ... ] && echo`: под `set -e` + `pipefail` неудачная
            # проверка на ПОСЛЕДНЕЙ строке цикла делает ненулевым весь цикл, и
            # присваивание молча убивает скрипт — поймано прямо на этом месте.
            if [ -f "$ROOT/$m.py" ]; then echo "$m.py"; fi
            if [ -f "$ROOT/$m/__init__.py" ]; then echo "$m"; fi
          done | sort -u)"
[ -z "$MODS" ] && { echo "ОШИБКА: не нашлось ни одного корневого модуля — разбор импортов сломался" >&2; exit 1; }
echo "$MODS" | sed 's/^/   /'

echo "== [2/5] Упаковка server/app + корневых модулей в один архив =="
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/payload/root"
cp -r "$ROOT/server/app" "$STAGE/payload/app"
# __pycache__ незачем везти: на бою другой Python, и чужие .pyc только путают.
find "$STAGE/payload" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
while IFS= read -r m; do
  cp -r "$ROOT/$m" "$STAGE/payload/root/$m"
done <<< "$MODS"
find "$STAGE/payload/root" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
TAR="$(mktemp -u).tgz"
tar -C "$STAGE/payload" -czf "$TAR" app root
echo "   размер архива: $(du -h "$TAR" | cut -f1)"

echo "== [3/5] Заливка (одна передача) =="
# Вместе с архивом едет свежий apply_release.sh: подмену, смоук и откат делает он — тот
# же, что зовёт автодеплой из CI. Одна реализация на оба пути (28.10.2026).
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
[ -n "$(git -C "$ROOT" status --porcelain -- server/app)" ] && COMMIT="$COMMIT+dirty"
scp $O "$TAR" "$VPS:/root/gb-deploy/server-app.tgz"
scp $O "$ROOT/deploy/apply_release.sh" "$VPS:/root/gb-deploy/maintenance/apply_release.sh.new"
rm -f "$TAR"

echo "== [4/5] Подмена, смоук, автооткат (apply_release.sh) =="
if ! ssh $O "$VPS" "set -e
  cd /root/gb-deploy/maintenance
  sed -i 's/\r\$//' apply_release.sh.new && mv apply_release.sh.new apply_release.sh
  rm -rf /root/gb-deploy/stage && mkdir -p /root/gb-deploy/stage
  tar -C /root/gb-deploy/stage -xzf /root/gb-deploy/server-app.tgz
  rm -f /root/gb-deploy/server-app.tgz
  bash apply_release.sh /root/gb-deploy/stage '$COMMIT' 'вручную: deploy-server.sh'
  rm -rf /root/gb-deploy/stage"
then
  echo "ВЫКЛАДКА ОТКАЧЕНА — смотри причину выше. Код на бою прежний."
  exit 1
fi
echo "== [5/5] Готово =="
echo "ГОТОВО. Ручной откат, если понадобится: кнопка «Откат бэкап» или gb_restore.sh code на VPS."
