#!/usr/bin/env bash
# deploy-release.sh — выкладка НЕИЗМЕНЯЕМОГО артефакта с откатом переключением ссылки.
#
# ━━ ЧЕМ ОТЛИЧАЕТСЯ ОТ deploy-server.sh ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Тот кладёт файлы ПОВЕРХ работающего кода. Даже с `app.old` это означает, что в
# момент подмены на диске лежит смесь, а после неудачи состояние знает только тот,
# кто стоял рядом. Здесь код каждой версии живёт в СВОЁМ каталоге и не правится
# никогда; переключение — это перевод одной символической ссылки, а откат — перевод
# её обратно. Обе операции мгновенные и обратимые.
#
# ━━ ЧТО ЗДЕСЬ ЕСТЬ, ЧЕГО НЕ БЫЛО ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   • ПРОИСХОЖДЕНИЕ. В манифесте версия и коммит. Девять совпавших SHA-256 однажды
#     дали ложную уверенность: файлы доехали целиком, но из ДРУГОЙ ветки;
#   • ЦЕЛОСТНОСТЬ. sha256 считается НА СЕРВЕРЕ после заливки, а не только у нас;
#   • АВТОМАТИЧЕСКИЙ ОТКАТ. Не поднялся /health — ссылка возвращается на прежнюю
#     версию БЕЗ участия человека. Сейчас откат описан словами в конце вывода, то
#     есть выполняется тем, кто их прочитал и не растерялся;
#   • ОТКАЗ ВЫКЛАДЫВАТЬ ГРЯЗНОЕ ДЕРЕВО. Артефакт, который нельзя связать с
#     коммитом, нельзя и воспроизвести — а значит, и разобрать потом, что выложили.
#
# ━━ СОСТОЯНИЕ ОСТАЁТСЯ НА МЕСТЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# `.env`, база, `downloads/`, `ota_bundles/`, резервные копии живут в КАТАЛОГЕ
# СОСТОЯНИЯ и к версиям отношения не имеют. Выкладка их не трогает вовсе — ни
# читает, ни пишет. Это и позволяет откатываться, не думая о данных.
#
# ━━ ПЕРВЫЙ ЗАПУСК ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Нужна ОДНОРАЗОВАЯ подготовка машины: каталог версий и юнит systemd, смотрящий на
# ссылку `current`. Команда `--print-unit` печатает готовый юнит; ставит его
# человек, осознанно и один раз. Скрипт САМ юнит не подменяет: перенастройка
# работающей службы — не то, что делают попутно с выкладкой.
#
# Запуск:
#   bash deploy/deploy-release.sh --print-unit          # показать юнит и выйти
#   bash deploy/deploy-release.sh --dry-run             # собрать и показать план
#   bash deploy/deploy-release.sh                       # собрать и выложить
#   bash deploy/deploy-release.sh --rollback            # вернуть предыдущую версию
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${GB_VPS_KEY:-$HOME/.ssh/gb_vps_ed25519}"
VPS="${GB_VPS:-root@194.226.120.74}"
RELEASES="${GB_RELEASES:-/root/gb-releases}"
STATE="${GB_STATE:-/root/gb-deploy}"
SERVICE="${GB_SERVICE:-gradebook}"
KEEP="${GB_KEEP:-5}"
HEALTH_URL="${GB_HEALTH:-http://127.0.0.1:8000/health}"
O="-i $KEY -o BatchMode=yes -o ConnectTimeout=25 -o StrictHostKeyChecking=accept-new"

DRY=0; ROLLBACK=0; ALLOW_DIRTY=0; ARTIFACT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     DRY=1 ;;
    --rollback)    ROLLBACK=1 ;;
    --allow-dirty) ALLOW_DIRTY=1 ;;
    --artifact)    ARTIFACT="$2"; shift ;;
    --print-unit)  PRINT_UNIT=1 ;;
    *) echo "неизвестный ключ: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "${PRINT_UNIT:-0}" = "1" ]; then
  cat <<UNIT
# /etc/systemd/system/${SERVICE}.service
# ⚠️ Ставится ОДИН раз и человеком. Ключевое отличие от нынешнего юнита — пути
# ведут на ССЫЛКУ current, а не в каталог с кодом: тогда выкладка и откат
# сводятся к переводу ссылки, и служба подхватывает нужную версию рестартом.
[Unit]
Description=GradeBookAI API
After=network.target

