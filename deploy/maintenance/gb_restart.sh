#!/bin/bash
# Перезапуск GradeBookAI с проверкой, что журнал действительно поднялся (27.10.2026).
# Его зовёт кнопка «Рестарт сервера» на рабочем столе; руками — так же.
#
#   gb_restart.sh          журнал (обычно этого хватает: 5–10 секунд без сайта)
#   gb_restart.sh all      журнал и Caddy
#   gb_restart.sh reboot   перезагрузить всю машину (1–2 минуты без сайта)
set -uo pipefail

health() { curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health; }

wait_up() {
  for i in $(seq 1 45); do
    if [ "$(health)" = 200 ]; then echo "журнал отвечает (через $((i * 2)) с)"; return 0; fi
    sleep 2
  done
  return 1
}

case "${1:-app}" in
  app)    echo "перезапускаю журнал…"; systemctl restart gradebook ;;
  all)    echo "перезапускаю журнал и Caddy…"; systemctl restart gradebook; systemctl restart caddy ;;
  reboot) echo "машина уходит в перезагрузку — сайт вернётся через 1–2 минуты"
          systemctl reboot; exit 0 ;;
  *)      echo "использование: $0 [app|all|reboot]" >&2; exit 2 ;;
esac

if ! wait_up; then
  echo "ЖУРНАЛ НЕ ПОДНЯЛСЯ за 90 секунд. Последние строки его журнала:"
  journalctl -u gradebook -n 25 --no-pager -o cat
  exit 1
fi
site=$(curl -s -m 10 -o /dev/null -w '%{http_code}' https://esstu-gradebook.ru/health)
if [ -f /var/www/gb-maintenance/maintenance.on ]; then
  echo "сайт снаружи: $site (включён жёсткий рубильник — 503 для людей так и задумано)"
elif [ "$site" = 200 ]; then
  echo "сайт снаружи открывается (200)"
else
  echo "СНАРУЖИ САЙТ НЕ ОТКРЫВАЕТСЯ (код $site), хотя журнал жив — попробуй: $0 all"
  exit 1
fi
