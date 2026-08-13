# -*- mode: python ; coding: utf-8 -*-
# GradeBookAI.spec — сборка ДЕСКТОП-КЛИЕНТА в один .exe (onefile, без консоли).
#
# Особенности проекта, которые учтены:
#  • Плоские импорты: код лежит в desktop/ sync/ data/, но импортируется плоско
#    (from core import ...) через _bootstrap.py. Даём эти папки в pathex И добавляем
#    все их .py как hiddenimports (PyInstaller не видит sys.path, который правит
#    _bootstrap на рантайме).
#  • Арт маскота (emotions/), шрифты (fonts/), иконка — кладём в бандл; код находит их
#    в _MEIPASS (emotes по модуль-относительным путям, fonts/get_icon — пропатчены).
#  • subjects.json НЕ бандлим (в subjects.py есть встроенный дефолт).
#  • ОБЩИЙ Vue-интерфейс (§11 CLAUDE.md, «один UI»): десктоп поднимает НАСТОЯЩЕЕ серверное
#    приложение (server/app) у себя же на 127.0.0.1 (desktop/local_api.py). Поэтому пакет
#    server/app и собранный web/dist бандлятся как ДАННЫЕ (сырые файлы, не через pyz) —
#    ровно та же раскладка путей, что и в исходниках репозитория (desktop/local_api.py и
#    server/app/main.py ищут их относительно СВОЕГО расположения, см. ниже). Серверные
#    Python-зависимости (fastapi/uvicorn/SQLAlchemy/jose/webauthn/httpx) — в hiddenimports:
#    без них локальный сервер просто не поднимется (desktop/local_api.py съест исключение и
#    десктоп тихо останется на нативных экранах — деградация, не крах, но фичи не будет).
#  • Серверный ФОНОВЫЙ режим --run-server (server_control.py, «этот ПК как сервер для ЛВС
#    колледжа») входит туда же: он использует ТОТ ЖЕ бандл server/app, просто с другим
#    биндом (0.0.0.0) и по кнопке в админке, а не автоматически.
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = os.path.abspath('.')


def _flat_mods(d):
    p = os.path.join(ROOT, d)
    if not os.path.isdir(p):
        return []
    return [f[:-3] for f in os.listdir(p) if f.endswith('.py') and not f.startswith('__')]


hidden = []
for d in ('desktop', 'sync', 'data'):
    hidden += _flat_mods(d)
# корневые модули, которые тоже импортируются плоско/лениво
hidden += ['grading', 'subjects', 'server_control', 'app_paths', 'log']
# reminder_parse — общий корневой модуль (как grading/vector_nlu), но с ЕДИНСТВЕННЫМ
# потребителем: напоминания в мессенджере (server/app/routers/messenger.py, §5.4).
# Ни один клиентский .py его не импортирует — статический анализ PyInstaller (идёт от
# main.py) его не увидит, а server/app у нас в datas (сырые файлы), не в code — тоже не
# подхватит. Обнаружено прогоном СОБРАННОГО Nuitka-exe (та же схема сборки) — там без
# явного include local_api не поднимался вовсе.
hidden += ['reminder_parse']
# dropout_risk (3.6) — правила риска отчисления. Импортируется только из
# server/app/webdata.py, который для сборщика — данные, а не код: без явного include
# локальный сервер внутри программы не поднимется.
hidden += ['dropout_risk']
# sqlcipher3 — ШИФРОВАНИЕ локальной копии базы (desktop/local_api.py). Модуль самодостаточный:
# один .pyd со статически влинкованным SQLCipher, внешних DLL не тянет, поэтому вшивается
# в exe как обычная зависимость — ПОЛЬЗОВАТЕЛЮ КАЧАТЬ НИЧЕГО НЕ НАДО. Импортируется
# ЛЕНИВО внутри server/app/db.py (а тот лежит в datas сырыми файлами), поэтому статический
# анализ его не найдёт — нужен явный hiddenimport, иначе копия молча останется открытой.
hidden += ['sqlcipher3', 'sqlcipher3.dbapi2']
# пакеты
for pkg in ('vector', 'schedule'):
    hidden += collect_submodules(pkg)
# зависимости, которые импортируются лениво/динамически
hidden += ['gostcrypto', 'gostcrypto.gostpbkdf', 'requests', 'cryptography',
           'openpyxl', 'win32crypt']