[Service]
Type=simple
# Каталог ВЕРСИИ (только чтение по смыслу; никто в него не пишет).
WorkingDirectory=${RELEASES}/current
# Корневые общие модули лежат в подкаталоге root/ — тот же приём, что в .exe
# (§8.1, грабля 6: свои файлы нельзя класть в корень чужой раскладки).
Environment=PYTHONPATH=${RELEASES}/current/root
# Сайт отдаётся из артефакта — той же версии, что и код. Разъехаться нечему.
Environment=GRADEBOOK_WEB_DIST=${RELEASES}/current/webdist
# СОСТОЯНИЕ — в отдельном каталоге и переживает любые выкладки и откаты.
Environment=GRADEBOOK_DOWNLOADS=${STATE}/downloads
Environment=GRADEBOOK_OTA_DIR=${STATE}/ota_bundles
Environment=GRADEBOOK_BACKUP_DIR=/root/gb-backups
# ── СЕКРЕТЫ ──────────────────────────────────────────────────────────────────
# Пока — как раньше, файлом окружения. Это РАБОТАЕТ, но у способа есть цена:
# переменные окружения процесса видны в /proc/<pid>/environ и в `systemctl show`,
# то есть ключ от базы с ПДн доступен любому, кто получил на машине root.
EnvironmentFile=${STATE}/server/.env
#
# ⚠️ ПЕРЕХОД НА УЧЁТНЫЕ ДАННЫЕ СЛУЖБЫ (приложение это уже умеет —
# server/app/secrets_source.py). Делается на машине, один раз, руками:
#
#   1) зашифровать секреты ключом машины (TPM, если он есть):
#        systemd-ask-password -n | systemd-creds encrypt --name=gradebook-db-key - \\
#            /etc/credstore.encrypted/gradebook-db-key
#        (и так же gradebook-jwt-secret, gradebook-data-key, gradebook-index-key,
#         gradebook-smtp-pass, gradebook-s3-key, gradebook-s3-secret,
#         gradebook-klipy-api-key, gradebook-rustore-service-token)
#   2) заменить строку EnvironmentFile выше на список:
#        LoadCredentialEncrypted=gradebook-db-key
#        LoadCredentialEncrypted=gradebook-jwt-secret
#        ...
#   3) УДАЛИТЬ соответствующие строки из ${STATE}/server/.env.
#
# 🔥 Шаг 3 обязателен и его легко забыть. Порядок источников в приложении такой:
# учётные данные → файл → окружение, поэтому оставленная переменная НЕ сломает
# сервер — она просто не будет использоваться. Но ключ останется лежать в файле
# на диске, и мы будем считать, что убрали его, глядя на зелёный переход.
# Проверить, откуда сервер читает на самом деле, можно на странице «Сервер».
# ⚠️ ПУТЬ К VENV — СВОЙСТВО МАШИНЫ, А НЕ НАШЕГО РЕПОЗИТОРИЯ. Не копируй строку
# ниже вслепую: возьми ExecStart из ДЕЙСТВУЮЩЕГО юнита (`systemctl cat ${SERVICE}`)
# и поменяй в нём только рабочий каталог и переменные выше. Придуманный путь даст
# службу, которая не стартует, — и разбираться с этим будут в момент переезда.
ExecStart=/root/gb-venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop uvloop --http httptools
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
  exit 0
fi

ssh_do() { ssh $O "$VPS" "$@"; }

# ── Откат ────────────────────────────────────────────────────────────────────────
if [ "$ROLLBACK" = "1" ]; then
  echo "== ОТКАТ на предыдущую версию =="
  ssh_do "set -e
    test -L ${RELEASES}/previous || { echo 'нет ${RELEASES}/previous — откатываться не на что'; exit 1; }
    cur=\$(readlink -f ${RELEASES}/current); prev=\$(readlink -f ${RELEASES}/previous)
    echo \"  было:  \$cur\"; echo \"  станет: \$prev\"
    ln -sfn \"\$prev\" ${RELEASES}/current.tmp && mv -Tf ${RELEASES}/current.tmp ${RELEASES}/current
    ln -sfn \"\$cur\" ${RELEASES}/previous.tmp && mv -Tf ${RELEASES}/previous.tmp ${RELEASES}/previous
    systemctl restart ${SERVICE}"
  sleep 3
  ssh_do "curl -s -m 10 -o /dev/null -w '  /health: %{http_code}\n' ${HEALTH_URL}"
  echo "ГОТОВО."
  exit 0
fi

# ── Сборка ───────────────────────────────────────────────────────────────────────
if [ -z "$ARTIFACT" ]; then
  echo "== [1/6] Сборка артефакта =="
  ( cd "$ROOT" && python -X utf8 tools/build_release.py )
  ARTIFACT="$(ls -t "$ROOT/dist-release"/gradebook-*.tar.gz | head -1)"
fi
[ -f "$ARTIFACT" ] || { echo "нет артефакта: $ARTIFACT" >&2; exit 1; }

NAME="$(basename "$ARTIFACT")"
REL="${NAME%.tar.gz}"
SHA_LOCAL="$(python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$ARTIFACT")"

# Грязное дерево — отказ. Такую поставку нельзя ни воспроизвести, ни объяснить.
if [ "$ALLOW_DIRTY" != "1" ] && [ -n "$(cd "$ROOT" && git status --porcelain)" ]; then
  echo "ОТКАЗ: рабочее дерево грязное — артефакт нельзя связать с коммитом." >&2
  echo "       Закоммить правки либо запусти с --allow-dirty (только для staging)." >&2
  exit 1
