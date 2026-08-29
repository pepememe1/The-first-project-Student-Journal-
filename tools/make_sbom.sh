#!/usr/bin/env bash
# make_sbom.sh — состав поставки (SBOM) в формате CycloneDX.
#
# Зачем НАМ, а не «потому что модно». Два конкретных адресата:
#   • ФГБОУ ВО ВСГУТУ при закупке спросит, из чего состоит поставляемое ПО, —
#     это обычное требование к приёмке, и отвечать «сейчас соберём» в тот момент
#     поздно;
#   • заявка в реестр российского ПО (ПП РФ № 1236) проверяет ОТСУТСТВИЕ
#     принудительной зависимости от иностранного ПО. Список зависимостей там
#     нужен не «примерно», а поимённо и с версиями.
#
# Третий адресат — мы сами: когда выйдет очередная громкая уязвимость, вопрос
# «есть ли у нас этот пакет и какой версии» решается чтением файла, а не
# раскопками по трём requirements и package-lock.
#
# ⚠️ Собираем ПО ОБЪЯВЛЕННЫМ спискам (requirements/package-lock), а не по тому,
# что оказалось установлено на машине сборки. Разница принципиальная: именно
# «оказалось установлено» и скрывало от нас отсутствие requests в
# server/requirements.txt — на бою он стоял транзитивно, и SBOM по окружению
# показал бы благополучие там, где инструкция по установке была неполной.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="$ROOT/sbom"
mkdir -p "$OUT"

VERSION="$(python -c "import re,io; s=io.open('desktop_update.py',encoding='utf-8').read(); print(re.search(r'APP_VERSION\s*=\s*[\"\x27]([^\"\x27]+)', s).group(1))")"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "== SBOM для GradeBookAI $VERSION ($COMMIT) =="

# ── Python: сервер и десктоп отдельными файлами ──
# Отдельными, а не одним: на машину ВСГУТУ едет ТОЛЬКО серверный набор, и
# смешивать в одном документе то, что там никогда не окажется, — вводить
# проверяющего в заблуждение.
for pair in "server/requirements.txt:server" "requirements.txt:desktop"; do
  req="${pair%%:*}"; name="${pair##*:}"
  echo "-- python/$name ($req)"
  # --output-reproducible: без него в документ попадают отметка времени и
  # случайный serialNumber, и два SBOM одной и той же поставки различаются
  # побайтово. Для неизменяемого артефакта это недопустимо — сверять нечем.
  # Зовём модулем (`python -m`), а не именем команды: на Windows скрипты pip
  # не всегда попадают в PATH, и сборка падала бы «command not found».
  # ⚠️ PYTHONUTF8: в наших requirements пояснения по-русски, а на Windows файл
  # читается системной кодировкой (cp1251) — инструмент падал «charmap codec
  # can't decode». На Linux этого не видно вовсе, то есть сборка SBOM работала
  # бы в CI и ломалась у человека на машине.
  PYTHONUTF8=1 python -m cyclonedx_py requirements "$req" \
      --of JSON \
      --output-reproducible \
      --no-validate \
      -o "$OUT/sbom-python-$name.cdx.json"
done

# ── Веб ──
# package-lock.json, а не node_modules: нас интересует то, что будет
# установлено по инструкции, а не слепок чьей-то машины.
if [ -f web/package-lock.json ]; then
  echo "-- npm/web"
  # --output-reproducible и здесь: без него документ получает случайный
  # serialNumber и отметку времени, и два SBOM ОДНОЙ И ТОЙ ЖЕ поставки
  # различаются побайтово. Замерено 29.08.2026 — питоновские файлы совпадали,
  # а этот нет, то есть «сверьте состав поставки» работало наполовину.
  npx --yes @cyclonedx/cyclonedx-npm@2.0.0 \
      --output-format JSON \
      --output-reproducible \
      --output-file "$OUT/sbom-web.cdx.json" \
      --package-lock-only \
      web/package.json
else
  echo "ВНИМАНИЕ: нет web/package-lock.json — состав веба в SBOM не попадёт" >&2
fi

# ── Сопроводительная записка ──
# Человекочитаемая: SBOM читает машина, а на приёмке спросит человек.
{
  echo "GradeBookAI — состав поставки (SBOM)"
  echo "Версия:        $VERSION"
  echo "Коммит:        $COMMIT"
  echo "Собрано (UTC): $STAMP"
  echo "Формат:        CycloneDX, JSON"
  echo
  echo "Файлы:"
  for f in "$OUT"/*.cdx.json; do
    [ -e "$f" ] || continue
    n="$(python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(len(d.get('components',[])))" "$f")"
    echo "  $(basename "$f") — компонентов: $n"
  done
  echo
  echo "Что НЕ входит и почему:"
  echo "  * модели Argos/Silero/Whisper — не пакеты, а данные; ставятся отдельно"
  echo "    и в репозитории не лежат (сотни МБ);"
  echo "  * системные компоненты Windows (WebView2 Runtime) — часть ОС покупателя,"
  echo "    мы их не поставляем и не линкуем."
} > "$OUT/SBOM-README.txt"

echo "ГОТОВО. Файлы в $OUT"
ls -la "$OUT"
