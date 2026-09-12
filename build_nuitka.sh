#!/usr/bin/env bash
# build_nuitka.sh — сборка ЗАЩИЩЁННОГО десктоп-клиента через Nuitka (компиляция в C →
# исходник практически не восстановить). Один .exe, весь клиентский код + арт внутри.
#
# Серверный пакет (server/app) ТЕПЕРЬ ВХОДИТ — это ОБЩИЙ Vue-интерфейс (§11 CLAUDE.md,
# «один UI»): десктоп поднимает его же у себя на 127.0.0.1 (desktop/local_api.py), плюс тот
# ⚠️ Бандлится СЫРЫМИ файлами (--include-data-dir), а НЕ компилируется Nuitka-пакетом:
# desktop/local_api.py и server/app/main.py находят друг друга через __file__-относительные
# обходы, которые ожидают РОВНО ДВА уровня вложенности «.../server/app/main.py» (та же
# раскладка, что и в исходниках). `--include-package=app` сплющил бы пакет до плоского
# app/ без server/ сверху — пути разъехались бы. Раз сервер и так публично слушает
# интернет на VPS (любой желающий видит его трафик/API), защищать его исходники здесь
# отдельным слоем смысла нет — Nuitka защищает КЛИЕНТСКИЙ код (desktop/sync/data/…),
# как и раньше; server/app просто едет как данные, тем не менее сборка работает целиком.
set -e
# Корень берём от САМОГО скрипта: путь к репозиторию у каждого разработчика свой, а
# захардкоженный чужой путь просто ломает сборку на любой другой машине.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(pwd -W 2>/dev/null || pwd)"

# 🔥 Здесь СТОЯЛО: PYTHONPATH="$ROOT/desktop;$ROOT/sync;$ROOT/data" с пояснением «плоские
# импорты через _bootstrap на рантайме». И то, и другое устарело: `_bootstrap.py` удалён,
# плоских импортов в репозитории не осталось ни одного (проверено grep'ом по всем формам
# `from core import` / `import data_store` и т.п.), а desktop/ sync/ data/ — обычные пакеты.
# Оставлять подпапки в пути было не просто лишним, а ВРЕДНЫМ: ровно из-за такой раскладки
# один файл, импортированный и как `core`, и как `data.core`, даёт ДВА объекта модуля со
# своим состоянием — для DBManager это две независимые «единственные» точки доступа к базе.
# Тот же мусор убран из pytest.ini; здесь он прожил дольше просто потому, что сборку гоняют
# реже тестов.
export PYTHONPATH="$ROOT"

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

