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

  # ━━ ПУБЛИКАЦИЯ СТАТИКИ ДЛЯ CADDY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # Зачем вторая копия: Caddy отдаёт ассеты сам, минуя Python (на одном ядре каждый
  # ассет иначе будит uvicorn). Но ходит он под пользователем caddy, а /root закрыт
  # правами drwx------ — из рабочего каталога он не прочитает НИЧЕГО и вернёт 403.
  # ⚠️ Копия делается ЗДЕСЬ ЖЕ, одним действием с основной выкладкой. Разъехавшиеся
  # копии — наш родной класс аварии; на этот случай в Caddyfile стоит матчер `file`:
  # нет файла в /var/www — запрос уходит на Python, как раньше (медленно, но цело).
  install -d -m 755 -o caddy -g caddy /var/www/gradebook
  for d in assets fonts icons mascot; do
    test -d "/root/gb-deploy/webdist/$d" && rsync -a --delete       "/root/gb-deploy/webdist/$d/" "/var/www/gradebook/$d/"
  done

  # Жмём ОДИН РАЗ при выкладке, а не на каждый запрос: 1.3 МБ бандла zstd-ом на одном
  # ядре — это ощутимо, и платить за это при каждом промахе кэша незачем. woff2 и webp
  # не трогаем: они уже сжаты, повторное сжатие только тратит место и время.
  find /var/www/gradebook -type f \( -name "*.js" -o -name "*.css" -o -name "*.svg"        -o -name "*.json" -o -name "*.webmanifest" -o -name "*.txt" \) -size +1k        -print0 | while IFS= read -r -d "" f; do
    zstd -19 -q -f --keep "$f" -o "$f.zst"
    gzip -9 -kf "$f"
  done
  chown -R caddy:caddy /var/www/gradebook

  systemctl reload caddy 2>/dev/null || systemctl restart caddy'

echo "== [5/5] Проверка =="
ssh $O "$VPS" 'echo "  bundle:" $(curl -s -m 8 http://127.0.0.1:8000/ | grep -oE "index-[A-Za-z0-9_-]+\.js" | head -1); echo "  caddy:" $(systemctl is-active caddy)'
echo "ГОТОВО. Если что-то не так — на VPS есть откат: mv webdist.old → webdist."
