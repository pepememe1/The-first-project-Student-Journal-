#!/usr/bin/env bash
# gb_cleanup.sh — еженедельная уборка КЭШЕЙ боевой машины (14.10.2026, просьба Ярослава
# «автоочистка, чтобы кэш чистился, без важных данных и бэкапов»).
#
# Зачем: диск на VPS 9.8 ГБ, и место здесь не про удобство. gb_backup.sh ПРОПУСКАЕТ снимок
# базы, когда свободно меньше ~1.5 размера базы, то есть переполнение отбирает резервные
# копии. До этой уборки кэши копились сами: 274 МБ кэша pip, 199 МБ скачанных .deb,
# 57 OTA-бандлов на 137 МБ, хотя телефону нужен один.
#
# ━━ ЧТО УБИРАЕТ (только это, по одному пути на шаг) ━━
#   1. /var/cache/apt/archives — скачанные пакеты; уже установлены, качаются заново;
#   2. кэш pip пользователя root — нужен только при переустановке, тоже качается заново;
#   3. OTA-бандлы в server/ota_bundles, кроме ТЕКУЩЕГО (на него указывает latest.json) и
#      трёх предыдущих — как запись того, что стояло на телефонах.
#      ⚠️ ОТКАТИТЬСЯ ИМИ НЕЛЬЗЯ (нашёл Полковник 14.10.2026): latest.json подписан, а
#      телефон не ставит бандл, который не новее своего (web/src/utils/otaVerify.js,
#      compareOtaVersions). Откат телефонов — только выпуском НОВОГО номера из нужного
#      коммита (web/deploy/release-ota.ps1).
#
# ━━ ЧЕГО НЕ ТРОГАЕТ НИКОГДА ━━
# /root/gb-backups (копии базы), саму базу, .env, webdist.old и server/app.old (откат
# деплоя), downloads (раздача .exe и APK), venv, журналы. Путей к ним в этом файле нет
# вовсе: граница проведена отсутствием кода, а не проверкой, которую можно ослабить.
# Журнал systemd сюда не входит намеренно: его размер уже держит SystemMaxUse в
# journald.conf, а журнал нужен при разборе инцидента (docs/security/INCIDENT-RESPONSE.md).
#
# ━━ OTA: ПОЧЕМУ НЕ «ВСЁ, КРОМЕ ПОСЛЕДНИХ N ФАЙЛОВ» ━━
# Порядок задаёт ВЕРСИЯ, а не время файла, и «текущий» берётся из latest.json: иначе
# недоехавший бандл, залитый позже текущего (такой лежал на бою с 07.10), считался бы
# текущим, а настоящий текущий — лишним. Файлы моложе суток не трогаются вовсе — возможно, выкладка
# идёт прямо сейчас (release-ota.ps1 заливает архив раньше, чем переключает latest.json).
# Не разобрался в latest.json — бандлы не трогает ни одного: лучше лишние мегабайты, чем
# телефоны без обновления.
#
# ━━ КАК ЗВАТЬ И СТАВИТЬ ━━
#   /root/gb-deploy/tools/gb_cleanup.sh --dry-run   # показать, ничего не удаляя
#   systemctl start gb-cleanup.service              # уборка вне расписания
# Установка (рядом лежат юнит, таймер и настройки автообновлений):
#   scp deploy/maintenance/gb_cleanup.sh gb:/root/gb-deploy/tools/
#   scp deploy/maintenance/gb-cleanup.{service,timer} gb:/etc/systemd/system/
#   ssh gb 'chmod 700 /root/gb-deploy/tools/gb_cleanup.sh &&
#           systemctl daemon-reload && systemctl enable --now gb-cleanup.timer'
set -euo pipefail

MODE="${1:-}"
DEPLOY=/root/gb-deploy
OTA="$DEPLOY/server/ota_bundles"
KEEP_OTA=3
LOG=/var/log/gb-cleanup.log
PIP="$DEPLOY/venv/bin/pip"

if [ -n "$MODE" ] && [ "$MODE" != "--dry-run" ]; then
  echo "Использование: $0 [--dry-run]" >&2
  exit 2
fi
DRY=0
[ "$MODE" = "--dry-run" ] && DRY=1

log() {
  echo "$*"
  [ "$DRY" = 1 ] || echo "$(date -Is) $*" >> "$LOG"
}