fi

echo "  артефакт: $NAME"
echo "  sha256:   $SHA_LOCAL"
echo "  версия:   $REL"

if [ "$DRY" = "1" ]; then
  echo
  echo "== ПЛАН (ничего не выполняется) =="
  echo "  1. залить $NAME в ${RELEASES}/incoming/"
  echo "  2. сверить sha256 НА СЕРВЕРЕ"
  echo "  3. распаковать в ${RELEASES}/${REL}"
  echo "  4. previous := текущая current; current := ${REL}"
  echo "  5. systemctl restart ${SERVICE}, ждать ${HEALTH_URL}"
  echo "  6. не поднялось → вернуть ссылку и перезапустить"
  exit 0
fi

echo "== [2/6] Заливка =="
ssh_do "mkdir -p ${RELEASES}/incoming"
scp $O "$ARTIFACT" "$VPS:${RELEASES}/incoming/$NAME"

echo "== [3/6] Сверка целостности НА СЕРВЕРЕ =="
ssh_do "cd ${RELEASES}/incoming && echo '${SHA_LOCAL}  ${NAME}' | sha256sum -c -"

echo "== [4/6] Распаковка в отдельный каталог =="
ssh_do "set -e
  rm -rf ${RELEASES}/${REL}.part
  mkdir -p ${RELEASES}/${REL}.part
  tar -C ${RELEASES}/${REL}.part -xzf ${RELEASES}/incoming/${NAME}
  test -f ${RELEASES}/${REL}.part/app/main.py
  test -f ${RELEASES}/${REL}.part/MANIFEST.json
  rm -rf ${RELEASES}/${REL}
  mv -T ${RELEASES}/${REL}.part ${RELEASES}/${REL}
  rm -f ${RELEASES}/incoming/${NAME}
  # Права: код читают, но не пишут. Каталог версии неизменяем и по правам тоже.
  chmod -R a-w ${RELEASES}/${REL} || true
  echo -n '  версия из манифеста: '
  python3 -c \"import json;d=json.load(open('${RELEASES}/${REL}/MANIFEST.json'));print(d['version'], d['commit'][:12], 'файлов:', d['file_count'])\""

echo "== [5/6] Переключение и перезапуск =="
ssh_do "set -e
  mkdir -p ${RELEASES}
  if [ -L ${RELEASES}/current ]; then
    ln -sfn \"\$(readlink -f ${RELEASES}/current)\" ${RELEASES}/previous.tmp
    mv -Tf ${RELEASES}/previous.tmp ${RELEASES}/previous
  fi
  # mv -T над символической ссылкой атомарен: промежуточного состояния, когда
  # ссылки нет вовсе, не существует.
  ln -sfn ${RELEASES}/${REL} ${RELEASES}/current.tmp
  mv -Tf ${RELEASES}/current.tmp ${RELEASES}/current
  systemctl restart ${SERVICE}"

echo "== [6/6] Проверка здоровья (до 30 с) =="
OK=0
for i in $(seq 1 10); do
  sleep 3
  CODE="$(ssh_do "curl -s -m 5 -o /dev/null -w '%{http_code}' ${HEALTH_URL} || true")"
  echo "  попытка $i: /health = ${CODE:-нет ответа}"
  if [ "$CODE" = "200" ]; then OK=1; break; fi
done

if [ "$OK" != "1" ]; then
  echo
  echo "🔥 НЕ ПОДНЯЛОСЬ. Возвращаю прежнюю версию." >&2
  ssh_do "set -e
    test -L ${RELEASES}/previous || exit 1
    ln -sfn \"\$(readlink -f ${RELEASES}/previous)\" ${RELEASES}/current.tmp
    mv -Tf ${RELEASES}/current.tmp ${RELEASES}/current
    systemctl restart ${SERVICE}" || echo "ОТКАТ ТОЖЕ НЕ УДАЛСЯ — идти руками" >&2
  sleep 3
  ssh_do "journalctl -u ${SERVICE} -n 40 --no-pager" || true
  exit 1
fi

echo "== Уборка старых версий (оставляем ${KEEP}) =="
ssh_do "cd ${RELEASES} && ls -1dt gradebook-* 2>/dev/null | tail -n +$((KEEP+1)) | while read -r d; do
    cur=\$(readlink -f current); prev=\$(readlink -f previous 2>/dev/null || echo '')
    [ \"\$(readlink -f \"\$d\")\" = \"\$cur\" ] && continue
    [ \"\$(readlink -f \"\$d\")\" = \"\$prev\" ] && continue
    chmod -R u+w \"\$d\"; rm -rf \"\$d\"; echo \"  убрана \$d\"
  done" || true

echo
echo "ГОТОВО. Выложена ${REL}."
echo "Откат одной командой: bash deploy/deploy-release.sh --rollback"
