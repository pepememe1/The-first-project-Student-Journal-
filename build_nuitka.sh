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
# dropout_risk — та же история (3.6): общий корневой модуль правил риска отчисления,
# импортируется ТОЛЬКО из server/app/webdata.py, то есть из «данных». Без явного include
# локальный сервер внутри программы падал бы на импорте webdata, и кабинет не открылся
# бы вовсе — ровно тот же отказ, что когда-то давал забытый reminder_parse.
INC="$INC --include-module=dropout_risk"

# paramiko — ЕДИНСТВЕННЫЙ путь входа по ПАРОЛЮ в разделе «Сервер» (ui/server_admin.py).
# Системный ssh пароль ввести не может: он запускается с BatchMode=yes, а без него
# процесс без консоли повис бы на приглашении навсегда; `sshpass` на Windows нет.
# Импорт там ЛЕНИВЫЙ и обёрнут в try/except — то есть при входе по ключу пакет не нужен,
# и сборка без него остаётся рабочей (кнопка честно скажет, что пароль недоступен).
# Поэтому включаем ТОЛЬКО если пакет реально стоит в сборочном окружении: жёсткий
# --include-package уронил бы сборку на машине без него, а это ровно та поломка,
# которая обнаруживается в момент релиза.
# Дельта-обновления (data/updater.py): без zstandard программа обновляется полной
# закачкой .exe — то есть работает, просто тратит больше трафика. Поэтому включаем по
# тому же правилу, что и paramiko: только если пакет реально стоит в сборочном окружении.
if "$PYEXE" -c "import zstandard" >/dev/null 2>&1; then
  INC="$INC --include-package=zstandard"
  echo "[nuitka] zstandard найден — обновления пойдут дельтой (единицы МБ)"
else
  echo "[nuitka] zstandard НЕ найден — обновления будут качать .exe целиком"
  echo "         (поставить: \"$PYEXE\" -m pip install zstandard)"
fi

if "$PYEXE" -c "import paramiko" >/dev/null 2>&1; then
  INC="$INC --include-package=paramiko"
  echo "[nuitka] paramiko найден — вход по паролю будет доступен в сборке"
else
  echo "[nuitka] paramiko НЕ найден — в сборке останется только вход по ключу"
  echo "         (поставить: \"$PYEXE\" -m pip install paramiko)"
fi

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

# ⚠️ --include-package=webview и встроенный плагин pywebview ВМЕСТЕ НЕ РАБОТАЮТ: Nuitka
# считает это конфликтом решений («Conflict between user and plugin decision for module
# webview.platforms.android») и падает, не начавшись. Выбрано второе — плагин отключён,
# пакет берём целиком сами (см. блок про pythonnet ниже): плагин рассчитан на прежнюю
# раскладку и вырезает webview.platforms.win32, без которого окно не открывается.
# ━━ ЧЕГО В СБОРКЕ БОЛЬШЕ НЕТ И ПОЧЕМУ ━━
# Интерфейс рисует системный движок Edge, а он берёт арт и шрифты из web/dist —
# собранной SPA. Нативные наборы нужны были ТОЛЬКО Qt-экранам, которых в сборке нет:
#   emotions/ (42 МБ) + emotes/ (35 МБ) — причём emotes это ПОЛНЫЙ ДУБЛЬ
#     emotions/эмоции (проверено: 30 из 30 файлов совпали побайтово);
#     те же 30 эмоций и 6 анимаций уже лежат в web/dist/mascot и весят 7 МБ,
#     потому что сжаты для веба;
#   fonts/ (9 МБ) — грузились через QFontDatabase; SPA их не подключает вовсе.
# Итого ~86 МБ мёртвого груза. Вернутся, если вернётся Qt-оболочка.
# ⚠️ Шрифты стоит ОТДЕЛЬНО занести в web/public с @font-face — тогда фирменное
# начертание будет и в программе, и на сайте, а не только там, где Syne стоит в системе.
# ━━ ПОЧЕМУ ВЫКИНУТЫ ТЯЖЁЛЫЕ ИИ-ПАКЕТЫ ━━
# Nuitka тянет то, что стоит В ОКРУЖЕНИИ, а не то, что нужно программе. В сборочном
# Python оказались dev-пакеты распознавания речи, и exe раздулся до 135 МБ:
#   ctranslate2 57 МБ + av.libs 63 МБ + onnxruntime 34 МБ + numpy.libs 21 МБ +
#   PIL 11 МБ + hf_xet 9 МБ + tokenizers 7 МБ (замерено по распакованному payload).
# Все они нужны ЛОКАЛЬНОМУ Whisper, а он в .exe и не бандлился никогда: сама модель
# весит ~3 ГБ и качается отдельно. Импорты у них ленивые и обёрнуты в try/except
# (vector/stt.py, server/app/stt_service.py), поэтому без них программа работает, а
# распознавание честно отвечает «движок не установлен» — правильный ответ для машины
# без GPU. Настоящий дом Whisper — сервер ВСГУТУ с видеокартой.
# ━━ pywebview + pythonnet ━━
# Окно рисует WinForms через pythonnet, а рядом с ним лежит папка runtime/ с .NET-
# библиотеками (Python.Runtime.dll и компания). Для Nuitka это ДАННЫЕ: без них exe
# собирается, запускается и падает «You must have pythonnet installed».
# Встроенный плагин pywebview ОТКЛЮЧАЕМ (--disable-plugin): он рассчитан на прежнюю
# раскладку пакета и вырезает webview.platforms.win32, который pywebview 6 импортирует
# из winforms.py. Пока плагин включён, добавить модуль руками нельзя — Nuitka считает
# это конфликтом решений и падает. Отключив плагин, берём пакет целиком сами.
PYNET_RT="$("$PYEXE" -c "import pythonnet,os;print(os.path.join(os.path.dirname(pythonnet.__file__),'runtime'))")"
PYNET=""
[ -d "$PYNET_RT" ] && PYNET="--include-data-dir=$PYNET_RT=pythonnet/runtime"
echo "pythonnet runtime: ${PYNET_RT:-не найден}"

