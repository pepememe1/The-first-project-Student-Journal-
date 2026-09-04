#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════════
# check_prod_caddyfile.sh — сверяет БОЕВОЙ Caddyfile с тем, что лежит в git.
#
# ━━ ЗАЧЕМ ━━
# `server/tests/test_caddyfile.py` (52 проверки) стережёт файл В РЕПОЗИТОРИИ, и в его
# собственной шапке честно записана граница: «тест читает ФАЙЛ, а не живой сервер — на
# бою конфиг может отличаться, и правка руками на машине переживёт деплой ровно до
# следующего». Этот скрипт закрывает ровно эту дыру: он единственный, кто смотрит на
# машину.
#
# ━━ ПОЧЕМУ НОРМАЛИЗУЕМ ПЕРЕВОДЫ СТРОК ━━
# В git файл лежит с CRLF (правится на Windows), на бою — с LF. Сырое сравнение хешей
# даёт ложное расхождение на файлах, идентичных посимвольно: проверено 03.09.2026 —
# 15 097 байт против 14 914, разница ровно в 183 перевода строки, а содержимое одно.
# Тот же приём уже применяется при сверке корневых модулей (CLAUDE.md §8.1).
#
# ━━ КАК ЗВАТЬ ━━
#   bash tools/check_prod_caddyfile.sh          # сверить
#   bash tools/check_prod_caddyfile.sh --diff   # и показать расхождение построчно
#
# Код выхода: 0 — совпало, 1 — разошлось, 2 — не смог проверить (нет связи/файла).
# Ненулевой код значим: скрипт предназначен для предделойных ворот, где расхождение
# обязано ОСТАНОВИТЬ выкладку, а не попасть в лог, который никто не читает.
# ═══════════════════════════════════════════════════════════════════════════════════
set -uo pipefail

HOST="${GB_SSH_HOST:-gb}"          # алиас из ~/.ssh/config
REMOTE="/etc/caddy/Caddyfile"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL="$ROOT/server/Caddyfile"
SHOW_DIFF="${1:-}"

if [ ! -f "$LOCAL" ]; then
  echo "ОШИБКА: нет $LOCAL — боевой конфиг пропал из репозитория" >&2
  exit 2
fi

# Локальный хеш: нормализуем CRLF -> LF, иначе сравнение врёт (см. шапку).
local_hash="$(sed 's/\r$//' "$LOCAL" | md5sum | cut -d' ' -f1)"

remote_hash="$(ssh -o ConnectTimeout=15 -o BatchMode=yes "$HOST" \
  "sed 's/\r\$//' $REMOTE 2>/dev/null | md5sum | cut -d' ' -f1" 2>/dev/null)"

if [ -z "$remote_hash" ]; then
  echo "ОШИБКА: не удалось прочитать $REMOTE на $HOST (нет связи или файла)" >&2
  echo "        Это НЕ «всё хорошо»: проверка не выполнена, выкладку не продолжать." >&2
  exit 2
fi

if [ "$local_hash" = "$remote_hash" ]; then
  echo "OK: боевой Caddyfile совпадает с git ($local_hash)"
  exit 0
fi

echo "🔥 РАСХОЖДЕНИЕ: боевой Caddyfile НЕ совпадает с git" >&2
echo "   git:  $local_hash" >&2
echo "   бой:  $remote_hash" >&2
echo "" >&2
echo "   Значит на машине правили руками, и 52 теста стерегут файл, которого на бою" >&2
echo "   нет. Либо перенесите правку в git, либо выложите git-версию:" >&2
echo "     scp server/Caddyfile $HOST:$REMOTE && ssh $HOST 'systemctl reload caddy'" >&2

if [ "$SHOW_DIFF" = "--diff" ]; then
  echo "" >&2
  echo "── расхождение (слева git, справа бой) ──" >&2
  tmp_remote="$(mktemp)"
  trap 'rm -f "$tmp_remote"' EXIT
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$HOST" "cat $REMOTE" 2>/dev/null \
    | sed 's/\r$//' > "$tmp_remote"
  diff <(sed 's/\r$//' "$LOCAL") "$tmp_remote" >&2 || true
fi

exit 1
