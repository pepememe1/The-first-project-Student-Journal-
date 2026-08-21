#!/usr/bin/env bash
# gb_backup.sh — суточный ЗАШИФРОВАННЫЙ снимок боевой БД с проверкой и ротацией.
#
# Почему так, а не «cp базы по крону»:
#   • cp живого файла SQLite НЕконсистентен: рядом пишется WAL, и копия может застать
#     базу в середине транзакции. Консистентный снимок даёт VACUUM INTO — он держит
#     read-транзакцию и переносит согласованное состояние.
#   • Снимок остаётся ЗАШИФРОВАННЫМ: VACUUM INTO на SQLCipher-соединении пишет копию тем
#     же ключом. Файл бэкапа сам по себе — шум без ключа (ключ живёт в .env на этой же
#     машине; для восстановления он и нужен).
#   • Бэкап без ПРОВЕРКИ — это Шрёдингеров бэкап (урок §16 CLAUDE.md): успехом считаем
#     не код возврата, а то, что снимок ОТКРЫЛСЯ тем же ключом, прошёл integrity_check и
#     в нём есть пользователи. Не прошёл — снимок удаляется, а не выдаётся за годный.
#   • Ротация держит диск в узде (на VPS он и так под три четверти): оставляем последние
#     $KEEP суточных, старьё удаляем. Трогаем ТОЛЬКО каталог auto/ — ручные снимки
#     (/root/gb-backups/pre-*) не автоочищаются.
#
# Ключ НИКОГДА не уходит в argv (виден в ps) и в лог — только в окружение дочернего
# python и переменную оболочки.
set -euo pipefail

DEPLOY=/root/gb-deploy
DB="$DEPLOY/server/gradebook_server.db"
ENV="$DEPLOY/server/.env"
OUT=/root/gb-backups/auto
KEEP=14
LOG=/var/log/gb-backup.log
PY="$DEPLOY/venv/bin/python"

log() { echo "$(date -Is) $*" >> "$LOG"; }

# Один экземпляр за раз — крон/таймер не должны наложиться на длинную предыдущую копию.
exec 9>/run/gb-backup.lock
if ! flock -n 9; then log "SKIP: предыдущий бэкап ещё идёт"; exit 0; fi

[ -f "$DB" ]  || { log "FAIL: нет файла БД $DB"; exit 1; }
[ -x "$PY" ]  || { log "FAIL: нет python venv $PY"; exit 1; }

# Ключ из .env — вырезаем возможные кавычки и CR (файл когда-то мог прилететь с Windows).
KEY=$(grep -E '^GRADEBOOK_DB_KEY=' "$ENV" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')
[ -n "$KEY" ] || { log "FAIL: GRADEBOOK_DB_KEY пуст в .env"; exit 1; }
export GB_KEY="$KEY"

mkdir -p "$OUT"; chmod 700 "$OUT"

# Диск-гард: НЕ создаём копию, если места в обрез. Иначе бэкап добил бы почти полный диск
# (на этой машине он и так под три четверти), и упал бы весь сайт, а не один бэкап. Лучше
# честно пропустить снимок и оставить след в логе, чем уронить прод ради копии.
db_kb=$(( $(stat -c%s "$DB") / 1024 ))
need_kb=$(( db_kb * 3 / 2 ))                       # ~1.5× размера БД про запас на VACUUM
avail_kb=$(df -Pk /root/gb-backups | tail -1 | awk '{print $4}')
use_pct=$(df -Pk /root/gb-backups | tail -1 | awk '{print $5}' | tr -d '%')
if [ "${avail_kb:-0}" -lt "$need_kb" ]; then
    log "FAIL: мало места (свободно ${avail_kb}KB, нужно ~${need_kb}KB, диск занят ${use_pct}%) — снимок пропущен"
    exit 3
fi

ts=$(date +%Y%m%d_%H%M%S)
dst="$OUT/gradebook_${ts}.db"

# 1) Консистентный зашифрованный снимок.
"$PY" - "$DB" "$dst" <<'PYEOF'
import os, sys, sqlcipher3
db, dst = sys.argv[1], sys.argv[2]
key = os.environ["GB_KEY"]
c = sqlcipher3.connect(db)
c.execute("PRAGMA key = \"x'%s'\"" % key)   # тот же способ, что в server/app/db.py
c.execute("VACUUM INTO ?", (dst,))           # копия наследует шифрование соединения
c.close()
PYEOF

# 2) Верификация: открыть тем же ключом, целостность, есть пользователи.
n=$("$PY" - "$dst" <<'PYEOF'
import os, sys, sqlcipher3
dst = sys.argv[1]; key = os.environ["GB_KEY"]
c = sqlcipher3.connect(dst)
c.execute("PRAGMA key = \"x'%s'\"" % key)
ok = c.execute("PRAGMA integrity_check").fetchone()[0]
assert ok == "ok", "integrity_check=%r" % ok
print(c.execute("SELECT count(*) FROM users").fetchone()[0])
c.close()
PYEOF
) || { log "FAIL: снимок не прошёл верификацию, удаляю $dst"; rm -f "$dst"; exit 2; }

if ! [ "$n" -ge 1 ] 2>/dev/null; then
    log "FAIL: в снимке 0 пользователей — что-то не так, удаляю $dst"
    rm -f "$dst"; exit 2
fi
chmod 600 "$dst"

# 3) Ротация: держим последние $KEEP, остальное удаляем (только auto/).
removed=$(ls -1t "$OUT"/gradebook_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | tee /dev/stderr | xargs -r rm -f 2>/dev/null; true)
kept=$(ls -1 "$OUT"/gradebook_*.db 2>/dev/null | wc -l)

sz=$(du -h "$dst" | cut -f1)
auto_kb=$(du -sk "$OUT" | cut -f1)                 # сколько всего занимает каталог auto/
log "OK: $dst ($sz, users=$n), храним $kept/$KEEP снимков (~${auto_kb}KB), диск занят ${use_pct}%"