echo "== Nuitka старт $(date +%T) (Python: $PYEXE) =="
"$PYEXE" -m nuitka main.py \
  --standalone --onefile \
  --windows-console-mode=disable \
  --windows-icon-from-ico=icon.ico \
  --company-name=Synapse --product-name=GradeBookAI \
  --file-version=3.5.0.0 --product-version=3.5.0.0 \
  --output-filename=GradeBookAI.exe \
  --output-dir=nuitka_out \
  --assume-yes-for-downloads \
  --onefile-tempdir-spec="{CACHE_DIR}/GradeBookAI/{VERSION}" \
  --include-data-files=icon.ico=icon.ico \
  --include-data-files=icon.png=icon.png \
  --include-package=vector \
  --include-package=schedule \
  --disable-plugin=pywebview \
  --include-package=webview \
  --include-package=clr_loader \
  --include-package=pythonnet \
  --include-module=clr \
  $PYNET \
  --include-package=sqlcipher3 \
  $DATADIRS \
  $PKGS \
  $INC \
  --noinclude-data-files='*.debug.pak' \
  --noinclude-data-files='*.debug.bin' \
  --noinclude-data-files='qtwebengine_devtools_resources.pak' \
  --noinclude-data-files='qtwebengine_locales/*' \
  --noinclude-data-files='server/app/*__pycache__*' \
  --nofollow-import-to=tkinter \
  --nofollow-import-to=matplotlib \
  --nofollow-import-to=PyQt5 \
  --nofollow-import-to=PyQt6 \
  --nofollow-import-to=PySide6 \
  --nofollow-import-to=faster_whisper \
  --nofollow-import-to=ctranslate2 \
  --nofollow-import-to=onnxruntime \
  --nofollow-import-to=av \
  --nofollow-import-to=tokenizers \
  --nofollow-import-to=huggingface_hub \
  --nofollow-import-to=hf_xet \
  --nofollow-import-to=transformers \
  --nofollow-import-to=torch \
  --nofollow-import-to=numpy \
  --nofollow-import-to=PIL \
  --nofollow-import-to=sounddevice \
  --nofollow-import-to=scipy \
  --nofollow-import-to=pyttsx3 \
  --nofollow-import-to=psycopg2 \
  --remove-output
echo "== Nuitka конец $(date +%T), код $? =="
ls -la nuitka_out/GradeBookAI.exe 2>&1
