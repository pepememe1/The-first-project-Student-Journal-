#!/usr/bin/env bash
# migrate_secrets_to_credentials.sh — перенести секреты из server/.env в зашифрованные
# учётные данные systemd (LoadCredentialEncrypted).
#
# ━━ ЗАЧЕМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Переменные окружения процесса видны в `/proc/<pid>/environ` и в выводе
# `systemctl show`. То есть ключ SQLCipher от базы с персональными данными студентов
# читает ЛЮБОЙ, кто получил на машине root, — в том числе администратор вуза, которому
# мы эту машину отдадим, и любой процесс, работающий от root. Ничего взламывать не надо.
# Учётные данные systemd видны только процессу службы, в окружении их нет, а при
# `SetCredentialEncrypted`/`LoadCredentialEncrypted` они и на диске лежат зашифрованными
# ключом машины (на хосте с TPM — привязанными к железу, снимок диска их не откроет).
#
# Читать их продукт УЖЕ умеет: `server/app/secrets_source.py`, источник номер один.
# Этот скрипт закрывает вторую половину — перенос на машине.
#
# ━━ ЧЕГО ЭТОТ СКРИПТ НЕ ДЕЛАЕТ ВСЛЕПУЮ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔴 Он НЕ вычищает .env, пока не убедится, что зашифрованное читается обратно и
# СОВПАДАЕТ с исходником. Иначе первая же ошибка шифрования уничтожила бы единственную
# копию ключа от базы — а это потеря всех данных навсегда, не «неудобство».
#
# Использование:
#   bash tools/migrate_secrets_to_credentials.sh --env server/.env --out /etc/gradebook/credentials
#   bash tools/migrate_secrets_to_credentials.sh --env … --out … --strip     # и вычистить .env
#   bash tools/migrate_secrets_to_credentials.sh --env … --out … --dry-run   # только показать
set -euo pipefail

ENV_FILE=""
OUT_DIR=""
STRIP=0
DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_FILE="$2"; shift 2;;
    --out) OUT_DIR="$2"; shift 2;;
    --strip) STRIP=1; shift;;
    --dry-run) DRY=1; shift;;
    *) echo "неизвестный аргумент: $1" >&2; exit 2;;
  esac
done

[ -n "$ENV_FILE" ] || { echo "нужен --env <путь к .env>" >&2; exit 2; }
[ -n "$OUT_DIR" ]  || { echo "нужен --out <каталог для .cred>" >&2; exit 2; }
[ -f "$ENV_FILE" ] || { echo "нет файла: $ENV_FILE" >&2; exit 2; }

if ! command -v systemd-creds >/dev/null 2>&1; then
  echo "⛔ systemd-creds не найден. Нужен systemd >= 250." >&2
  echo "   Без него перенос невозможен, и делать вид, что он состоялся, нельзя:" >&2
  echo "   продукт продолжит читать ключи из окружения." >&2
  exit 3
fi

# 🔑 СПИСОК ИМЁН БЕРЁТСЯ ИЗ ПРОДУКТА, А НЕ ПЕРЕПИСЫВАЕТСЯ СЮДА.
# Вторая копия списка разошлась бы молча, и первым забытым оказался бы новый секрет —
# он остался бы в .env, а мы считали бы перенос законченным. Тот же приём, что у
# `deploy-server.sh` с корневыми модулями.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYBIN="${GRADEBOOK_PY:-python3}"
NAMES="$("$PYBIN" - "$HERE" <<'PY'
import sys, os, importlib.util
root = sys.argv[1]
path = os.path.join(root, "server", "app", "secrets_source.py")
spec = importlib.util.spec_from_file_location("secrets_source", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(" ".join(mod.SECRET_NAMES))
PY
)"
[ -n "$NAMES" ] || { echo "⛔ не удалось прочитать SECRET_NAMES из secrets_source.py" >&2; exit 3; }

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

moved=0
skipped=0
for name in $NAMES; do
  # Значение берём ровно так, как его увидит config.py: строка `ИМЯ=значение`,
  # кавычки и CR отбрасываем.
  value="$(grep -E "^${name}=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"'\r' || true)"
  if [ -z "$value" ]; then
    skipped=$((skipped + 1))
    continue
  fi
  # systemd не любит подчёркивания в именах учётных данных — тот же перевод, что в
  # secrets_source._from_credentials_dir: GRADEBOOK_DB_KEY -> gradebook-db-key.
  cred="$(echo "$name" | tr 'A-Z_' 'a-z-')"
  if [ "$DRY" = "1" ]; then
    echo "  [проба] $name -> $OUT_DIR/$cred.cred"
    moved=$((moved + 1))
    continue
  fi
  printf '%s' "$value" | systemd-creds encrypt --name="$cred" --with-key=auto - "$OUT_DIR/$cred.cred"
  chmod 600 "$OUT_DIR/$cred.cred"

  # 🔴 ОБРАТНАЯ ПРОВЕРКА. Без неё мы бы вычистили .env, доверившись коду возврата
  # шифрования, — и узнали бы о расхождении в момент, когда база уже не открывается.
  back="$(systemd-creds decrypt --name="$cred" "$OUT_DIR/$cred.cred" - 2>/dev/null || true)"
  if [ "$back" != "$value" ]; then
    echo "⛔ $name: зашифрованное НЕ читается обратно тем же значением." >&2
    echo "   Файл $OUT_DIR/$cred.cred оставлен для разбора, .env НЕ тронут." >&2
    exit 4
  fi
  echo "  перенесён: $name -> $cred.cred (проверен обратным чтением)"
  moved=$((moved + 1))
done

echo "перенесено: $moved, пропущено (нет в .env или пусто): $skipped"

if [ "$STRIP" = "1" ] && [ "$DRY" != "1" ] && [ "$moved" -gt 0 ]; then
  # Копия рядом, с датой: «plaintext .env не должен оставаться вторым источником» —
  # но и удалять единственную копию ключа без резерва нельзя. Резерв кладём с правами
  # 600 и говорим о нём вслух, чтобы его унесли с машины, а не забыли.
  backup="$ENV_FILE.before-credentials-$(date +%Y%m%d-%H%M%S)"
  cp "$ENV_FILE" "$backup"
  chmod 600 "$backup"
  tmp="$(mktemp)"
  # Строки секретов не удаляем молча, а ЗАМЕЩАЕМ пометкой: следующий человек, открывший
  # .env, должен понять, куда делся ключ, а не решить, что его забыли задать.
  cp "$ENV_FILE" "$tmp"
  for name in $NAMES; do
    cred="$(echo "$name" | tr 'A-Z_' 'a-z-')"
    [ -f "$OUT_DIR/$cred.cred" ] || continue
    sed -i "s|^${name}=.*|# ${name} перенесён в учётные данные systemd ($cred.cred). Держать его здесь\n# нельзя: окружение процесса читается через /proc/<pid>/environ любым root.|" "$tmp"
  done
  mv "$tmp" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  echo "  .env очищен от секретов; резервная копия: $backup"
  echo "  ⚠️ УНЕСИТЕ резервную копию с машины и удалите её отсюда — пока она лежит рядом,"
  echo "     перенос не закончен, а лишь удвоил число мест, где лежит ключ."
fi
