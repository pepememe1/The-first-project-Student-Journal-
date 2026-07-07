#!/usr/bin/env bash
# make-installer.sh — собирает ОДИН самораспаковывающийся файл gradebook-installer.run
# (флешка → sudo ./gradebook-installer.run --domain <домен> → всё разворачивается само).
#
# Требует: makeself (apt install makeself) и собранный сайт (web/dist).
# Запуск из корня репозитория:  bash deploy/make-installer.sh --domain esstu-gradebook.ru
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

command -v makeself >/dev/null || { echo "Нет makeself. Установите: sudo apt install makeself"; exit 1; }
[ -d web/dist ] || { echo "Сначала соберите сайт: (cd web && npm ci && npm run build)"; exit 1; }

STAGE="$(mktemp -d)"
echo "Готовлю бандл в $STAGE …"
mkdir -p "$STAGE/server" "$STAGE/web/dist" "$STAGE/deploy"
# Только нужное для сервера (без тестов/кэша), сайт — собранный dist, и установщик.
cp -r server/app server/requirements.txt server/run.py "$STAGE/server/" 2>/dev/null || cp -r server/* "$STAGE/server/"
rm -rf "$STAGE"/server/**/__pycache__ "$STAGE"/server/app/tests 2>/dev/null || true
cp -r web/dist/* "$STAGE/web/dist/"
cp deploy/install.sh "$STAGE/deploy/install.sh"
cp DEPLOY-VSGUTU-SECURE.md "$STAGE/" 2>/dev/null || true

OUT="$ROOT/gradebook-installer.run"
# --notemp: распаковка во временную папку; при запуске вызывается deploy/install.sh с
# переданными аргументами (напр. --domain). makeself сам делает файл исполняемым.
makeself --gzip "$STAGE" "$OUT" "GradeBookAI installer" ./deploy/install.sh
chmod +x "$OUT"
rm -rf "$STAGE"
echo
echo "ГОТОВО: $OUT"
echo "На сервере ВСГУТУ:  sudo ./gradebook-installer.run --domain <домен колледжа>"
