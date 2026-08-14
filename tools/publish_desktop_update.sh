#!/usr/bin/env bash
# publish_desktop_update.sh — выложить новую сборку десктопа так, чтобы установленные
# программы обновились САМИ (дельтой, если она выгодна).
#
# Запускать ПОСЛЕ сборки .exe (см. §8.1 в доке) — это и есть «десктопная часть деплоя»:
#
#     bash tools/publish_desktop_update.sh dist/GradeBookAI.exe
#
# Что делает:
#   1. качает с сервера ПРЕДЫДУЩИЙ выложенный .exe (он же база для дельты);
#   2. считает патч предыдущая→новая и манифест (tools/make_desktop_patch.py);
#      патч публикуется, только если реально выгоден — см. --min-gain там же;
#   3. заливает патч, полный .exe и манифест в downloads/updates на VPS;
#   4. обновляет downloads/GradeBookAI.exe — кнопку «Скачать» на сайте;
#   5. проверяет, что сервер отдаёт новый манифест.
#
# ⚠️ Версия берётся из desktop_update.py::APP_VERSION. Забыли поднять её перед сборкой —
# скрипт остановится: выложить сборку под уже существующим номером хуже, чем не
# выложить, — часть парка осталась бы на старом коде, считая себя обновлённой.
set -euo pipefail

NEW_EXE="${1:-dist/GradeBookAI.exe}"
SSH_KEY="${GB_SSH_KEY:-$HOME/.ssh/gb_vps_ed25519}"
HOST="${GB_HOST:-root@194.226.120.74}"
SITE="${GB_SITE:-https://esstu-gradebook.ru}"
REMOTE_DL="/root/gb-deploy/downloads"
# ⚠️ pwd -W — иначе на Windows/Git Bash ROOT получается в стиле /c/Users/... (MSYS), а
# ниже он идёт АРГУМЕНТОМ нативному Windows-python (не Cygwin/MSYS-сборке) — тот такой
# путь открыть не может (см. build_nuitka.sh, тот же приём уже применён там).
ROOT="$(cd "$(dirname "$0")/.." && pwd -W 2>/dev/null || pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ -f "$NEW_EXE" ] || { echo "нет файла сборки: $NEW_EXE"; exit 2; }

# ⚠️ Читаем ИМЕННО desktop_update.py, а не data/core.py: с 3.7 литерал живёт здесь, а
# core.py его только ре-экспортирует (`from desktop_update import APP_VERSION`), и
# регулярка по core.py не находила ничего — выкладка падала «не удалось прочитать
# APP_VERSION» на ровном месте. Тот же файл читает и сервер (routers/web/siteinfo.py).
VERSION="$(python -c "
import re,io
s=io.open('$ROOT/desktop_update.py',encoding='utf-8').read()
m=re.search(r'APP_VERSION\s*=\s*\"([^\"]+)\"',s)
print(re.search(r'(\d+(?:\.\d+)*)',m.group(1)).group(1) if m else '')")"
[ -n "$VERSION" ] || { echo "не удалось прочитать APP_VERSION из desktop_update.py"; exit 2; }
echo "== выкладываем версию $VERSION =="

# 1. Предыдущий манифест и .exe — база для дельты. Нет их (первая выкладка) — не беда,
#    будет только полная закачка.
OLD_EXE=""
OLD_VERSION="$(curl -fsS "$SITE/desktop/updates" 2>/dev/null \
  | python -c "import sys,json;d=json.load(sys.stdin);print(d.get('version',''))" 2>/dev/null || true)"
if [ -n "$OLD_VERSION" ] && [ "$OLD_VERSION" != "$VERSION" ]; then
  echo "-- предыдущая версия на сервере: $OLD_VERSION, качаю её для дельты"
  if curl -fsS -o "$WORK/old.exe" "$SITE/downloads/updates/GradeBookAI-$OLD_VERSION.exe"; then
    OLD_EXE="$WORK/old.exe"
  else
    echo "-- предыдущий .exe недоступен, дельты не будет (только полная закачка)"
  fi
elif [ "$OLD_VERSION" = "$VERSION" ]; then
  echo "ОСТАНОВЛЕНО: на сервере уже выложена версия $VERSION — поднимите APP_VERSION"
  exit 3
fi

# 2. Патч + манифест.
python "$ROOT/tools/make_desktop_patch.py" \
  --new "$NEW_EXE" --version "$VERSION" \
  ${OLD_EXE:+--old "$OLD_EXE" --old-version "$OLD_VERSION"} \
  --out "$WORK/updates"

# 3. Заливка. Манифест кладём ПОСЛЕДНИМ: пока его нет, программы не увидят версию,
#    файлов которой ещё нет на диске сервера.
ssh -i "$SSH_KEY" -o BatchMode=yes "$HOST" "mkdir -p $REMOTE_DL/updates"
for f in "$WORK/updates"/*.exe "$WORK/updates"/*.patch; do
  [ -e "$f" ] || continue
  echo "-- заливаю $(basename "$f") ($(du -h "$f" | cut -f1))"
  scp -i "$SSH_KEY" -o BatchMode=yes "$f" "$HOST:$REMOTE_DL/updates/"
done
scp -i "$SSH_KEY" -o BatchMode=yes "$WORK/updates/manifest.json" "$HOST:$REMOTE_DL/updates/"

# 4. Кнопка «Скачать» на сайте — тот же файл, что и полная закачка обновления.
ssh -i "$SSH_KEY" -o BatchMode=yes "$HOST" \
  "cp -f $REMOTE_DL/updates/GradeBookAI-$VERSION.exe $REMOTE_DL/GradeBookAI.exe"

# 5. Проверка снаружи: сервер обязан отдавать НОВУЮ версию.
GOT="$(curl -fsS "$SITE/desktop/updates" \
  | python -c "import sys,json;print(json.load(sys.stdin).get('version',''))")"
[ "$GOT" = "$VERSION" ] || { echo "ПРОВЕРКА НЕ ПРОШЛА: сервер отдаёт «$GOT»"; exit 4; }

# Старые сборки копим не бесконечно: дельта строится только с ПОСЛЕДНЕЙ версии,
# остальные лежат мёртвым грузом на диске, которого на VPS и так немного.
ssh -i "$SSH_KEY" -o BatchMode=yes "$HOST" \
  "cd $REMOTE_DL/updates && ls -t GradeBookAI-*.exe 2>/dev/null | tail -n +3 | xargs -r rm -f;
   ls -t *.patch 2>/dev/null | tail -n +4 | xargs -r rm -f; df -h / | tail -1"

echo "== ГОТОВО: версия $VERSION выложена, программы подхватят её при следующем запуске =="
