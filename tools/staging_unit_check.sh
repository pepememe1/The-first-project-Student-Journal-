#!/usr/bin/env bash
# staging_unit_check.sh — проверить ужесточённый юнит ДО того, как он станет боевым.
#
# ━━ ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ ШАГ, А НЕ ДОВЕРИЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Ужесточение systemd ломает молча и не там, где смотришь. Живой пример из нашего же
# захода: `ProtectHome=yes` при коде в /root/gb-deploy делает каталог кода невидимым —
# служба не находит собственный serve.py. Ни одна проверка «файл юнита корректен» этого
# не увидит: синтаксис безупречен, а сервер мёртв.
# Поэтому проверка идёт В ТРИ ступени, и каждая ловит своё:
#   1) разбор — `systemd-analyze verify` (опечатки в именах директив);
#   2) ЗАПУСК под копией имени (gradebook-staging) и живой /health — единственное, что
#      доказывает работоспособность;
#   3) `systemd-analyze security` — оценка и перечень оставшихся дыр.
#
# Использование (на целевой машине, от root):
#   bash tools/staging_unit_check.sh                       # проверить gradebook.service
#   bash tools/staging_unit_check.sh --port 8099           # свой порт для staging
set -euo pipefail

UNIT="/etc/systemd/system/gradebook.service"
STAGING="gradebook-staging"
PORT="8099"
KEEP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --unit) UNIT="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    *) echo "неизвестный аргумент: $1" >&2; exit 2;;
  esac
done

[ -f "$UNIT" ] || { echo "нет юнита: $UNIT" >&2; exit 2; }
[ "$(id -u)" = "0" ] || { echo "нужны права root" >&2; exit 2; }

fail=0

echo "== 1/3 разбор юнита =="
if systemd-analyze verify "$UNIT" 2>&1 | tee /tmp/gb-verify.txt | grep -q .; then
  echo "   ⚠️ systemd-analyze verify не молчит:"
  sed 's/^/      /' /tmp/gb-verify.txt
  # Не роняем сразу: verify ругается и на безобидное (например, на отсутствующий
  # каталог, который создаст сам systemd при старте). Решение — за человеком, но
  # молчать об этом нельзя.
else
  echo "   разбор чистый"
fi

echo "== 2/3 запуск под именем $STAGING на порту $PORT =="
# Копия юнита с другим портом и другим StateDirectory: боевое состояние staging не
# трогает НИКОГДА. Порча боевой базы проверкой — ровно то, ради чего staging и заводят.
sed -e "s/^Environment=GRADEBOOK_PORT=.*/Environment=GRADEBOOK_PORT=$PORT/" \
    -e "s/^StateDirectory=gradebook$/StateDirectory=gradebook-staging/" \
    -e "s|^Environment=GRADEBOOK_DB_URL=.*|Environment=GRADEBOOK_DB_URL=sqlite:////var/lib/gradebook-staging/gradebook_server.db|" \
    -e "s|^Environment=GRADEBOOK_FILES_DIR=.*|Environment=GRADEBOOK_FILES_DIR=/var/lib/gradebook-staging/attachments|" \
    "$UNIT" > "/etc/systemd/system/$STAGING.service"
systemctl daemon-reload
systemctl start "$STAGING" || true

ok=0
for i in $(seq 1 20); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" 2>/dev/null || echo 000)"
  if [ "$code" = "200" ]; then ok=1; echo "   /health отвечает 200 (через ${i}с)"; break; fi
  sleep 1
done
if [ "$ok" != "1" ]; then
  echo "   ⛔ staging НЕ поднялся. Это и есть тот отказ, ради которого шаг существует." >&2
  journalctl -u "$STAGING" -n 40 --no-pager >&2 || true
  fail=1
fi

echo "== 3/3 оценка ужесточения =="
systemd-analyze security "$STAGING.service" 2>/dev/null | tail -25 || \
  echo "   systemd-analyze security недоступен"

# Обязательные директивы проверяем ТЕКСТОМ, а не оценкой: балл — сводная величина, он
# может остаться приличным при выпавшей ключевой строке.
echo "== обязательный набор =="
for d in "NoNewPrivileges=yes" "ProtectSystem=strict" "PrivateTmp=yes" \
         "PrivateDevices=yes" "ProtectKernelTunables=yes" "ProtectKernelModules=yes" \
         "ProtectControlGroups=yes" "CapabilityBoundingSet=" \
         "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" \
         "SystemCallFilter=@system-service" "User=gradebook"; do
  if grep -qF "$d" "$UNIT"; then
    printf '   ✅ %s\n' "$d"
  else
    printf '   ⛔ НЕТ: %s\n' "$d"
    fail=1
  fi
done
if grep -qE "^ProtectHome=(yes|read-only)" "$UNIT"; then
  printf '   ✅ %s\n' "$(grep -E '^ProtectHome=' "$UNIT")"
else
  printf '   ⛔ НЕТ: ProtectHome\n'; fail=1
fi
if grep -qE "^User=root" "$UNIT"; then
  printf '   ⛔ служба всё ещё от root\n'; fail=1
fi

if [ "$KEEP" != "1" ]; then
  systemctl stop "$STAGING" 2>/dev/null || true
  rm -f "/etc/systemd/system/$STAGING.service"
  rm -rf /var/lib/gradebook-staging
  systemctl daemon-reload
  echo "staging убран"
fi

[ "$fail" = "0" ] && echo "ИТОГ: юнит пригоден к бою" || echo "ИТОГ: ЕСТЬ ЗАМЕЧАНИЯ, в бой не переводить"
exit "$fail"
