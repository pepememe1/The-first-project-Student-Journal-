#!/usr/bin/env bash
# build_nuitka.sh — сборка ЗАЩИЩЁННОГО десктоп-клиента через Nuitka (компиляция в C →
# исходник практически не восстановить). Один .exe, весь клиентский код + арт внутри.
# Сервер (host) не входит: он не распространяется (живёт на VPS), а вложение его сырых
# .py как данных свело бы защиту на нет.
set -e
cd "c:/Users/yaros/Desktop/GB_2_7/The-first-project-Student-Journal-"
ROOT="$(pwd -W 2>/dev/null || pwd)"

# Плоские импорты (ui/ sync/ data/ кладутся в sys.path через _bootstrap на рантайме) —
# Nuitka их сама не видит, поэтому даём папки в путь и включаем модули явно.
export PYTHONPATH="$ROOT/ui;$ROOT/sync;$ROOT/data"

# ФИКС Store-Python: gcc из скачанного Nuitka MinGW не находит свои заголовки (windows.h)
# и библиотеки, потому что путь идёт через reparse-point песочницы Windows Store.
# Явно указываем include/lib каталоги MinGW через переменные gcc.
MINGW="C:/Users/yaros/AppData/Local/Packages/PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0/LocalCache/Local/Nuitka/Nuitka/Cache/downloads/gcc/x86_64/15.2.0posix-13.0.0-msvcrt-r6/mingw64"
GCCV="$MINGW/lib/gcc/x86_64-w64-mingw32/15.2.0"
if [ -f "$MINGW/x86_64-w64-mingw32/include/windows.h" ]; then
  export CPATH="$MINGW/x86_64-w64-mingw32/include;$MINGW/include;$GCCV/include;$GCCV/include-fixed"
  export LIBRARY_PATH="$MINGW/x86_64-w64-mingw32/lib;$MINGW/lib;$GCCV"
  export PATH="$MINGW/bin:$PATH"
  echo "CPATH задан на MinGW-заголовки."
fi

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

echo "== Nuitka старт $(date +%T) =="
python -m nuitka main.py \
  --standalone --onefile \
  --enable-plugin=pyside6 \
  --windows-console-mode=disable \
  --windows-icon-from-ico=icon.ico \
  --company-name=Synapse --product-name=GradeBookAI \
  --file-version=2.7.0.0 --product-version=2.7.0.0 \
  --output-filename=GradeBookAI.exe \
  --output-dir=nuitka_out \
  --assume-yes-for-downloads \
  --include-data-dir=emotions=emotions \
  --include-data-dir=emotes=emotes \
  --include-data-dir=vector_assets=vector_assets \
  --include-data-dir=fonts=fonts \
  --include-data-files=icon.ico=icon.ico \
  --include-data-files=icon.png=icon.png \
  --include-package=vector \
  --include-package=schedule \
  $INC \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=matplotlib \
  --nofollow-import-to=PyQt5 \
  --nofollow-import-to=PyQt6 \
  --nofollow-import-to=fastapi \
  --nofollow-import-to=uvicorn \
  --remove-output
echo "== Nuitka конец $(date +%T), код $? =="
ls -la nuitka_out/GradeBookAI.exe 2>&1
