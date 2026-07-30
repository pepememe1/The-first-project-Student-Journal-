#!/usr/bin/env bash
# build_nuitka.sh — сборка ЗАЩИЩЁННОГО десктоп-клиента через Nuitka (компиляция в C →
# исходник практически не восстановить). Один .exe, весь клиентский код + арт внутри.
#
# Серверный пакет (server/app) ТЕПЕРЬ ВХОДИТ — это ОБЩИЙ Vue-интерфейс (§11 CLAUDE.md,
# «один UI»): десктоп поднимает его же у себя на 127.0.0.1 (ui/local_api.py), плюс тот
# же пакет нужен фоновому хостингу «этот ПК как сервер» (--run-server, server_control.py).
# ⚠️ Бандлится СЫРЫМИ файлами (--include-data-dir), а НЕ компилируется Nuitka-пакетом:
# ui/local_api.py и server/app/main.py находят друг друга через __file__-относительные
# обходы, которые ожидают РОВНО ДВА уровня вложенности «.../server/app/main.py» (та же
# раскладка, что и в исходниках). `--include-package=app` сплющил бы пакет до плоского
# app/ без server/ сверху — пути разъехались бы. Раз сервер и так публично слушает
# интернет на VPS (любой желающий видит его трафик/API), защищать его исходники здесь
# отдельным слоем смысла нет — Nuitka защищает КЛИЕНТСКИЙ код (ui/sync/data/vector/…),
# как и раньше; server/app просто едет как данные, тем не менее сборка работает целиком.
set -e
# Корень берём от САМОГО скрипта: путь к репозиторию у каждого разработчика свой, а
# захардкоженный чужой путь просто ломает сборку на любой другой машине.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(pwd -W 2>/dev/null || pwd)"

# Плоские импорты (ui/ sync/ data/ кладутся в sys.path через _bootstrap на рантайме) —
# Nuitka их сама не видит, поэтому даём папки в путь и включаем модули явно.
export PYTHONPATH="$ROOT/ui;$ROOT/sync;$ROOT/data"

# ⚠️ Собирать нужно ОБЫЧНЫМ python.org Python, НЕ из Microsoft Store: у Store-сборки
# песочница ломает пути MinGW, и gcc не находит windows.h. Ошибка при этом вылезает
# глубоко внутри компиляции и выглядит непонятно, поэтому ниже стоит явная проверка.
#
# Порядок выбора: переменная GRADEBOOK_PYEXE → установленные python.org сборки (свежие
# первыми) → системный python. Верхняя граница 3.14 не случайна: PySide6 требует <3.15.
#
# Рабочая версия команды — Python 3.14 (решение Ярослава, у него на ней собирается).
# ⚠️ Учтите: Nuitka 4.1.3 при старте пишет, что 3.14 поддержана ЭКСПЕРИМЕНТАЛЬНО и
# советует 3.13. Предупреждение не блокирует сборку, но если в готовом .exe полезут
# необъяснимые сбои — проверять эту связку нужно первой: `GRADEBOOK_PYEXE=...Python313`
# даёт полностью поддерживаемый вариант, зависимости туда уже поставлены.
PYEXE="${GRADEBOOK_PYEXE:-}"
if [ -z "$PYEXE" ]; then
  for ver in 314 313 312 311 310; do
    cand="$LOCALAPPDATA/Programs/Python/Python$ver/python.exe"
    [ -f "$cand" ] && { PYEXE="$cand"; break; }
  done
fi
[ -z "$PYEXE" ] && PYEXE="python"

# Fail fast: со Store-Python сборка всё равно не пройдёт, но упадёт неочевидно.
case "$("$PYEXE" -c 'import sys; print(sys.executable)')" in
  *WindowsApps*)
    echo "ОШИБКА: выбран Python из Microsoft Store — Nuitka с ним не соберётся." >&2
    echo "Поставьте python.org (winget install Python.Python.3.14) либо задайте" >&2
    echo "GRADEBOOK_PYEXE=путь/к/python.exe" >&2
    exit 1 ;;
esac

