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
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -r "$ROOT/web/dist" "$STAGE/webdist"
TAR="$(mktemp -u).tgz"
tar -C "$STAGE" -czf "$TAR" webdist
echo "   размер архива: $(du -h "$TAR" | cut -f1)"

echo "== [3/5] Заливка (одна передача) =="
# Подмену, сохранение старых чанков, копию для Caddy, сжатие, смоук и откат делает
# apply_release.sh — тот же, что зовёт автодеплой из CI (28.10.2026).
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
[ -n "$(git -C "$ROOT" status --porcelain -- web)" ] && COMMIT="$COMMIT+dirty"
scp $O "$TAR" "$VPS:/root/gb-deploy/webdist.tgz"
scp $O "$ROOT/deploy/apply_release.sh" "$VPS:/root/gb-deploy/maintenance/apply_release.sh.new"
rm -f "$TAR"

echo "== [4/5] Подмена, смоук, автооткат (apply_release.sh) =="
if ! ssh $O "$VPS" "set -e
  cd /root/gb-deploy/maintenance
  sed -i 's/\r\$//' apply_release.sh.new && mv apply_release.sh.new apply_release.sh
  rm -rf /root/gb-deploy/stage-web && mkdir -p /root/gb-deploy/stage-web
  tar -C /root/gb-deploy/stage-web -xzf /root/gb-deploy/webdist.tgz
  rm -f /root/gb-deploy/webdist.tgz
  bash apply_release.sh /root/gb-deploy/stage-web '$COMMIT' 'вручную: deploy-web.sh'
  rm -rf /root/gb-deploy/stage-web"
then
  echo "ВЫКЛАДКА САЙТА ОТКАЧЕНА — смотри причину выше."
  exit 1
fi
echo "== [5/5] Готово =="
echo "ГОТОВО. Ручной откат, если понадобится: кнопка «Откат бэкап» или gb_restore.sh code на VPS."
