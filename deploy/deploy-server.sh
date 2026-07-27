#!/usr/bin/env bash
# deploy-server.sh — НАДЁЖНЫЙ деплой СЕРВЕРНОГО кода (server/app/**) на VPS.
#
# Проблема, которую решает: до сих пор серверный код заливался вручную — scp
# ОДНОГО файла (обычно server/app/routers/web.py, см. web/deploy/update-vps.ps1),
# который правили чаще остальных. Как только правки легли в ДРУГОЙ файл
# (routers/parent.py, routers/messenger.py, models.py — как в этой сессии), тот
# скрипт их молча не заливал: сервер отвечал 404/405 на новые эндпоинты, хотя
# локально всё было готово и протестировано. Здесь — ВЕСЬ server/app/ одним
# архивом (та же атомарная схема, что в deploy-web.sh: пакуем → заливаем ОДНИМ
# файлом → распаковываем в .new → mv на место, с откатом на .old).
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

echo "== [1/4] Упаковка server/app в один архив =="
TAR="$(mktemp -u).tgz"
tar -C "$ROOT/server" -czf "$TAR" app
echo "   размер архива: $(du -h "$TAR" | cut -f1)"

echo "== [2/4] Заливка (одна передача) =="
scp $O "$TAR" "$VPS:/root/gb-deploy/server-app.tgz"
rm -f "$TAR"

echo "== [3/4] Атомарная подмена на VPS =="
ssh $O "$VPS" 'set -e
  rm -rf /root/gb-deploy/server/app.new && mkdir -p /root/gb-deploy/server/app.new
  tar -C /root/gb-deploy/server/app.new -xzf /root/gb-deploy/server-app.tgz --strip-components=1
  test -f /root/gb-deploy/server/app.new/main.py   # не подменяем битой распаковкой
  rm -rf /root/gb-deploy/server/app.old
  mv /root/gb-deploy/server/app /root/gb-deploy/server/app.old 2>/dev/null || true
  mv /root/gb-deploy/server/app.new /root/gb-deploy/server/app
  rm -f /root/gb-deploy/server-app.tgz
  systemctl restart gradebook'

echo "== [4/4] Проверка =="
sleep 2
ssh $O "$VPS" 'echo "  gradebook:" $(systemctl is-active gradebook); curl -s -m 8 -o /dev/null -w "  /health: %{http_code}\n" http://127.0.0.1:8000/health'
echo "ГОТОВО. Если что-то не так — на VPS есть откат: mv /root/gb-deploy/server/app.old → app, systemctl restart gradebook."
