#!/usr/bin/env bash
# install.sh — развернуть GradeBookAI на новом Linux-сервере «в одну команду».
#
# ━━ СЦЕНАРИЙ, РАДИ КОТОРОГО ЭТО НАПИСАНО (Ярослав, 04.09.2026) ━━
# Дословно: «сделай допустим так чтобы ты мне закинул на флешку файлы с сервером и всем
# вот этим вот, вставил его на линукс ПК, подключился через SSH к новому серваку, увидел
# новое железо, само всё подхватилось, выставились параметры сервера, и сам наш адрес
# https://esstu-gradebook.ru/ сразу начал жить не на старом впс а тут без большого
# количества команд».
#
#   sudo bash deploy/install.sh --domain esstu-gradebook.ru
#
# Файлы приложения (server/, web/dist/, tools/) должны лежать РЯДОМ — то есть флешка
# несёт весь каталог проекта. Для «одной кнопки» скрипт заворачивается в
# самораспаковывающийся .run — см. deploy/make-installer.sh.
#
# ━━ ЧЕГО ЭТОТ СКРИПТ НЕ МОЖЕТ, И ОБ ЭТОМ НАДО ЗНАТЬ ЗАРАНЕЕ ━━
# Домен переключается НЕ здесь. Чтобы https://esstu-gradebook.ru открывался с новой
# машины, нужны две вещи, которых нет ни у одного скрипта:
#   1) A-запись домена должна указывать на IP новой машины (панель регистратора);
#   2) машина должна быть доступна из интернета по портам 80 и 443.
# Второе — записанный блокер проекта, и он не наш: порты и публичный адрес выдаёт сеть
# вуза. Пока этого нет, сервер поднимется и будет работать по IP, а сертификат Caddy не
# получит (Let's Encrypt проверяет владение доменом через тот самый 80-й порт).
# Скрипт честно скажет об этом в конце, а не сделает вид, что всё готово.
set -euo pipefail

DOMAIN=""
# 🔴 КАТАЛОГ ПО УМОЛЧАНИЮ СМЕНЁН С /root/gb-deploy НА /opt/gradebook (10.09.2026),
# и это не вкусовщина, а ТРЕБОВАНИЕ ужесточения юнита. `ProtectHome=yes` делает /root,
# /home и /run/user НЕДОСТУПНЫМИ процессу службы — с кодом в /root/gb-deploy служба не
# прочитала бы собственный `serve.py` и не поднялась бы вовсе. То есть «применить
# hardening вслепую» здесь означало бы мёртвый сервер на первом же старте.
# /opt — штатное место для стороннего приложения по FHS, и оно вне защищаемых домашних.
# ⚠️ Живого VPS это не касается: там служба уже стоит, а этот скрипт разворачивает
# НОВУЮ машину. Перенос существующей — отдельная осознанная операция.
APP_DIR="/opt/gradebook"
PORT="8000"
STATIC_DIR="/var/www/gradebook"
RESTORE_DB=""
WITH_AI="auto"

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2;;
    --dir) APP_DIR="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --restore-db) RESTORE_DB="$2"; shift 2;;
    --with-ai) WITH_AI="yes"; shift;;
    --no-ai) WITH_AI="no"; shift;;
    *) echo "неизвестный аргумент: $1"; exit 1;;
  esac
