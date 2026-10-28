#!/bin/bash
# Учения восстановления (27.10.2026): раз в неделю свежая ночная копия поднимается рядом с
# боем вторым экземпляром журнала и проверяется так, как её проверял бы человек в аварию.
#
# Почему не хватает ночной проверки gb_backup.sh: integrity_check доказывает, что файл цел,
# но не то, что с ним встанет журнал (миграции, ключ, якорь синка). Копия, из которой не
# поднимались, — надежда, а не копия (Google называет это «учениями», DiRT).
#
# Второй экземпляр живёт на 127.0.0.1:8091 с базой в /tmp: якорь синка и файл рубильника
# лежат рядом с базой, то есть тоже в /tmp, и бой не задевают. Запросов от людей к нему нет,
# поэтому ни писем, ни пушей он не шлёт. Итог — /var/lib/gb-backup/drill.json и вечерняя
# сводка; провал — письмо сторожа тревог сразу.
set -uo pipefail

DEPLOY=/root/gb-deploy
BACK=/root/gb-backups/auto
STATE=/var/lib/gb-backup
LOG=/var/log/gb-backup.log
PORT=8091
PY="$DEPLOY/venv/bin/python"

mkdir -p "$STATE"
log() { echo "$(date -Is) $*" >> "$LOG"; }

snap=$(ls -1t "$BACK"/gradebook_*.db 2>/dev/null | head -1)
D=$(mktemp -d /tmp/gb-drill-XXXX)
pid=""
cleanup() {
  if [ -n "$pid" ]; then kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; fi
  rm -rf "$D"
}
trap cleanup EXIT

result() {   # ok detail [boot users grades chain]
  "$PY" - "$STATE/drill.json" "$@" <<'PYEOF'
import json, sys, time
path, ok, detail = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
extra = dict(zip(("boot_s", "users", "grades", "chain", "snapshot"), sys.argv[4:]))
json.dump({"ts": time.time(), "ok": ok, "detail": detail, **extra},
          open(path, "w", encoding="utf-8"), ensure_ascii=False)
PYEOF
}

fail() {
  log "DRILL FAIL: $1"
  result 0 "$1" "" "" "" "" "$(basename "${snap:-нет}")"
  cd "$DEPLOY/server" && OPENSSL_CONF="$DEPLOY/gost-prov.cnf" "$PY" -m app.alarm \
    --title "Учения восстановления не прошли" --line "$1" \
    --line "Копии базы могут не подняться в аварию — разберись, пока всё работает." >/dev/null 2>&1
  echo "учения НЕ прошли: $1"
  exit 1
}

[ -n "$snap" ] || fail "нет ни одной ночной копии в $BACK"
cp "$snap" "$D/gradebook_server.db"
cd "$DEPLOY/server" || fail "нет каталога $DEPLOY/server"
export OPENSSL_CONF="$DEPLOY/gost-prov.cnf" GRADEBOOK_DB_URL="sqlite:///$D/gradebook_server.db"

start=$(date +%s)
"$DEPLOY/venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" >"$D/uvicorn.log" 2>&1 &
pid=$!
up=0
for _ in $(seq 1 60); do
  [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health")" = 200 ] \
    && { up=1; break; }
  kill -0 "$pid" 2>/dev/null || break
  sleep 2
done
boot=$(( $(date +%s) - start ))
[ "$up" = 1 ] || fail "журнал с копией не поднялся за ${boot} с: $(tail -3 "$D/uvicorn.log" | tr '\n' ' ' | cut -c1-200)"

page=$(curl -s -m 10 "http://127.0.0.1:$PORT/" | grep -c 'index-' || true)
[ "${page:-0}" -ge 1 ] || fail "журнал с копией поднялся, но главная страница пустая"

#Данные читаем той же дверью, что журнал: модели и журнал безопасности.
checks=$("$PY" - <<'PYEOF' 2>/dev/null | tail -1
import json
from app.audit import verify_chain
from app.db import SessionLocal
from app.models import Grade, User
db = SessionLocal()
try:
    print(json.dumps({"users": db.query(User).count(), "grades": db.query(Grade).count(),
                      "chain": verify_chain(db, limit=5000).get("status", "?")}))
finally:
    db.close()
PYEOF
)
users=$(echo "$checks" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["users"])' 2>/dev/null)
grades=$(echo "$checks" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["grades"])' 2>/dev/null)
chain=$(echo "$checks" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["chain"])' 2>/dev/null)
[ "${users:-0}" -ge 1 ] 2>/dev/null || fail "в поднятой копии не читаются пользователи (${checks:-пусто})"
case "$chain" in
  ok|legacy|empty) ;;
  *) fail "в копии не сходится журнал безопасности: $chain" ;;
esac

result 1 "копия поднялась и читается" "$boot" "$users" "$grades" "$chain" "$(basename "$snap")"
log "DRILL OK: $(basename "$snap") поднялась за ${boot} с, пользователей $users, оценок $grades, журнал $chain"
echo "учения прошли: копия $(basename "$snap"), старт ${boot} с, пользователей $users, оценок $grades, журнал $chain"