INC=""
for d in ui sync data; do
  for f in "$d"/*.py; do
    b="$(basename "$f" .py)"
    [ "$b" = "__init__" ] && continue
    INC="$INC --include-module=$b"
  done
done
for b in grading subjects server_control fonts app_paths _bootstrap main_window; do
  INC="$INC --include-module=$b"
done
# reminder_parse — общий корневой модуль (как grading/vector_nlu), но с ЕДИНСТВЕННЫМ
# потребителем: напоминания в мессенджере (server/app/routers/messenger.py, чисто
# онлайн-фича §5.4). Ни один клиентский .py его не импортирует, поэтому статический
# анализ Nuitka (идёт от main.py) его не увидит сам — а server/app у нас данные (см.
# ниже), значит и оттуда не подхватится. Без явного include local_api тихо не поднимался
# бы: `from app.main import app` роняется на `messenger.py`'s `import reminder_parse`.
# Проверено ПОЛНЫМ перебором всех корневых .py репозитория — остальные общие модули
# (grading/study_hours/vector_nlu/weather) уже импортируются откуда-то из ui/vector/data
# и потому попадают в сборку сами.
INC="$INC --include-module=reminder_parse"

# server/app + собранный сайт (web/dist) — см. комментарий в шапке файла: данными, не
# компиляцией. Нет одной из папок (свежий чекаут без server/ или без npm run build) —
# просто пропускаем эту часть, сборка не падает, фича молча не войдёт.
# ⚠️ server/app — ИМЕННО --include-raw-dir, а НЕ --include-data-dir: последний молча
# ФИЛЬТРУЕТ файлы кода (.py) как «не данные» («All non-code files are copied» — из
# --help самой Nuitka), считая, что .py-файлы либо компилируются отдельно, либо это
# ошибка. server/app — сплошь .py, и --include-data-dir отдал бы пустую папку без
# единого предупреждения о критичности (только тихий WARNING «No data files in
# directory»), а local_api.py потом молча не находил бы пакет `app`. web/dist —
# обычные статические ассеты (html/js/css), для них --include-data-dir корректен.
DATADIRS=""
[ -d server/app ] && DATADIRS="$DATADIRS --include-raw-dir=server/app=server/app"
[ -f web/dist/index.html ] && DATADIRS="$DATADIRS --include-data-dir=web/dist=web/dist"

# Серверный Python-стек (fastapi/uvicorn/…) — обычные site-packages зависимости самого
# server/app; --include-package тянет их целиком (в отличие от сырых данных, это code
# самого Nuitka, а не наш продукт — защищать/не защищать не наш вопрос).
PKGS=""
for p in fastapi starlette uvicorn sqlalchemy jose multipart webauthn httpx httpcore \
         anyio h11 websockets click; do
  PKGS="$PKGS --include-package=$p"
done
# stdlib email.* (mailer.py: MIMEText/MIMEMultipart) — та же беда, что у reminder_parse
# выше, но со стандартной библиотекой: Nuitka по умолчанию бандлит НЕ весь stdlib, а
# только модули, которые статически увидела от main.py. email.mime — сабпакет, который
# больше НИКТО в клиентском коде не трогает, поэтому без явного include получали бы
# «No module named 'email.mime'» уже ПОСЛЕ сборки, при первом запуске (обнаружено именно
# так — прогоном собранного exe, см. историю). Берём пакетом целиком (--include-package),
# а не точечными email.mime.text/multipart: email — самый частый источник таких сюрпризов
# (email.utils и т.п.), а весит он как модуль считаные килобайты.
PKGS="$PKGS --include-package=email"

echo "== Nuitka старт $(date +%T) (Python: $PYEXE) =="
"$PYEXE" -m nuitka main.py \
  --standalone --onefile \
  --enable-plugin=pyside6 \
  --windows-console-mode=disable \
  --windows-icon-from-ico=icon.ico \
  --company-name=Synapse --product-name=GradeBookAI \
  --file-version=3.4.1.0 --product-version=3.4.1.0 \
  --output-filename=GradeBookAI.exe \
  --output-dir=nuitka_out \
  --assume-yes-for-downloads \
  --onefile-tempdir-spec="{CACHE_DIR}/GradeBookAI/{VERSION}" \
  --include-data-dir=emotions=emotions \
  --include-data-dir=emotes=emotes \
  --include-data-dir=vector_assets=vector_assets \
  --include-data-dir=fonts=fonts \
  --include-data-files=icon.ico=icon.ico \
  --include-data-files=icon.png=icon.png \
  --include-package=vector \
  --include-package=schedule \
  $DATADIRS \
  $PKGS \
  $INC \
  --include-module=PySide6.QtWebEngineWidgets \
  --include-module=PySide6.QtWebEngineCore \
  --noinclude-data-files='*.debug.pak' \
  --noinclude-data-files='*.debug.bin' \
  --noinclude-data-files='qtwebengine_devtools_resources.pak' \
  --noinclude-data-files='qtwebengine_locales/*' \
  --noinclude-data-files='server/app/*__pycache__*' \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=matplotlib \
  --nofollow-import-to=PyQt5 \
  --nofollow-import-to=PyQt6 \
  --remove-output
echo "== Nuitka конец $(date +%T), код $? =="
ls -la nuitka_out/GradeBookAI.exe 2>&1