remove() {
  if [ "$DRY" = 1 ]; then
    echo "  удалил бы: $1"
  else
    rm -f -- "$1" && log "  удалено: $1"
  fi
}

# Один экземпляр за раз: ручной запуск не должен наложиться на запуск по таймеру.
exec 9>/run/gb-cleanup.lock
if ! flock -n 9; then log "SKIP: предыдущая уборка ещё идёт"; exit 0; fi

used_before=$(df --output=used -BM / | tail -1 | tr -dc '0-9')
[ "$DRY" = 1 ] && echo "ХОЛОСТОЙ ПРОГОН — ничего не удаляется"

# ── 1. скачанные пакеты apt ─────────────────────────────────────────────────────────
if [ "$DRY" = 1 ]; then
  echo "  apt-get clean освободил бы: $(du -sh /var/cache/apt/archives 2>/dev/null | cut -f1)"
elif apt-get clean 2>/dev/null; then
  log "apt: кэш пакетов очищен"
else
  # Чаще всего — блокировка apt: ночное обновление безопасности ещё идёт. Не ждём и не
  # падаем (кэш подождёт неделю), но говорим об этом, а не молчим.
  log "apt: кэш НЕ очищен — apt занят (идёт обновление?), пропущено до следующей недели"
fi

# ── 2. кэш pip ──────────────────────────────────────────────────────────────────────
if [ -x "$PIP" ]; then
  if [ "$DRY" = 1 ]; then
    echo "  pip cache purge освободил бы: $(du -sh /root/.cache/pip 2>/dev/null | cut -f1)"
  else
    "$PIP" cache purge >/dev/null 2>&1 && log "pip: кэш очищен" || log "pip: кэш уже пуст"
  fi
fi

# ── 3. старые OTA-бандлы ────────────────────────────────────────────────────────────
cur=""
if [ -f "$OTA/latest.json" ]; then
  cur=$(sed -n 's/.*"file"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$OTA/latest.json" | head -1)
fi
if ! printf '%s' "$cur" | grep -Eq '^1\.[0-9]{6}\.[0-9]{4}\.zip$' || [ ! -f "$OTA/$cur" ]; then
  log "OTA: не понял latest.json (file='$cur') — бандлы не трогаю"
else
  curv="${cur%.zip}"
  # Версии берутся и из архивов, и из манифестов: прежние уборки удаляли архив, а манифест
  # оставался сиротой (на бою 14.10.2026 таких лежало двенадцать).
  all=$(ls -1 "$OTA" | grep -E '^1\.[0-9]{6}\.[0-9]{4}\.(zip|manifest\.json)$' \
        | sed -E 's/\.(zip|manifest\.json)$//' | sort -u || true)
  # Оставляемые прежние: KEEP_OTA последних версий СТАРШЕ текущей, у которых есть сам
  # архив (манифест-сирота место в списке занял бы впустую). Версии фиксированной ширины
  # (1.ГГММДД.ЧЧММ), поэтому строковое сравнение совпадает с порядком выпуска.
  zips=$(ls -1 "$OTA" | grep -E '^1\.[0-9]{6}\.[0-9]{4}\.zip$' | sed 's/\.zip$//' | sort || true)
  keep=$(printf '%s\n' "$zips" | awk -v c="$curv" 'length($0) && $0 < c' | tail -n "$KEEP_OTA")
  echo "OTA: текущий $curv, из прежних оставлены: $(echo $keep)"
  for v in $all; do
    [ "$v" = "$curv" ] && continue
    printf '%s\n' "$keep" | grep -qxF "$v" && continue
    if [ -n "$(find "$OTA" -maxdepth 1 -name "$v.*" -mmin -1440)" ]; then
      echo "  моложе суток, оставлен: $v"
      continue
    fi
    [ -f "$OTA/$v.zip" ] && remove "$OTA/$v.zip"
    [ -f "$OTA/$v.manifest.json" ] && remove "$OTA/$v.manifest.json"
  done
fi

used_after=$(df --output=used -BM / | tail -1 | tr -dc '0-9')
pct=$(df --output=pcent / | tail -1 | tr -d ' ')
if [ "$DRY" = 1 ]; then
  echo "Холостой прогон окончен. Диск занят $pct."
else
  log "OK: освобождено $((used_before - used_after)) МБ, диск занят $pct"
fi
