# -*- mode: python ; coding: utf-8 -*-
# GradeBookAI.spec — сборка ДЕСКТОП-КЛИЕНТА в один .exe (onefile, без консоли).
#
# Особенности проекта, которые учтены:
#  • Плоские импорты: код лежит в ui/ sync/ data/, но импортируется плоско
#    (from core import ...) через _bootstrap.py. Даём эти папки в pathex И добавляем
#    все их .py как hiddenimports (PyInstaller не видит sys.path, который правит
#    _bootstrap на рантайме).
#  • Арт маскота (emotions/), шрифты (fonts/), иконка — кладём в бандл; код находит их
#    в _MEIPASS (emotes по модуль-относительным путям, fonts/get_icon — пропатчены).
#  • subjects.json НЕ бандлим (в subjects.py есть встроенный дефолт).
#  • ОБЩИЙ Vue-интерфейс (§11 CLAUDE.md, «один UI»): десктоп поднимает НАСТОЯЩЕЕ серверное
#    приложение (server/app) у себя же на 127.0.0.1 (ui/local_api.py). Поэтому пакет
#    server/app и собранный web/dist бандлятся как ДАННЫЕ (сырые файлы, не через pyz) —
#    ровно та же раскладка путей, что и в исходниках репозитория (ui/local_api.py и
#    server/app/main.py ищут их относительно СВОЕГО расположения, см. ниже). Серверные
#    Python-зависимости (fastapi/uvicorn/SQLAlchemy/jose/webauthn/httpx) — в hiddenimports:
#    без них локальный сервер просто не поднимется (ui/local_api.py съест исключение и
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
for d in ('ui', 'sync', 'data'):
    hidden += _flat_mods(d)
# корневые модули, которые тоже импортируются плоско/лениво
hidden += ['grading', 'subjects', 'server_control', 'fonts', 'app_paths', '_bootstrap',
           'main_window', 'log']
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
# sqlcipher3 — ШИФРОВАНИЕ локальной копии базы (ui/local_api.py). Модуль самодостаточный:
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
# QtWebEngine — встроенный веб-view онлайн-вкладок (мессенджер/модерация, ui/messenger_web.py).
# Импортируется ЛЕНИВО внутри функции, поэтому PyInstaller его статикой не видит — добавляем
# явно, чтобы хук PySide6 собрал Chromium (QtWebEngineProcess, resources, icudtl, локали).
hidden += ['PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore']
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
# server/app — СЫРЫМИ файлами (не через pyz): ui/local_api.py и server/app/main.py сами
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
    pathex=[ROOT, os.path.join(ROOT, 'ui'), os.path.join(ROOT, 'sync'),
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

# ── Обрезка QtWebEngine под лимит размера exe ─────────────────────────────────────────
# Chromium тянет ~200 МБ сырыми. Убираем то, что конечному пользователю не нужно:
#  • *.debug.pak / *.debug.bin — отладочные ресурсы (~82 МБ);
#  • qtwebengine_devtools_resources — DevTools (F12), в проде не нужны (~10 МБ);
#  • локали WebEngine, кроме ru/en (~38 МБ из 53 языков).
# Сам Qt6WebEngineCore.dll (193 МБ) обязателен — его не трогаем (сжимается в onefile).
def _keep_webengine(dest):
    d = (dest or '').lower().replace('\\', '/')
    if '.debug.' in d:
        return False
    if 'devtools_resources' in d:
        return False
    if 'qtwebengine_locales/' in d:
        name = d.rsplit('/', 1)[-1]
        return name.startswith(('ru', 'en'))
    return True


a.datas = [t for t in a.datas if _keep_webengine(t[0])]
a.binaries = [t for t in a.binaries if _keep_webengine(t[0])]

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
