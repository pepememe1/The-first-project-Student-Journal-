#!/bin/bash
# Еженедельное обновление ВСЕХ пакетов ОС (27.10.2026), ночь на воскресенье.
#
# Исправления безопасности ставятся каждый час (unattended-upgrades и сторож уязвимостей),
# а обычные исправления ошибок из noble-updates копились бы бесконечно: к 27.10 их ждало 11.
# Раз в неделю ночью ставим всё, с `--with-new-pkgs` (новое ядро тянет новые пакеты), но без
# удаления пакетов — это делает только человек. Нужна перезагрузка — перезагружаемся сразу:
# ночь на воскресенье, людей нет. Итог — /var/lib/gb-os-update/last.json и вечерняя сводка.
set -uo pipefail

STATE=/var/lib/gb-os-update
LOG=/var/log/gb-os-update.log
mkdir -p "$STATE"
log() { echo "$(date -Is) $*" >> "$LOG"; }

exec 9>/run/gb-os-update.lock
flock -n 9 || { log "SKIP: предыдущее обновление ещё идёт"; exit 0; }

#needrestart сам перезапускает службы после обновления библиотек: сторож тревог не должен
#принимать это за падение и перезапускать журнал вдогонку.
echo $(( $(date +%s) + 1800 )) > /run/gb-alarm.pause
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

pkgs() { dpkg-query -W -f '${Package} ${Version}\n' | sort; }
before=$(pkgs)
ok=1
err=""
if ! apt-get update -q >>"$LOG" 2>&1; then ok=0; err="apt-get update не прошёл"; fi
if [ "$ok" = 1 ] && ! apt-get -y -q --with-new-pkgs \
     -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade >>"$LOG" 2>&1; then
  ok=0; err="apt-get upgrade не прошёл (подробно в $LOG)"
fi
after=$(pkgs)
changed=$(comm -13 <(echo "$before") <(echo "$after"))
count=$(printf '%s' "$changed" | grep -c . || true)
names=$(printf '%s\n' "$changed" | awk 'NF{print $1}' | head -12 | tr '\n' ' ')

#Журнал обязан отвечать после обновления: иначе это не «обновились», а «уронили».
alive=0
for _ in $(seq 1 30); do
  [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)" = 200 ] && { alive=1; break; }
  sleep 2
done
if [ "$alive" = 0 ]; then
  systemctl restart gradebook
  sleep 8
  [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)" = 200 ] \
    || { ok=0; err="${err:+$err; }журнал не отвечает после обновления"; }
fi
reboot=0
[ -f /var/run/reboot-required ] && reboot=1

python3 - "$STATE/last.json" "$ok" "$count" "$names" "$reboot" "$err" <<'PYEOF'
import json, sys, time
path, ok, count, names, reboot, err = sys.argv[1:7]
json.dump({"ts": time.time(), "ok": ok == "1", "count": int(count or 0),
           "packages": names.split(), "reboot": reboot == "1", "error": err},
          open(path, "w", encoding="utf-8"), ensure_ascii=False)
PYEOF
log "OS-UPDATE ok=$ok обновлено=$count перезагрузка=$reboot ${names}${err:+ ОШИБКА: $err}"
rm -f /run/gb-alarm.pause
echo "обновлено пакетов: $count ${names}"
[ -n "$err" ] && echo "ошибка: $err"
if [ "$reboot" = 1 ] && [ "$ok" = 1 ]; then
  log "перезагрузка после обновления"
  systemctl reboot
fi
