#!/bin/bash
# Рубильник обслуживания GradeBookAI: весь сайт и API отвечают 503 со страницей
# «технические работы» (блок @maintenance в server/Caddyfile).
#
#   gb_maintenance.sh on      включить
#   gb_maintenance.sh off     выключить
#   gb_maintenance.sh status  что сейчас
#
# Страница лежит в /var/www/gb-maintenance (Caddy работает под пользователем caddy и в
# /root не заходит). Копию из репозитория кладёт `install` этого же скрипта.
set -euo pipefail
DIR=/var/www/gb-maintenance
FLAG="$DIR/maintenance.on"
SRC="$(cd "$(dirname "$0")" && pwd)/page"

case "${1:-status}" in
  install)
    mkdir -p "$DIR/_maint"
    cp "$SRC/index.html" "$DIR/index.html"
    cp "$SRC"/_maint/* "$DIR/_maint/"
    chmod -R a+rX "$DIR"
    echo "страница обслуживания обновлена в $DIR"
    ;;
  on)
    [ -f "$DIR/index.html" ] || { echo "сначала: $0 install" >&2; exit 1; }
    date -Is > "$FLAG"
    chmod a+r "$FLAG"
    echo "обслуживание ВКЛЮЧЕНО: сайт отвечает 503"
    ;;
  off)
    rm -f "$FLAG"
    echo "обслуживание выключено"
    ;;
  status)
    if [ -f "$FLAG" ]; then echo "включено с $(cat "$FLAG")"; else echo "выключено"; fi
    ;;
  *)
    echo "использование: $0 on|off|status|install" >&2; exit 2
    ;;
esac