# Модули включаем ПОЛНЫМ ИМЕНЕМ ПАКЕТА (`data.core`, а не `core`). Раньше здесь стояло
# короткое имя — наследие плоских импортов: Nuitka послушно компилировала лишний модуль
# `core`, которого в продукте не существует, а настоящий `data.core` попадал в сборку
# только потому, что до него дотягивался анализ от main.py. Явное включение нужно не
# «на всякий случай»: часть этих модулей достижима ТОЛЬКО через server/app, а он едет
# сырыми данными (см. ниже) — статический анализ туда не заходит вовсе.
INC=""
for d in desktop sync data; do
  for f in "$d"/*.py; do
    b="$(basename "$f" .py)"
    [ "$b" = "__init__" ] && continue
    INC="$INC --include-module=$d.$b"
  done
done
for b in grading app_paths log; do
  INC="$INC --include-module=$b"
done
# 🔥 КОРНЕВЫЕ ОБЩИЕ МОДУЛИ, КОТОРЫЕ НУЖНЫ ТОЛЬКО СЕРВЕРНОМУ ПАКЕТУ.
# `server/app` едет СЫРЫМИ ДАННЫМИ (см. ниже), и статический анализ Nuitka туда не
# заходит вовсе — значит ни один модуль, достижимый ТОЛЬКО оттуда, сам в сборку не
# попадёт. Без него локальный сервер внутри программы не поднимается, и окно не
# открывается СОВСЕМ: `from app.main import app` роняется на первом же таком импорте.
#
# ⚠️ СПИСОК ВЫВОДИТСЯ ИЗ ИМПОРТОВ, А НЕ ХРАНИТСЯ ЗДЕСЬ. Здесь стояла рукописная тройка
# (reminder_parse, dropout_risk, grading) с припиской «проверено ПОЛНЫМ перебором —
# остальные (grading/study_hours/vector_nlu/weather) уже импортируются откуда-то из
# desktop/data и потому попадают сами». 28.08.2026 это оказалось НЕПРАВДОЙ: собранный
# .exe падал на `No module named 'vector_nlu'` и показывал диалог «не удалось открыть
# окно… чаще всего не хватает WebView2» — то есть неверную причину, потому что настоящую
# видно только в логе. Утверждение было верным в день, когда его писали, и молча
# устарело, когда с десктопной стороны пропал последний импортёр (снос Qt).
# Это ровно тот же класс отказа, что чинился в deploy/deploy-server.sh тем же приёмом:
# снимок значения отказывает именно в тот день, когда он нужен.
#
# 🔥 ВЕЗЁМ ИХ СЫРЫМИ ФАЙЛАМИ, А НЕ КОМПИЛЯЦИЕЙ — И ЭТО КУПЛЕНО ТРЕМЯ СБОРКАМИ.
# Сначала недостающие модули добавлялись как `--include-module=` (то есть компилировались
# Nuitka наравне с клиентским кодом). Собранный .exe после этого падал с «Nuitka: A
# segmentation fault has occurred» ещё ДО первой строки Python: ни лога, ни окна, ни
# внятного кода возврата. Сузили список с десяти модулей до пяти реально недостающих —
# segfault остался. Разбирать, какой именно из пяти лексиконов ломает компилятор, дорого
# (каждая проба — двадцать минут) и бессмысленно: компилировать их незачем.
#
# `server/app` и так едет `--include-raw-dir` (см. шапку файла), и общие корневые модули —
# такой же серверный код. Кладём их сырыми файлами в КОРЕНЬ распаковки: именно туда
# смотрит `server/app/webdata.py`, который делает sys.path.insert на три каталога вверх
# от себя. Это ровно та раскладка, что на боевом VPS (/root/gb-deploy/<модуль>.py рядом
# с server/app/), то есть одна механика вместо двух.
# ⚠️ Компилируем только то, до чего анализ дотянется сам (grading, study_hours,
# desktop_update — их импортируют из desktop/). Форсировать их не надо и не нужно.
ROOT_MODS="$(grep -rhoE '^[[:space:]]*(import|from)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' \
               server/app --include='*.py' 2>/dev/null \
             | awk '{print $2}' | sort -u \
             | while read -r m; do
                 if [ -f "$m.py" ]; then
                   # Только те, до которых анализ Nuitka не дотянется сам. Он идёт от
                   # main.py через desktop/ sync/ data/, поэтому импортируемое оттуда
                   # (grading, study_hours, desktop_update) компилируется и без нас.
                   # ⚠️ Граница слова — КЛАССОМ СИМВОЛОВ, а не `\b`: обратный слэш в этом
                   # шаблоне уже превращался в символ backspace, grep переставал находить
                   # что-либо, и фильтр молча пропускал ВСЁ.
                   if ! grep -rqE "^[[:space:]]*(import|from)[[:space:]]+$m([^A-Za-z0-9_]|$)" \
                          desktop sync data --include='*.py' 2>/dev/null; then
                     echo "$m.py"
                   fi
                 fi
               done | sort -u)"
if [ -z "$ROOT_MODS" ]; then
  echo "ОШИБКА: не нашлось ни одного корневого модуля server/app — разбор импортов сломался" >&2
  exit 1
fi
# Кладём их СЫРЫМИ ФАЙЛАМИ в ОТДЕЛЬНЫЙ подкаталог `gb_shared`, а путь к нему добавляет
# `desktop/local_api.py::ensure_server_path()` — рядом с тем местом, где он и так кладёт
# в sys.path каталог `server/`.
# ⚠️ ПОЧЕМУ НЕ В КОРЕНЬ РАСПАКОВКИ, хотя на боевом VPS раскладка именно такая
# (/root/gb-deploy/<модуль>.py рядом с server/app/): в корне onefile-распаковки лежит
# СОБСТВЕННЫЙ payload Nuitka — bootstrap, DLL, дерево dist. Класть туда свои файлы значит
# накладывать их на чужую раскладку; сборка с `=.` падала segfault'ом ещё до первой
# строки Python. Подкаталог ни на что не накладывается.
ROOT_STAGE="$(mktemp -d)"
trap 'rm -rf "$ROOT_STAGE" "${VENDOR_STAGE:-}"' EXIT
for f in $ROOT_MODS; do cp "$f" "$ROOT_STAGE/"; done
echo "[nuitka] корневые модули только-для-сервера (сырыми файлами): $ROOT_MODS"
INC="$INC --include-raw-dir=$ROOT_STAGE=gb_shared"

# ━━ СЕРВЕРНЫЙ СТЕК ЕДЕТ СЫРЫМ, А НЕ КОМПИЛИРУЕТСЯ (10.09.2026) ━━━━━━━━━━━━━━━━━━━
# 🔥 ЗАМЕР, ИЗ КОТОРОГО ЭТО ВЫРОСЛО. Распакованный payload — 172 МБ при 45.6 МБ архива,
# и 117 МБ из них это ОДИН внутренний бинарь Nuitka. Он получен из 16.8 МБ исходников,
# то есть раздувание примерно СЕМИКРАТНОЕ. Из этих 16.8 МБ нашего кода — 1.06 МБ, то
# есть ШЕСТЬ ПРОЦЕНТОВ; остальные 94 % — sqlalchemy (8 МБ .py), pydantic, websockets,
# click, webauthn и прочее.
#
# Компилировать их незачем по обеим причинам, ради которых здесь вообще взята Nuitka:
#   • ЗАЩИТА — это публичные библиотеки, тот же код открыто лежит на боевом VPS.
#     Nuitka у нас закрывает КЛИЕНТСКИЙ код (desktop/sync/data), и он остаётся закрыт;
#   • СКОРОСТЬ — горячие пути этих библиотек и так не на Python: у pydantic это
#     _pydantic_core.pyd (Rust), у SQLAlchemy — C-код sqlite3, у websockets — свои
#     расширения. Nuitka ускоряет питоновскую обвязку между ними, а её доля мала.
#
# Главное: они нужны ТОЛЬКО пакету `server/app`, который УЖЕ едет сырыми файлами и
# исполняется обычным интерпретатором (см. шапку файла). То есть это не новая схема, а
# распространение действующей на её же зависимости.
#
# ⚠️ ГРАНИЦА ПРОВЕДЕНА РАЗБОРОМ ИМПОРТОВ, А НЕ НА ГЛАЗ. Сюда попадает пакет, который не
# импортирует НИ ОДИН компилируемый файл (desktop/ sync/ data/ schedule/ корень).
# fastapi, starlette, uvicorn, httpx, paramiko, requests, cryptography, zstandard в
# список НЕ входят — их зовёт наш код, они остаются скомпилированными.
# ⚠️ Порядок импорта безопасен по построению: на верхнем уровне `desktop/local_api.py`
# лежит только stdlib, весь серверный стек он импортирует ЛЕНИВО — то есть уже после
# `ensure_server_path()`, которая и кладёт `gb_vendor` в sys.path.
# ⚠️ `.dist-info` везём вместе с пакетами: часть из них (websockets, pydantic) читает
# свою версию и точки расширения через `importlib.metadata`, и без метаданных это либо
# падает, либо тихо меняет поведение.
# 🔥 СПИСОК РАСШИРЕН 10.09.2026 ПОСЛЕ ТРЁХ НЕУДАЧНЫХ СБОРОК, И УРОК ОБЩИЙ.
# Сначала я «сэкономил» ещё полтора мегабайта, выбросив yaml, watchfiles, ecdsa и rsa
# как заведомо ненужные: их импортёры стоят под try/except, значит отсутствие безопасно.
# Рассуждение было верным по букве и неверным по существу. `jose` пробует
# cryptography-бэкенд, и ТОЛЬКО если тот не поднялся — берёт `ecdsa`. А cryptography
# компилировалась ЧАСТИЧНО: Nuitka включила ровно те её подмодули, до которых дотянулась
# от нашего клиентского кода, и нужного jose куска там не оказалось. Итог — падение на
# `No module named 'ecdsa'`, то есть на «запасном» пакете, которого не должно было
# понадобиться.
#
# 🔑 ПРАВИЛО, КОТОРОЕ ИЗ ЭТОГО СЛЕДУЕТ: пакет, который импортирует СЫРОЙ код, обязан
# присутствовать ЦЕЛИКОМ — сырым в gb_vendor либо `--include-package` без изъятий.
# Статический анализ в сырые файлы не заходит и подмодули угадать не может, а
# «необязательная» ветка чужой библиотеки становится обязательной ровно тогда, когда
# основная почему-то не сработала. Экономия в полтора мегабайта здесь стоила трёх
# сборок по девять минут — и это дешёвая цена только потому, что ошибка громкая.
VENDOR="sqlalchemy pydantic pydantic_core annotated_types typing_inspection jose \
        multipart python_multipart webauthn cbor2 pyasn1 pyasn1_modules websockets \
        click ecdsa rsa yaml watchfiles colorama dotenv openpyxl gigachat"
SITE="$("$PYEXE" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")"
VENDOR_STAGE="$(mktemp -d)"
for p in $VENDOR; do
  if [ ! -d "$SITE/$p" ]; then
    echo "ОШИБКА: пакет '$p' не найден в $SITE — сборка остановлена." >&2
    echo "Без него локальный сервер в программе не поднимется, и узнается это только" >&2
    echo "на живом запуске. Поставьте: \"$PYEXE\" -m pip install -r server/requirements.txt" >&2
    exit 1
  fi
  cp -r "$SITE/$p" "$VENDOR_STAGE/"
done
# .dist-info подбираем ОТДЕЛЬНЫМ проходом по RECORD: имя дистрибутива и имя пакета
# расходятся (python-jose → jose, python-multipart → multipart), и угадывать по имени
# каталога нельзя — RECORD перечисляет реально положенные файлы, это и есть связь.
for di in "$SITE"/*.dist-info; do
  [ -d "$di" ] || continue
  keep=""
  for p in $VENDOR; do
    if [ -f "$di/RECORD" ] && grep -qE "^$p/" "$di/RECORD"; then keep=1; break; fi
  done
  [ -n "$keep" ] && cp -r "$di" "$VENDOR_STAGE/"
done
find "$VENDOR_STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
VENDOR_KB="$(du -sk "$VENDOR_STAGE" | cut -f1)"
echo "[nuitka] серверный стек сырыми файлами: $((VENDOR_KB/1024)) МБ ($VENDOR)"
INC="$INC --include-raw-dir=$VENDOR_STAGE=gb_vendor"
# 🔥 STDLIB-ХВОСТ СЫРЫХ ПАКЕТОВ. Куплено отдельной сборкой 10.09.2026.
# Nuitka бандлит НЕ весь stdlib, а только те модули, которые увидела статическим
# разбором. Пока sqlalchemy компилировалась, её `import zoneinfo` был виден, и zoneinfo
# ехал в сборку сам. Как только пакет стал сырым, анализ туда заходить перестал — и
# собранная программа упала на `No module named 'zoneinfo'`. Ни одного предупреждения
# при сборке: она прошла успешно.
# ⚠️ Перечислять такие модули руками нельзя — это снимок значения, который откажет в
# день, когда любая из библиотек добавит себе новый импорт. Выводим разбором ТОГО ЖЕ
# каталога, который уезжает в сборку: список не может разойтись с содержимым.
STDLIB_TAIL="$("$PYEXE" -X utf8 - "$VENDOR_STAGE" <<'PYSTD'
import ast, os, sys

root = sys.argv[1]
found = set()
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
    for name in filenames:
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(open(os.path.join(dirpath, name), "rb").read())
        except (SyntaxError, ValueError, OSError):
            continue                      # часть файлов — шаблоны под другую версию
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])

# Встроенные (вкомпилированы в сам интерпретатор) включать не нужно и нельзя.
# tkinter и компания отрезаны отдельно ниже — тащить сюда GUI ради чужого докстринга
# незачем.
SKIP = {"tkinter", "turtle", "idlelib", "lib2to3", "test", "pydoc_data",
        "antigravity", "this", "__future__"}
# ⚠️ Проверяем НАЛИЧИЕ на этой платформе. Библиотеки пишутся кроссплатформенно и
# импортируют `termios`/`readline` под `if os.name != "nt"` — на Windows таких модулей
# нет вовсе, и `--include-module=termios` уронил бы сборку целиком. Отсутствие здесь
# безвредно ровно потому, что и в рантайме этой ветки не будет.
import importlib.util


def available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


out = sorted(
    m for m in found
    if m in sys.stdlib_module_names
    and m not in sys.builtin_module_names
    and m not in SKIP
    and available(m)
)
print(" ".join(out))
PYSTD
)"
if [ -n "$STDLIB_TAIL" ]; then
  echo "[nuitka] stdlib-хвост сырых пакетов: $(printf '%s' "$STDLIB_TAIL" | wc -w) модулей"
  for m in $STDLIB_TAIL; do INC="$INC --include-module=$m"; done
fi
for p in $VENDOR; do
  INC="$INC --nofollow-import-to=$p"
done

# paramiko — ЕДИНСТВЕННЫЙ путь входа по ПАРОЛЮ в разделе «Сервер» (desktop/server_admin.py).
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
# ⚠️ Здесь остались ТОЛЬКО те, которые импортирует наш КОМПИЛИРУЕМЫЙ код (проверено
# разбором импортов по desktop/ sync/ data/ schedule/ и корню):
#   fastapi, starlette, uvicorn, httpx — desktop/local_api.py и doctor.py;
#   httpcore, anyio, h11 — их же зависимости, оставлены с ними заодно.
# Остальной серверный стек уехал в gb_vendor сырыми файлами, см. блок ниже.
# ⚠️ ЦЕЛИКОМ, А НЕ «СКОЛЬКО УВИДЕЛ АНАЛИЗ». Эти пакеты зовёт и компилируемый
# клиентский код, и сырой серверный. Для клиента Nuitka сама подтянет нужные подмодули,
# а для сырого кода — не подтянет ничего, потому что не видит его вовсе. Значит либо
# пакет целиком, либо отказ в рантайме у случайной ручки. Именно на этом сломалась
# третья сборка: `cryptography` была включена частично.
for p in fastapi starlette uvicorn httpx httpcore anyio h11 \
         cryptography requests urllib3 certifi idna charset_normalizer \
         greenlet gostcrypto; do
  PKGS="$PKGS --include-package=$p"
done
# typing_extensions — один файл, а не пакет.
PKGS="$PKGS --include-module=typing_extensions"
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
# Итого ~86 МБ мёртвого груза.
# ⚠️ Qt-оболочки БОЛЬШЕ НЕТ В ПРОЕКТЕ — не «не включается в сборку», а удалена из
# исходников (перенесена в WORK/GB-legacy-qt). Раньше она формально существовала как
# запасной путь, но в .exe не попадала никогда, поэтому у людей не исполнялась ни разу —
# и молча накапливала поломки. Флаг --nofollow-import-to=PySide6 ниже оставлен
# СТРАХОВКОЙ: случайный импорт Qt не должен вернуть в сборку Chromium незаметно.
# ⚠️ Шрифты стоит ОТДЕЛЬНО занести в web/public с @font-face — тогда фирменное
# начертание будет и в программе, и на сайте, а не только там, где Syne стоит в системе.
# ━━ ПОЧЕМУ ВЫКИНУТЫ ТЯЖЁЛЫЕ ИИ-ПАКЕТЫ ━━
# Nuitka тянет то, что стоит В ОКРУЖЕНИИ, а не то, что нужно программе. В сборочном
# Python оказались dev-пакеты распознавания речи, и exe раздулся до 135 МБ:
#   ctranslate2 57 МБ + av.libs 63 МБ + onnxruntime 34 МБ + numpy.libs 21 МБ +
#   PIL 11 МБ + hf_xet 9 МБ + tokenizers 7 МБ (замерено по распакованному payload).
# Все они нужны ЛОКАЛЬНОМУ Whisper, а он в .exe и не бандлился никогда: сама модель
# весит ~3 ГБ и качается отдельно. Импорты у них ленивые и обёрнуты в try/except
# (server/app/stt_service.py), поэтому без них программа работает, а
# распознавание честно отвечает «движок не установлен» — правильный ответ для машины
# без GPU. Настоящий дом Whisper — сервер ВСГУТУ с видеокартой.
# ━━ ЧЕТЫРЕ ИСКЛЮЧЕНИЯ И ОТКАЗ ОТ ДОКСТРИНГОВ (10.09.2026) ━━
# Замер по РАСПАКОВАННОМУ payload (172 МБ при 45.6 МБ архива) показал, что мёртвого
# груза уровня «ИИ-пакеты» в сборке больше нет: numpy, PIL, torch, onnxruntime,
# ctranslate2 отсутствуют полностью — исключения выше работают. (Строки «tkinter» и
# «pytest» в бинаре есть, но это ТЕКСТ чужих докстрингов, а не модули: у pywebview в
# gui/__init__.py перечислены бэкенды, включая tkinter. Считать пакет включённым по
# совпадению подстроки нельзя — проверять надо по именам подмодулей.)
#
# Убираем четыре пакета, и у каждого названа причина, по которой отсутствие БЕЗОПАСНО —
# проверено чтением их импортёров, а не предположением:
#   yaml       — uvicorn/config.py импортирует его ВНУТРИ функции и только когда
#                log_config задан файлом .yaml; мы задаём конфиг объектом. У
#                starlette/schemas.py импорт под try/except и нужен генератору OpenAPI,
#                которым продукт не пользуется;
#   watchfiles — uvicorn/supervisors/__init__.py берёт его под try/except ImportError и
#                только ради --reload; локальный сервер поднимается через uvicorn.Config
#                без перезагрузки;
#   ecdsa, rsa — запасные бэкенды python-jose. jose/backends/__init__.py сначала пробует
#                cryptography_backend, и он у нас ЕСТЬ (Fernet, SQLCipher, подпись
#                выпуска) — значит до веток `except ImportError` дело не доходит.
#
# 🔴 ПЯТЫЙ КАНДИДАТ — `pyasn1` — НЕ ИСКЛЮЧЁН, И ЭТО ВАЖНО. Он выглядит как хвост `rsa`,
# но его импортирует ещё и `webauthn` (helpers/asn1/android_key.py,
# registration/formats/android_key.py) — разбор attestation при регистрации passkey.
# Убрав его «заодно», мы сломали бы заведение ключа входа, причём молча и только у тех,
# кто заводит passkey с Android-устройства. Правило прежнее: пакет исключают по РАЗБОРУ
# импортёров, а не по тому, что он оказался рядом в списке зависимостей.
#
# `--python-flag=no_docstrings` выбрасывает докстринги из КОМПИЛИРУЕМОГО кода. Основная
# цель — SQLAlchemy (19 МБ исходников, значительная часть которых документация).
# ⚠️ Почему это безопасно именно у нас, а вообще говоря — нет:
#   • FastAPI строит описание ручки из ЕЁ докстринга, но `server/app` едет СЫРЫМИ
#     файлами (см. шапку) и интерпретируется обычным Python — флаг его не касается;
#   • SQLAlchemy правит `__doc__` при импорте (util/deprecations.py) — проверено, что
#     она устойчива к None: `fn.__doc__ is not None and fn.__doc__ or ""`;
#   • click берёт текст помощи из докстрингов, но CLI uvicorn мы не запускаем;
#   • в нашем коде `__doc__` не используется функционально ни разу (проверено grep'ом).
# Флаг НЕ включает `no_asserts`: часть библиотек проверяет assert'ами настоящие
# инварианты, и снимать их ради килобайтов — размен не в нашу пользу.

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

# ⚠️ Nuitka сама ищет C-компилятор (MSVC через реестр, либо автозагрузка MinGW64 — но та
# работает ТОЛЬКО для Python <=3.12, а сборка идёт на 3.13/3.14). На машине без Visual
# Studio это вылезает уже ПОСЛЕ генерации C-кода: «FATAL: cannot locate suitable C
# compiler» — минуты компиляции Python-уровня на ветер, ошибка не в начале. `--zig` —
# третий вариант из этого же сообщения Nuitka: работает компилятором для любого
# 64-битного Python, без Visual Studio вообще. Добавляем, только если НИ MSVC, НИ MinGW
# не нашлись на PATH — не переопределяем выбор там, где Visual Studio уже настроена и
# работает (напр. у Ярослава, «решение... у него на ней собирается», см. комментарий у
# выбора Python выше).
#
# 🔥 ЖИВОЙ БАГ (Release-3.6.2): «Zig скачивается САМ» — НЕПРАВДА, несмотря на текст
# сообщения Nuitka «depends on 'zig' to compile» (звучит как обещание автозагрузки).
# Нужен pip-пакет `ziglang` В СБОРОЧНОМ Python + его каталог (там лежит zig.exe) НА
# PATH — без этого второго шага сборка падала уже на этапе C-компиляции, даже когда
# сам пакет был установлен (проверено: `pip install ziglang` без добавления в PATH
# всё равно не работает — `import ziglang` доступности исполняемости не даёт). Раньше
# PATH правился РУКАМИ в интерактивной сессии — фикс молча терялся при следующем
# запуске скрипта с нуля. Теперь скрипт делает это САМ.
CC_FLAG=""
if ! command -v cl.exe >/dev/null 2>&1 && ! command -v gcc.exe >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1; then
  echo "[nuitka] Visual Studio/MinGW не найдены на PATH — используем --zig"
  CC_FLAG="--zig"
  ZIG_DIR="$("$PYEXE" -c "import ziglang, os; print(os.path.dirname(ziglang.__file__))" 2>/dev/null || true)"
  if [ -z "$ZIG_DIR" ]; then
    echo "[nuitka] пакет ziglang не найден в сборочном Python — ставлю"
    "$PYEXE" -m pip install --quiet ziglang
    ZIG_DIR="$("$PYEXE" -c "import ziglang, os; print(os.path.dirname(ziglang.__file__))" 2>/dev/null || true)"
  fi
  if [ -n "$ZIG_DIR" ]; then
    export PATH="$ZIG_DIR:$PATH"
    echo "[nuitka] zig.exe добавлен в PATH: $ZIG_DIR"
  else
    echo "[nuitka] ⚠️ не удалось найти/поставить ziglang — сборка, скорее всего, упадёт на этапе C-компиляции"
  fi
fi

# 🔥 Версия .exe БОЛЬШЕ НЕ ЗАХАРДКОЖЕНА. Здесь стояло `--file-version=3.5.0.0
# --product-version=3.5.0.0` — при том, что APP_VERSION давно ушла на 3.7.x. Это не
# косметика в свойствах файла: та же строка подставляется в --onefile-tempdir-spec
# ({VERSION}), то есть КАЖДЫЙ выпуск распаковывался в одну и ту же папку кэша
# %LOCALAPPDATA%\GradeBookAI\3.5.0.0. Именно она сбила с толку разбор автообновления в
# 3.6.2 («обновление применилось к копии в кэше, а не к настоящему .exe»).
# Берём из ЕДИНСТВЕННОГО места (desktop_update.py::APP_VERSION) и приводим к формату
# Windows «a.b.c.d»: «Release 3.7.3» → 3.7.3.0.
FILEVER="$("$PYEXE" -c "
import re, pathlib
src = pathlib.Path('desktop_update.py').read_text(encoding='utf-8')
m = re.search(r'APP_VERSION\s*=\s*[\'\"]([^\'\"]+)', src)
nums = re.findall(r'\d+', m.group(1) if m else '')
nums = (nums + ['0', '0', '0', '0'])[:4]
print('.'.join(nums))
")"
if ! printf '%s' "$FILEVER" | grep -qE '^[0-9]+(\.[0-9]+){3}$'; then
  echo "ОШИБКА: не удалось прочитать APP_VERSION из desktop_update.py (получено: '$FILEVER')." >&2
  echo "Сборка остановлена: .exe с чужим номером версии распакуется в чужую папку кэша." >&2
  exit 1
fi
echo "[nuitka] версия сборки: $FILEVER"

echo "== Nuitka старт $(date +%T) (Python: $PYEXE) =="
"$PYEXE" -m nuitka main.py \
  --standalone --onefile \
  --python-flag=no_docstrings \
  --no-deployment-flag=excluded-module-usage \
  $CC_FLAG \
  --windows-console-mode=disable \
  --windows-icon-from-ico=icon.ico \
  --company-name=Synapse --product-name=GradeBookAI \
  --file-version="$FILEVER" --product-version="$FILEVER" \
  --output-filename=GradeBookAI.exe \
  --output-dir=nuitka_out \
  --assume-yes-for-downloads \
  --onefile-tempdir-spec="{CACHE_DIR}/GradeBookAI/{VERSION}" \
  --include-data-files=icon.ico=icon.ico \
  --include-data-files=icon.png=icon.png \
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
  --remove-output
echo "== Nuitka конец $(date +%T), код $? =="
ls -la nuitka_out/GradeBookAI.exe 2>&1
