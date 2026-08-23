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
  # ━━ СТАРЫЕ ЧАНКИ ОСТАЮТСЯ ЖИТЬ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # 🔥 Куплено дефектом 23.08.2026. У человека открыта вкладка со СТАРОЙ сборкой; часть
  # страниц и все сцены пасхалок подгружаются лениво, отдельными файлами. Выкладка
  # заменяла каталог целиком — и старые файлы исчезали. Дальше человек нажимал на
  # раздел, браузер шёл за своим чанком, получал 404, и НИЧЕГО НЕ ПРОИСХОДИЛО: ни
  # ошибки, ни объяснения. Поймано на пасхалке (сцена «выпала», а на экране пусто), но
  # касается это ЛЮБОЙ ленивой части приложения — за один деплой пропадало 20 файлов.
  # В колледже журнал держат открытым весь день, то есть попадание почти гарантировано.
  #
  # ⚠️ Имена ассетов содержат ХЕШ СОДЕРЖИМОГО (Vite), поэтому старые и новые файлы
  # спокойно лежат рядом и никогда не конфликтуют. Именно это и позволяет их не удалять.
  # ⚠️ `cp -n` (не перезаписывать) обязателен: совпало имя — значит совпало и
  # содержимое, и новый файл трогать нечем.
  # ⚠️ `-p` (сохранить время файла) ОБЯЗАТЕЛЕН, и это не мелочь. Без него копия
  # получает ТЕКУЩЕЕ время, значит перенесённые чанки при каждой выкладке молодеют, и
  # уборка `-mtime +14` ниже не наступает для них НИКОГДА: каталог рос бы бесконечно,
  # а комментарий «копятся не вечно» был бы неправдой (нашёл Полковник).
  # ⚠️ Ошибку НЕ глушим. Раньше стояло `2>/dev/null || true`: не скопировалось (нет
  # места, права) — выкладка проходила «успешно», старые чанки исчезали, и возвращался
  # ровно тот немой 404, ради которого правка и сделана. Пусть падает громко.
  if [ -d /root/gb-deploy/webdist/assets ]; then
    #  вместо : coreutils на бою предупреждает, что поведение 
    # непортируемо и может измениться. Смысл тот же — не трогать уже существующее.
    cp -rp --update=none /root/gb-deploy/webdist/assets/. /root/gb-deploy/webdist.new/assets/
  fi
  rm -rf /root/gb-deploy/webdist.old
  mv /root/gb-deploy/webdist /root/gb-deploy/webdist.old 2>/dev/null || true
  mv /root/gb-deploy/webdist.new /root/gb-deploy/webdist
  rm -f /root/gb-deploy/webdist.tgz
  # Копятся они не вечно: старше двух недель уже никому не нужны — за это время
  # закрывают даже самую забытую вкладку, а место на диске у нас 2.7 ГБ свободных.
  find /root/gb-deploy/webdist/assets -type f -mtime +14 -delete 2>/dev/null || true

  # ━━ ПУБЛИКАЦИЯ СТАТИКИ ДЛЯ CADDY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  # Зачем вторая копия: Caddy отдаёт ассеты сам, минуя Python (на одном ядре каждый
  # ассет иначе будит uvicorn). Но ходит он под пользователем caddy, а /root закрыт
  # правами drwx------ — из рабочего каталога он не прочитает НИЧЕГО и вернёт 403.
  # ⚠️ Копия делается ЗДЕСЬ ЖЕ, одним действием с основной выкладкой. Разъехавшиеся
  # копии — наш родной класс аварии; на этот случай в Caddyfile стоит матчер `file`:
  # нет файла в /var/www — запрос уходит на Python, как раньше (медленно, но цело).
  install -d -m 755 -o caddy -g caddy /var/www/gradebook
  # ⚠️ У `assets` НЕТ `--delete`, у остальных есть, и это не небрежность. В assets
  # лежат файлы с хешем содержимого, которые ещё нужны открытым вкладкам со старой
  # сборкой (см. выше); снеси их — и получишь тот самый немой 404. Остальные каталоги
  # заменяются целиком: там имена постоянные, и лишний старый файл только мешает.
  for d in fonts icons mascot easter; do
    test -d "/root/gb-deploy/webdist/$d" && rsync -a --delete       "/root/gb-deploy/webdist/$d/" "/var/www/gradebook/$d/"
  done
  rsync -a "/root/gb-deploy/webdist/assets/" "/var/www/gradebook/assets/"
  find /var/www/gradebook/assets -type f -mtime +14 -delete 2>/dev/null || true

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