# stdlib email.* (server/app/mailer.py: MIMEText/MIMEMultipart) — тот же случай, что и
# reminder_parse выше, но со стандартной библиотекой: без явного include Nuitka-сборка
# (см. build_nuitka.sh) падала на «No module named 'email.mime'» при первом запуске.
hidden += collect_submodules('email')
# ⚠️ QtWebEngine БОЛЬШЕ НЕ ВКЛЮЧАЕТСЯ. Окно рисует системный движок Edge (WebView2), а
# Qt-оболочка убрана из проекта целиком (см. main.py) — Chromium внутри PySide6 стоил бы
# ~150 МБ ради кода, которого больше нет. Списки исключений ниже оставлены как страховка:
# случайный импорт Qt не должен снова раздуть сборку незаметно.
# python-docx (Word-экспорт журнала/ведомости) — импортируется лениво (data/exports.py).
# Пакет ставится как python-docx, а импортируется как `docx`; ему нужны его шаблоны
# (docx/templates/*.docx), поэтому тянем и submodules, и data-файлы.
hidden += collect_submodules('docx')
# Серверный стек (общий Vue-интерфейс + фоновый хостинг --run-server, см. шапку файла).
# server/app сам НЕ здесь — он бандлится как ДАННЫЕ (см. datas ниже) и импортируется
# обычным файловым импортом (ensure_server_path добавляет распакованный server/ в
# sys.path), поэтому его подмодули статике PyInstaller не нужны. А вот это —
# настоящие site-packages зависимости, которые FastAPI/uvicorn тянут лениво (роутеры,
# lifespan, ASGI-протокол) и которые статический анализ main.py не увидит сам.
for pkg in ('fastapi', 'starlette', 'uvicorn', 'sqlalchemy', 'jose', 'multipart',
            'webauthn', 'httpx', 'httpcore', 'anyio', 'h11', 'websockets', 'click'):
    hidden += collect_submodules(pkg)

datas = []
datas += collect_data_files('docx')   # шаблон default.docx и пр. — иначе Document() падает
for folder in ('emotions', 'emotes', 'vector_assets', 'fonts'):
    if os.path.isdir(os.path.join(ROOT, folder)):
        datas.append((folder, folder))
for f in ('icon.ico', 'icon.png'):
    if os.path.isfile(os.path.join(ROOT, f)):
        datas.append((f, '.'))
# server/app — СЫРЫМИ файлами (не через pyz): desktop/local_api.py и server/app/main.py сами
# находят его через __file__-относительные пути ОТНОСИТЕЛЬНО РАСПАКОВАННОГО _MEIPASS
# (та же раскладка, что в исходниках репозитория — server/ рядом с корнем). Нет папки на
# машине сборки (свежий чекаут без server/) — просто пропускаем, фича молча не войдёт.
_server_app = os.path.join('server', 'app')
if os.path.isdir(os.path.join(ROOT, _server_app)):
    datas.append((_server_app, _server_app))
# Собранный сайт (web/dist) — server/app/main.py::_find_web_dist его ищет по этому же
# относительному пути; нет сборки (npm run build не запускали) — сервер поднимется
# как чистый API без SPA, это штатная деградация, не ошибка сборки exe.
_web_dist = os.path.join('web', 'dist')
if os.path.isfile(os.path.join(ROOT, _web_dist, 'index.html')):
    datas.append((_web_dist, _web_dist))

a = Analysis(
    ['main.py'],
    pathex=[ROOT, os.path.join(ROOT, 'desktop'), os.path.join(ROOT, 'sync'),
            os.path.join(ROOT, 'data')],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)

# ── Страховка: Qt не должен просочиться в сборку ──────────────────────────────────────
# Здесь раньше стояла обрезка QtWebEngine (Chromium тянул ~200 МБ, и из него вырезались
# отладочные ресурсы, DevTools и лишние локали). Теперь Qt в проекте нет вовсе — окно
# рисует системный движок Edge, — поэтому обрезать нечего. Но молчаливое возвращение Qt
# «одним импортом» уже удваивало размер .exe (49 → 135 МБ, §8.1), а замечают это только
# при выкладке. Поэтому не фильтруем, а РОНЯЕМ сборку: пусть отказ будет громким.
_qt = [t[0] for t in (a.binaries + a.datas)
       if 'pyside6' in (t[0] or '').lower() or 'qt6' in (t[0] or '').lower()]
if _qt:
    raise SystemExit(
        'В сборку попал Qt — значит где-то вернулся импорт PySide6. Это ~150 МБ и '
        'откат к убранной оболочке. Найдите импорт, а не выключайте эту проверку.\n'
        'Первые совпадения: ' + ', '.join(_qt[:5]))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GradeBookAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='icon.ico',
)
