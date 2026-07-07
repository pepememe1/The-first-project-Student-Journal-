#!/usr/bin/env bash
# install.sh — установщик GradeBookAI на боевой Linux-ПК (ВСГУТУ) «в одну команду».
#
# Что делает: ставит зависимости, разворачивает сервер + собранный сайт, создаёт
# systemd-сервис, поднимает HTTPS (Caddy), генерит .env (секреты), АВТО-ОБНАРУЖИВАЕТ
# ViPNet/OpenSSL GOST-engine и включает сертифицированный ГОСТ-режим, запускает сервер.
#
# Использование (от root):
#   sudo bash install.sh --domain esstu-gradebook.ru
# Файлы приложения (server/, web/dist/ ) должны лежать РЯДОМ со скриптом (на флешке).
# Для «одной кнопки» скрипт заворачивается в самораспаковывающийся .run (makeself) —
# см. deploy/make-installer.sh.
set -euo pipefail

DOMAIN=""
APP_DIR="/opt/gradebook"
PORT="8000"
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2;;
    --dir) APP_DIR="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    *) echo "неизвестный аргумент: $1"; exit 1;;
  esac
done
[ "$(id -u)" = "0" ] || { echo "Запускать от root: sudo bash install.sh --domain <домен>"; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"   # корень бандла (где server/ и web/)
[ -d "$SRC/server" ] || { echo "Не найден server/ рядом со скриптом ($SRC)"; exit 1; }

echo "== [1/8] Пакеты ОС =="
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip openssl curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https >/dev/null
elif command -v dnf >/dev/null; then
  dnf install -y -q python3 python3-pip openssl curl >/dev/null
else
  echo "Неизвестный пакетный менеджер — поставьте python3/venv/openssl/caddy вручную";
fi

echo "== [2/8] Caddy (авто-HTTPS) =="
if ! command -v caddy >/dev/null; then
  if command -v apt-get >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null || true
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list 2>/dev/null || true
    apt-get update -qq && apt-get install -y -qq caddy >/dev/null || echo "Caddy не встал автоматически — поставьте вручную"
  fi
fi

echo "== [3/8] Копирование приложения в $APP_DIR =="
mkdir -p "$APP_DIR"
cp -r "$SRC/server" "$APP_DIR/"
[ -d "$SRC/web/dist" ] && { rm -rf "$APP_DIR/webdist"; cp -r "$SRC/web/dist" "$APP_DIR/webdist"; }
mkdir -p "$APP_DIR/downloads"

echo "== [4/8] Python-окружение и зависимости =="
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/server/requirements.txt"

echo "== [5/8] Обнаружение ViPNet / OpenSSL GOST-engine =="
GOST_OK=$("$APP_DIR/venv/bin/python" -c "import hashlib; print('1' if any(n in hashlib.algorithms_available for n in ('streebog512','md_gost12_512','gost2012_512')) else '0')" 2>/dev/null || echo 0)
if [ "$GOST_OK" = "1" ]; then
  echo "   ГОСТ-движок найден → сертифицированный режим ВКЛючён (GRADEBOOK_VIPNET=1)"; VIPNET=1
else
  echo "   ГОСТ-движок НЕ найден → пока dev-крипта. Поставьте ViPNet CSP + GOST-engine и перезапустите."; VIPNET=0
fi

echo "== [6/8] Конфиг .env (секреты генерируются) =="
ENV="$APP_DIR/server/.env"
if [ ! -f "$ENV" ]; then
  JWT=$(openssl rand -hex 32)
  HOSTID=$("$APP_DIR/venv/bin/python" -c "import uuid;print(uuid.uuid4())")
  DATAKEY=$(openssl rand -hex 32)
  IDXKEY=$(openssl rand -hex 32)
  cat > "$ENV" <<ENVEOF
GRADEBOOK_JWT_SECRET=$JWT
GRADEBOOK_HOST_DEVICE_ID=$HOSTID
GRADEBOOK_ALLOWED_ORIGINS=https://${DOMAIN:-localhost}
GRADEBOOK_VIPNET=$VIPNET
GRADEBOOK_DATA_KEY=$DATAKEY
GRADEBOOK_INDEX_KEY=$IDXKEY
GRADEBOOK_WEB_DIST=$APP_DIR/webdist
GRADEBOOK_DOWNLOADS=$APP_DIR/downloads
ENVEOF
  chmod 600 "$ENV"
  echo "   .env создан (права 600). ⚠ Боевые ключи ПДн после установки перенести в СКЗИ/токен."
else
  echo "   .env уже есть — не трогаю."
fi

echo "== [7/8] systemd-сервис gradebook =="
cat > /etc/systemd/system/gradebook.service <<UNIT
[Unit]
Description=GradeBookAI API server
After=network.target
[Service]
WorkingDirectory=$APP_DIR/server
ExecStart=$APP_DIR/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT
Restart=always
User=root
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now gradebook

echo "== [8/8] Caddy (HTTPS $DOMAIN) с security-заголовками =="
if [ -n "$DOMAIN" ] && command -v caddy >/dev/null; then
  cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "DENY"
		Referrer-Policy "no-referrer"
		Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self'; connect-src 'self'; font-src 'self' data: https://fonts.gstatic.com; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; form-action 'self'"
		-Server
	}
	reverse_proxy 127.0.0.1:$PORT
}
CADDY
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
fi

echo
echo "======================================================================"
echo " ГОТОВО. Сервер: $(systemctl is-active gradebook) | ГОСТ-режим: $([ "$VIPNET" = 1 ] && echo сертифицированный || echo dev)"
[ -n "$DOMAIN" ] && echo " Сайт: https://$DOMAIN"
echo " Дальше (152-ФЗ): поставить ViPNet CSP (если ещё нет) → перезапустить;"
echo " ключи ПДн перенести в СКЗИ/на токен; вести журнал учёта ключей; аттестация ИСПДн."
echo "======================================================================"