done
[ "$(id -u)" = "0" ] || { echo "Запускать от root: sudo bash deploy/install.sh --domain <домен>"; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"   # корень бандла (где server/, web/, tools/)
[ -d "$SRC/server" ] || { echo "Не найден server/ рядом со скриптом ($SRC)"; exit 1; }

TOTAL=10

echo "== [1/$TOTAL] Пакеты ОС =="
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip openssl curl ca-certificates \
      debian-keyring debian-archive-keyring apt-transport-https >/dev/null
elif command -v dnf >/dev/null; then
  dnf install -y -q python3 python3-pip openssl curl >/dev/null
else
  echo "Неизвестный пакетный менеджер — поставьте python3/venv/openssl/caddy вручную"
fi

echo "== [2/$TOTAL] Caddy (авто-HTTPS) =="
if ! command -v caddy >/dev/null; then
  if command -v apt-get >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null || true
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
      > /etc/apt/sources.list.d/caddy-stable.list 2>/dev/null || true
    apt-get update -qq && apt-get install -y -qq caddy >/dev/null \
      || echo "Caddy не встал автоматически — поставьте вручную"
  fi
fi

echo "== [3/$TOTAL] Копирование приложения в $APP_DIR =="
mkdir -p "$APP_DIR" "$APP_DIR/downloads"
cp -r "$SRC/server" "$APP_DIR/"
#Корневые общие модули (grading.py, study_hours.py, schedule/ и прочие) НЕ лежат внутри
#server/, но сервер их импортирует. Забыть их — значит уронить прод: этот дефект уже
#дважды случался при обычном деплое. Копируем всё, что есть в корне бандла.
for item in "$SRC"/*.py "$SRC/schedule" "$SRC/tools"; do
  [ -e "$item" ] && cp -r "$item" "$APP_DIR/" 2>/dev/null || true
done
if [ -d "$SRC/web/dist" ]; then
  rm -rf "$APP_DIR/webdist"; cp -r "$SRC/web/dist" "$APP_DIR/webdist"
  # ⚠️ ВТОРАЯ КОПИЯ СТАТИКИ — НЕ ИЗБЫТОЧНОСТЬ. Caddy работает под пользователем `caddy`,
  # а /root имеет права drwx------: раздача прямо из $APP_DIR даёт 403 НА КАЖДЫЙ АССЕТ.
  # Это записанная грабля проекта, оплаченная упавшим сайтом.
  mkdir -p "$STATIC_DIR"; rm -rf "${STATIC_DIR:?}/"*; cp -r "$SRC/web/dist/." "$STATIC_DIR/"
  chown -R caddy:caddy "$STATIC_DIR" 2>/dev/null || true
fi
mkdir -p /var/log/caddy && chown -R caddy:caddy /var/log/caddy 2>/dev/null || true

echo "== [4/$TOTAL] Python-окружение и зависимости =="
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
# ⚠️ ИЗ ФАЙЛА, А НЕ СПИСКОМ. Прежняя версия шага «прописать службу» в переносе
# (desktop/server_admin.py) ставила пять пакетов, перечисленных руками, — без ГОСТ-хеша,
# без SQLCipher, без выгрузок. Рукописный список зависимостей верен ровно в день, когда
# его написали; тот же класс дефекта уже ронял сборку .exe и деплой.
#
# ⚠️ ЗАМОК ВЕРСИЙ ИМЕЕТ ПРИОРИТЕТ (п. 2.5 PLAN-HARDENING). В requirements.txt везде
# `>=` — для разработки правильно, для поставки дыра: покупатель ставит по тому же
# файлу через полгода и получает комбинацию, которую никто не проверял. Если рядом
# лежит requirements.lock.txt (снят tools/freeze_requirements.py на машине с зелёным
# прогоном) — ставим по нему.
if [ -f "$APP_DIR/server/requirements.lock.txt" ]; then
  echo "   ставлю по ЗАМКУ версий (проверенная комбинация)"
  "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/server/requirements.lock.txt"
else
  echo "   замка версий нет — ставлю по requirements.txt (версии не зафиксированы)"
  "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/server/requirements.txt"
fi

echo "== [5/$TOTAL] Железо этой машины =="
HW=$(cd "$APP_DIR/server" && "$APP_DIR/venv/bin/python" -c \
     "from app import hostcaps; print(hostcaps.describe())" 2>/dev/null || echo "не определилось")
echo "   $HW"

echo "== [6/$TOTAL] Тяжёлый набор (распознавание речи, перевод, озвучка) =="
# Ставим ПО КЛАССУ МАШИНЫ, а не по тумблеру: настройку, которую надо вспомнить и
# переключить руками, забывают ровно в день переезда. Решение принимает hostcaps.
if [ "$WITH_AI" = "no" ]; then
  echo "   пропущено (--no-ai)"
elif [ ! -f "$APP_DIR/tools/provision_ai_host.py" ]; then
  echo "   пропущено: tools/ не приехал в бандле"
else
  AI_ARGS="--apply"
  [ "$WITH_AI" = "yes" ] && AI_ARGS="--apply --force"
  # shellcheck disable=SC2086
  (cd "$APP_DIR" && "$APP_DIR/venv/bin/python" tools/provision_ai_host.py $AI_ARGS) \
    || echo "   ⚠️ тяжёлый набор не встал — сервер будет работать без перевода и распознавания"
fi

echo "== [7/$TOTAL] ГОСТ-движок (ViPNet / OpenSSL GOST-engine) =="
GOST_OK=$("$APP_DIR/venv/bin/python" -c "import hashlib; print('1' if any(n in hashlib.algorithms_available for n in ('streebog512','md_gost12_512','gost2012_512')) else '0')" 2>/dev/null || echo 0)
if [ "$GOST_OK" = "1" ]; then
  echo "   ГОСТ-движок найден → сертифицированный режим ВКЛючён"; VIPNET=1
else
  echo "   ГОСТ-движок НЕ найден → пока dev-крипта (хеш паролей считает gostcrypto)."; VIPNET=0
fi

echo "== [8/$TOTAL] Конфиг .env =="
ENV="$APP_DIR/server/.env"
if [ -f "$ENV" ]; then
  echo "   .env приехал вместе с бандлом — НЕ трогаю."
  echo "   (это правильный путь переноса: старые ключи сохраняются, значит старая база"
  echo "    откроется на новой машине)"
else
  # 🔥 ЛОВУШКА, КОТОРАЯ СТОИЛА БЫ ВСЕЙ БАЗЫ. Файл БД шифруется целиком (SQLCipher), и
  # ключ лежит в .env. Привезти базу БЕЗ .env и сгенерировать новый ключ — значит
  # получить файл, который не откроется никогда: SQLCipher ответит «file is not a
  # database», и это будет выглядеть как испорченная копия, а не как неверный ключ.
  # Поэтому здесь ОТКАЗ, а не «сделаем как получится».
  if [ -n "$RESTORE_DB" ] || [ -f "$APP_DIR/server/gradebook_server.db" ]; then
    echo "   ⛔ ОСТАНОВ: есть база, но нет server/.env."
    echo "      База зашифрована ключом из .env. Сгенерировать новый ключ значит навсегда"
    echo "      потерять доступ к данным — файл не откроется, и выглядеть это будет как"
    echo "      порча копии. Привезите .env со старого сервера (/root/gb-deploy/server/.env)"
    echo "      и запустите установку снова."
    exit 3
  fi
  JWT=$(openssl rand -hex 32)
  HOSTID=$("$APP_DIR/venv/bin/python" -c "import uuid;print(uuid.uuid4())")
  DATAKEY=$(openssl rand -hex 32)
  IDXKEY=$(openssl rand -hex 32)
  # ⚠️ КЛЮЧ ШИФРОВАНИЯ БАЗЫ ГЕНЕРИРУЕТСЯ ЗДЕСЬ. Раньше его в этом файле НЕ БЫЛО вовсе:
  # свежеустановленный сервер работал с базой БЕЗ шифрования файла, то есть ПДн студентов
  # лежали на диске открытым текстом. Ровно 64 hex-символа — иначе db.py откажется
  # открывать базу (проверка стоит там намеренно: «тихо открылось без шифрования» —
  # худший исход из всех).
  DBKEY=$(openssl rand -hex 32)
  cat > "$ENV" <<ENVEOF
GRADEBOOK_JWT_SECRET=$JWT
GRADEBOOK_HOST_DEVICE_ID=$HOSTID
GRADEBOOK_ALLOWED_ORIGINS=https://${DOMAIN:-localhost}
GRADEBOOK_DOMAIN=${DOMAIN:-}
GRADEBOOK_VIPNET=$VIPNET
GRADEBOOK_DATA_KEY=$DATAKEY
GRADEBOOK_INDEX_KEY=$IDXKEY
GRADEBOOK_DB_KEY=$DBKEY
GRADEBOOK_WEB_DIST=$APP_DIR/webdist
GRADEBOOK_DOWNLOADS=$APP_DIR/downloads
ENVEOF
  chmod 600 "$ENV"
  echo "   .env создан (права 600), включая ключ шифрования базы."
  echo "   ⚠️ СНИМИТЕ С НЕГО КОПИЮ И ХРАНИТЕ ВНЕ ЭТОЙ МАШИНЫ: без него база не откроется."
fi

if [ -n "$RESTORE_DB" ]; then
  echo "   Восстанавливаю базу из $RESTORE_DB"
  cp "$RESTORE_DB" "$APP_DIR/server/gradebook_server.db"
fi

# ── Redis: общее состояние между процессами ────────────────────────────────────────
# ⚠️ СТАВИТСЯ ПО КЛАССУ МАШИНЫ, а не всегда — тот же принцип, что у тяжёлого набора ИИ
# (hostcaps). На слабой машине несколько процессов бессмысленны (там одно ядро), а
# лишняя служба ест память, которой и так мало.
# 🔴 И ставится ЛОКАЛЬНО, только на петлю. Redis по сети добавил бы сетевой отказ на
# путь КАЖДОГО входа: анти-брутфорс спрашивает его до сверки пароля. Это была бы наша
# собственная новая точка отказа, причём в самом чувствительном месте.
if [ "$(cd "$APP_DIR/server" 2>/dev/null && "$APP_DIR/venv/bin/python" -c \
        'from app import hostcaps; print(hostcaps.describe().get("tier",""))' 2>/dev/null)" \
     = "workstation" ]; then
  echo "== Redis (машина класса workstation — есть смысл в нескольких процессах) =="
  apt-get install -y -qq redis-server >/dev/null 2>&1 || true
  if systemctl list-unit-files 2>/dev/null | grep -q '^redis-server\.service'; then
    # Только петля: наружу эту дверь открывать незачем и опасно.
    sed -i 's/^# *bind .*/bind 127.0.0.1 ::1/' /etc/redis/redis.conf 2>/dev/null || true
    systemctl enable --now redis-server >/dev/null 2>&1 || true
    if redis-cli ping 2>/dev/null | grep -q PONG; then
      # ⚠️ Ключ ДОПИСЫВАЕТСЯ, только если его там нет: перезапись затёрла бы правку,
      # сделанную руками (например другой номер базы).
      grep -q '^GRADEBOOK_REDIS_URL=' "$APP_DIR/server/.env" 2>/dev/null \
        || echo 'GRADEBOOK_REDIS_URL=redis://127.0.0.1:6379/0' >> "$APP_DIR/server/.env"
      echo "   Redis отвечает; общее состояние включено."
      # ⚠️ ВОРКЕРОВ НЕ ПРОПИСЫВАЕМ. Даже когда всё готово, умолчание — один процесс:
      # молча занять восемь ядер значит переделать прод без спроса. Включает человек,
      # добавив GRADEBOOK_WORKERS, и только когда перенос состояния завершён целиком
      # (server/app/shared_state.py::PENDING_MIGRATION).
    else
      echo "   ⚠️ Redis не отвечает — сервер будет работать в ОДИН процесс (как раньше)."
    fi
  else
    echo "   ⚠️ redis-server не установился — сервер работает в ОДИН процесс (как раньше)."
  fi
else
  echo "== Redis не ставим: класс машины не workstation, несколько процессов не нужны =="
fi

echo "== [9/$TOTAL] systemd-служба gradebook =="

# ── Учётная запись службы ──────────────────────────────────────────────────────
# 🔴 ПОЧЕМУ НЕ root. Прежний юнит стоял с `User=root`, и это давало серверу, смотрящему
# в интернет, полные права на машину: любая ошибка в разборе запроса становилась бы не
# «утечкой данных журнала», а «машина целиком». Отдельный системный пользователь без
# оболочки и без домашнего каталога — граница, которая держится сама, без нашей
# аккуратности.
# ⚠️ `--no-create-home` намеренно: домашнего каталога у службы быть не должно, он всё
# равно недоступен из-за ProtectHome. Состояние живёт в StateDirectory (см. ниже).
if ! id -u gradebook >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin gradebook
  echo "   заведён системный пользователь gradebook"
else
  echo "   пользователь gradebook уже есть"
fi

# ── Каталог состояния ──────────────────────────────────────────────────────────
# 🔑 БАЗА ПЕРЕЕЗЖАЕТ ИЗ КАТАЛОГА КОДА В /var/lib/gradebook. Причина в требовании «код и
# release-каталог — только для чтения»: при `ProtectSystem=strict` весь диск для службы
# доступен на чтение, а писать можно лишь туда, что названо явно. База, лежащая среди
# кода, требовала бы открыть на запись сам каталог развёртывания — то есть отменить
# ровно то, ради чего ужесточение и делается (подменивший .py получает исполнение кода).
# ⚠️ Каталог создаёт и сам systemd (StateDirectory=), но нам он нужен РАНЬШЕ: сюда
# кладётся восстановленная база ещё до первого старта службы.
STATE_DIR="/var/lib/gradebook"
install -d -o gradebook -g gradebook -m 0700 "$STATE_DIR"
install -d -o gradebook -g gradebook -m 0700 "$STATE_DIR/attachments"

# Перенос базы, если она приехала в старое место (бандл со сборки или --restore-db).
for old in "$APP_DIR/server/gradebook_server.db"; do
  if [ -f "$old" ] && [ ! -f "$STATE_DIR/gradebook_server.db" ]; then
    echo "   переношу базу в $STATE_DIR (код становится только-для-чтения)"
    mv "$old" "$STATE_DIR/gradebook_server.db"
    for tail in -wal -shm; do
      [ -f "$old$tail" ] && mv "$old$tail" "$STATE_DIR/gradebook_server.db$tail"
    done
  fi
done
chown -R gradebook:gradebook "$STATE_DIR"

# ── Код — только для чтения ────────────────────────────────────────────────────
# Владелец root, службе только чтение и вход в каталоги. Так подмена кода требует root,
# а не компрометации самого сервера.
chown -R root:root "$APP_DIR"
chmod -R go-w "$APP_DIR"
# .env служба обязана ЧИТАТЬ (config.py дочитывает его при старте), но не более того.
# 0640 root:gradebook — читает служба и root, остальные не видят вовсе.
if [ -f "$APP_DIR/server/.env" ]; then
  chown root:gradebook "$APP_DIR/server/.env"
  chmod 640 "$APP_DIR/server/.env"
fi

# ── Секреты: из .env в учётные данные systemd ──────────────────────────────────
# `secrets_source.py` ищет секрет в трёх местах и первым — в $CREDENTIALS_DIRECTORY.
# Здесь мы этот первый источник и создаём. Смысл в том, что переменные окружения
# процесса видны в /proc/<pid>/environ и в `systemctl show`, то есть ключ от базы с ПДн
# читает любой, кто получил root, — включая администратора вуза, которому мы отдадим
# машину. Зашифрованные учётные данные видны ТОЛЬКО процессу службы, а на TPM-хосте ещё
# и привязаны к машине: снимок диска сам по себе их не открывает.
CRED_DIR="/etc/gradebook/credentials"
CRED_LINES=""
if command -v systemd-creds >/dev/null 2>&1 && [ -f "$APP_DIR/server/.env" ]; then
  install -d -o root -g root -m 0700 /etc/gradebook "$CRED_DIR"
  bash "$APP_DIR/tools/migrate_secrets_to_credentials.sh" \
       --env "$APP_DIR/server/.env" --out "$CRED_DIR" --strip || {
    echo "   ⛔ ОСТАНОВ: перенос секретов в учётные данные не удался." >&2
    echo "      Ставить службу с секретами в .env, объявив их перенесёнными, нельзя." >&2
    exit 7
  }
  for f in "$CRED_DIR"/*.cred; do
    [ -e "$f" ] || continue
    CRED_LINES="${CRED_LINES}LoadCredentialEncrypted=$(basename "$f" .cred):$f"$'\n'
  done
else
  echo "   ⚠️ systemd-creds недоступен (нужен systemd >= 250) — секреты остаются в .env."
  echo "      Это РАБОТАЕТ, но слабее: ключ виден в /proc/<pid>/environ любому root."
fi
# ProtectHome=yes отрезает /root, /home и /run/user. Если каталог развёртывания всё же
# оказался внутри них (оператор передал --dir), включать `yes` НЕЛЬЗЯ — служба не
# прочитает свой код. Понижаем до read-only и ГРОМКО об этом говорим: молча ослабленная
# защита хуже отсутствующей, потому что о ней потом отчитываются как о сделанной.
case "$APP_DIR" in
  /root/*|/home/*)
    PROTECT_HOME="read-only"
    echo "   ⚠️ ВНИМАНИЕ: код лежит в $APP_DIR, то есть внутри домашнего каталога."
    echo "      ProtectHome понижен с yes до read-only — иначе служба не видит свой код."
    echo "      Правильное лечение: развернуть в /opt/gradebook (умолчание)." ;;
  *) PROTECT_HOME="yes" ;;
esac

cat > /etc/systemd/system/gradebook.service <<UNIT
[Unit]
Description=GradeBookAI API server
After=network.target

[Service]
WorkingDirectory=$APP_DIR/server
# --loop uvloop --http httptools заданы ЯВНО, хотя uvicorn выбирает их сам при
# --loop auto / --http auto. Явность нужна не ради скорости (она уже есть, проверено по
# /proc/<pid>/maps живого процесса), а ради ГРОМКОГО отказа: пропадёт пакет из venv — и
# служба не поднимется вовсе, вместо того чтобы тихо съехать на медленный asyncio.
#
# 🔥 ЗДЕСЬ БЫЛ ЛИТЕРАЛЬНЫЙ "\n" ПОСРЕДИ СТРОКИ. В heredoc он не превращается в перенос —
# systemd получал его как ОТДЕЛЬНЫЙ аргумент uvicorn, и служба падала на старте с
# «unrecognized arguments». То есть самый первый запуск на новой машине не удался бы, а
# причина выглядела бы как поломка приложения. Команда пишется ОДНОЙ строкой.
#
# 🔑 С 10.09.2026 запуск идёт через server/serve.py, а не прямым вызовом uvicorn.
# Причина одна: число процессов нельзя писать в юните числом. Записанное здесь
# `--workers 4` описывало бы НАМЕРЕНИЕ и осталось бы прежним, когда Redis выключат или
# перенос состояния окажется незавершённым, — а это ослабляет анти-брутфорс ровно в N
# раз и совершенно молча. serve.py выводит число из готовности и печатает основание.
# ⚠️ Без GRADEBOOK_REDIS_URL поведение БУКВАЛЬНО прежнее: один процесс, uvloop, httptools.
Environment=GRADEBOOK_PORT=$PORT
# База и вложения — в каталоге состояния, а не среди кода (см. пояснение выше).
Environment=GRADEBOOK_DB_URL=sqlite:////var/lib/gradebook/gradebook_server.db
Environment=GRADEBOOK_FILES_DIR=/var/lib/gradebook/attachments
# Библиотеки, которые лезут в ~/.cache (huggingface, argos), должны попадать в свой
# каталог, а не падать об отсутствующий домашний.
Environment=XDG_CACHE_HOME=/var/cache/gradebook
Environment=HOME=/var/lib/gradebook
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/server/serve.py
Restart=always

# ━━ ГРАНИЦА ПРИВИЛЕГИЙ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
User=gradebook
Group=gradebook
UMask=0077
StateDirectory=gradebook
StateDirectoryMode=0700
CacheDirectory=gradebook
CacheDirectoryMode=0700
$CRED_LINES
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=$PROTECT_HOME
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
# Пустой набор — служба не сохраняет НИ ОДНОЙ привилегии. Это возможно только потому,
# что слушаем порт $PORT (>1024): для 80/443 понадобился бы CAP_NET_BIND_SERVICE, и
# именно поэтому наружу смотрит Caddy, а не мы.
CapabilityBoundingSet=
AmbientCapabilities=
# AF_UNIX нужен для локального Redis по петле и для журнала, AF_INET/AF_INET6 — сам
# HTTP. Всё остальное (AF_NETLINK, AF_PACKET) серверу журнала незачем.
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
SystemCallArchitectures=native
LockPersonality=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
ProtectHostname=yes
ProtectClock=yes
# ⚠️ MemoryDenyWriteExecute НАМЕРЕННО НЕ ВКЛЮЧЁН, хотя `systemd-analyze security` за него
# снимает баллы. Пояснение важнее балла: `cryptography` работает через cffi, а libffi
# создаёт исполняемые замыкания в памяти — с этим запретом падает подпись JWT и
# шифрование полей, то есть вход в журнал. Балл ради неработающего входа — плохой размен.

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now gradebook

# ── Проверка, а не надежда ─────────────────────────────────────────────────────
# Требование плана дословно: «нельзя применять вслепую: сначала staging, затем
# systemd-analyze security». Staging делает tools/staging_unit_check.sh ДО выкладки;
# здесь — обязательная проверка уже применённого.
sleep 3
if ! systemctl is-active --quiet gradebook; then
  echo "   ⛔ Служба НЕ поднялась после ужесточения. Журнал:" >&2
  journalctl -u gradebook -n 40 --no-pager >&2 || true
  echo "   Откат: systemctl edit gradebook (снять спорную директиву) и разобраться." >&2
  exit 8
fi
echo "   служба поднялась; оценка ужесточения:"
systemd-analyze security gradebook.service 2>/dev/null | tail -3 || \
  echo "   (systemd-analyze security недоступен на этой версии systemd)"

echo "== [10/$TOTAL] Caddy: боевой конфиг =="
# 🔑 БЕРЁМ НАСТОЯЩИЙ КОНФИГ ИЗ РЕПОЗИТОРИЯ, А НЕ ПИШЕМ СВОЙ.
# Прежняя версия этого скрипта писала здесь СОБСТВЕННЫЙ минимальный Caddyfile. Он
# поднимал сайт, и потому дефект был бы незаметен — но в нём не было НИЧЕГО из того, что
# в боевой конфиг добавляли отдельными заходами: сжатия (главный бандл уезжал бы
# несжатым, 1.3 МБ вместо 287 КБ), таймаутов против slowloris, лимитов тела, ротации
# журнала доступа, раздачи статики из /var/www и правила «на приложение идёт ВСЁ, кроме
# статики». Проект уже записал правило: боевой конфиг РОВНО ОДИН, и всякая вторая копия
# опасна. Поэтому — копия файла из бандла с подменой одной строки: домена.
if [ -f "$SRC/server/Caddyfile" ] && command -v caddy >/dev/null; then
  cp "$SRC/server/Caddyfile" /etc/caddy/Caddyfile
  if [ -n "$DOMAIN" ]; then
    # Меняем ТОЛЬКО строку блока сайта («esstu-gradebook.ru {»), а не все вхождения:
    # домен встречается и в комментариях, и правка их сделала бы конфиг непонятным.
    sed -i "s/^esstu-gradebook\.ru {/$DOMAIN {/" /etc/caddy/Caddyfile
  fi
  if caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
    echo "   боевой конфиг установлен и проверен"
  else
    echo "   ⚠️ caddy validate отверг конфиг — Caddy НЕ перезапущен, сайт остался как был."
    echo "      Это правильнее, чем применить сломанный конфиг и уронить домен."
  fi
else
  echo "   ⚠️ server/Caddyfile не приехал в бандле — Caddy не настроен."
  echo "      Сервер работает на 127.0.0.1:$PORT, снаружи он недоступен."
fi

echo
echo "======================================================================"
echo " ЖЕЛЕЗО:  $HW"
echo " СЛУЖБА:  $(systemctl is-active gradebook)"
HEALTH=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" || echo "нет ответа")
echo " /health: $HEALTH  (локально)"
if [ -n "$DOMAIN" ]; then
  PUB=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/health" || echo "нет ответа")
  echo " https://$DOMAIN/health: $PUB"
  if [ "$PUB" != "200" ]; then
    echo
    echo " ⚠️ ДОМЕН ЕЩЁ НЕ УКАЗЫВАЕТ СЮДА — и это ожидаемо, скрипт этого не умеет."
    echo "    Осталось ровно два действия, оба вне этой машины:"
    echo "      1) в панели регистратора перевести A-запись $DOMAIN на IP этой машины;"
    echo "      2) открыть снаружи порты 80 и 443 (сеть вуза)."
    echo "    Дальше Caddy получит сертификат сам, никаких команд не нужно."
    echo "    Проверить: curl -sS -o /dev/null -w '%{http_code}\\n' https://$DOMAIN/health"
  fi
fi
echo "======================================================================"
echo " Дальше по 152-ФЗ: ViPNet CSP (если ГОСТ-движок не найден) → перезапуск службы;"
echo " ключи ПДн — в СКЗИ/на токен; журнал учёта ключей; аттестация ИСПДн."
echo " ⚠️ Старый сервер НЕ трогали: он цел и продолжает работать. Выключать его можно"
echo "    только после того, как домен заработает отсюда."
echo "======================================================================"
