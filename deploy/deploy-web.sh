#!/usr/bin/env bash
# deploy-web.sh — НАДЁЖНЫЙ деплой веб-редакции на VPS.
#
# Проблема, которую решает: заливка dist множеством мелких файлов (scp -r) по флейковому
# каналу залипает и, если webdist перед этим очищен, оставляет сайт битым. Здесь:
#   1) собираем dist;
#   2) пакуем в ОДИН tar.gz (одна быстрая передача вместо десятков файлов);
#   3) на VPS распаковываем в webdist.new и АТОМАРНО подменяем (mv) — сайт ни секунды
#      не остаётся полупустым, есть откат (webdist.old);
#   4) reload caddy + проверка.
#
# Запуск локально из Git Bash:  bash deploy/deploy-web.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${GB_VPS_KEY:-$HOME/.ssh/gb_vps_ed25519}"
VPS="${GB_VPS:-root@194.226.120.74}"
O="-i $KEY -o BatchMode=yes -o ConnectTimeout=25"

echo "== [1/5] Сборка сайта =="
( cd "$ROOT/web" && npm run build )

echo "== [2/5] Упаковка dist в один архив =="
TAR="$(mktemp -u).tgz"
tar -C "$ROOT/web/dist" -czf "$TAR" .
echo "   размер архива: $(du -h "$TAR" | cut -f1)"

echo "== [3/5] Заливка (одна передача) =="
scp $O "$TAR" "$VPS:/root/gb-deploy/webdist.tgz"
rm -f "$TAR"

echo "== [4/5] Атомарная подмена на VPS =="
ssh $O "$VPS" 'set -e
  rm -rf /root/gb-deploy/webdist.new && mkdir -p /root/gb-deploy/webdist.new
  tar -C /root/gb-deploy/webdist.new -xzf /root/gb-deploy/webdist.tgz
  test -f /root/gb-deploy/webdist.new/index.html   # не подменяем битой распаковкой
  rm -rf /root/gb-deploy/webdist.old
  mv /root/gb-deploy/webdist /root/gb-deploy/webdist.old 2>/dev/null || true
  mv /root/gb-deploy/webdist.new /root/gb-deploy/webdist
  rm -f /root/gb-deploy/webdist.tgz
  systemctl reload caddy 2>/dev/null || systemctl restart caddy'

echo "== [5/5] Проверка =="
ssh $O "$VPS" 'echo "  bundle:" $(curl -s -m 8 http://127.0.0.1:8000/ | grep -oE "index-[A-Za-z0-9_-]+\.js" | head -1); echo "  caddy:" $(systemctl is-active caddy)'
echo "ГОТОВО. Если что-то не так — на VPS есть откат: mv webdist.old → webdist."
