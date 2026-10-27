#!/bin/bash
# Жёсткий рубильник обслуживания GradeBookAI: весь сайт и API отвечают 503 страницей
# «технические работы» (блок @maintenance в server/Caddyfile). Нужен, когда само приложение
# лежит или его заменяют; в обычных случаях — мягкий рубильник в админке («Сервер»), там
# админка остаётся доступной. Страница у обоих одна: web/public/maintenance/.
#
#   gb_maintenance.sh on      включить
#   gb_maintenance.sh off     выключить
#   gb_maintenance.sh status  что сейчас
set -euo pipefail
FLAG_DIR=/var/www/gb-maintenance
FLAG="$FLAG_DIR/maintenance.on"
PAGE=/var/www/gradebook/maintenance/index.html

case "${1:-status}" in
  on)
    [ -f "$PAGE" ] || { echo "нет $PAGE — сначала выложи сайт (deploy/deploy-web.sh)" >&2; exit 1; }
    mkdir -p "$FLAG_DIR"
    chmod 755 "$FLAG_DIR"
    date -Is > "$FLAG"
    chmod a+r "$FLAG"
    echo "жёсткий рубильник ВКЛЮЧЁН: сайт отвечает 503"
    ;;
  off)
    rm -f "$FLAG"
    echo "жёсткий рубильник выключен"
    ;;
  status)
    if [ -f "$FLAG" ]; then echo "включён с $(cat "$FLAG")"; else echo "выключен"; fi
    ;;
  *)
    echo "использование: $0 on|off|status" >&2; exit 2
    ;;
esac
