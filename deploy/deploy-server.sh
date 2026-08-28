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
scp $O "$TAR" "$VPS:/root/gb-deploy/server-app.tgz"
rm -f "$TAR"

echo "== [4/5] Атомарная подмена на VPS =="
ssh $O "$VPS" 'set -e
  rm -rf /root/gb-deploy/stage && mkdir -p /root/gb-deploy/stage
  tar -C /root/gb-deploy/stage -xzf /root/gb-deploy/server-app.tgz
  test -f /root/gb-deploy/stage/app/main.py   # не подменяем битой распаковкой
  # Корневые модули кладём ПЕРВЫМИ: приложение новое, а модуль под ним обязан
  # быть тоже новым — иначе окно, в котором свежий app зовёт старый study_hours.
  cp -r /root/gb-deploy/stage/root/. /root/gb-deploy/
  rm -rf /root/gb-deploy/server/app.old
  mv /root/gb-deploy/server/app /root/gb-deploy/server/app.old 2>/dev/null || true
  mv /root/gb-deploy/stage/app /root/gb-deploy/server/app
  rm -rf /root/gb-deploy/stage /root/gb-deploy/server-app.tgz
  # Чужие .pyc от предыдущей версии переживают подмену каталога и однажды уже
  # давали «поведение старого кода при новом файле».
  find /root/gb-deploy -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
  systemctl restart gradebook'

echo "== [5/5] Проверка =="
sleep 3
ssh $O "$VPS" 'echo "  gradebook:" $(systemctl is-active gradebook); curl -s -m 10 -o /dev/null -w "  /health: %{http_code}\n" http://127.0.0.1:8000/health'
echo "ГОТОВО. Если что-то не так — на VPS есть откат: mv /root/gb-deploy/server/app.old → app, systemctl restart gradebook."
