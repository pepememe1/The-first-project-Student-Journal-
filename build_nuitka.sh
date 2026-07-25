#!/usr/bin/env bash
# build_nuitka.sh — сборка ЗАЩИЩЁННОГО десктоп-клиента через Nuitka (компиляция в C →
# исходник практически не восстановить). Один .exe, весь клиентский код + арт внутри.
# Сервер (host) не входит: он не распространяется (живёт на VPS), а вложение его сырых
# .py как данных свело бы защиту на нет.
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

echo "== Nuitka старт $(date +%T) (Python: $PYEXE) =="
"$PYEXE" -m nuitka main.py \
  --standalone --onefile \
  --enable-plugin=pyside6 \
  --windows-console-mode=disable \
  --windows-icon-from-ico=icon.ico \
  --company-name=Synapse --product-name=GradeBookAI \
  --file-version=2.9.0.0 --product-version=2.9.0.0 \
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
  $INC \
  --include-module=PySide6.QtWebEngineWidgets \
  --include-module=PySide6.QtWebEngineCore \
  --noinclude-data-files='*.debug.pak' \
  --noinclude-data-files='*.debug.bin' \
  --noinclude-data-files='qtwebengine_devtools_resources.pak' \
  --noinclude-data-files='qtwebengine_locales/*' \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=matplotlib \
  --nofollow-import-to=PyQt5 \
  --nofollow-import-to=PyQt6 \
  --nofollow-import-to=fastapi \
  --nofollow-import-to=uvicorn \
  --remove-output
echo "== Nuitka конец $(date +%T), код $? =="
ls -la nuitka_out/GradeBookAI.exe 2>&1
