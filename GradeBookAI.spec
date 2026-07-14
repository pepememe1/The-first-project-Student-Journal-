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
#  • Серверный (host) режим --run-server в этот билд НЕ входит — это отдельная сборка;
#    клиент подключается к готовому серверу (esstu-gradebook.ru).
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
# пакеты
for pkg in ('vector', 'schedule'):
    hidden += collect_submodules(pkg)
# зависимости, которые импортируются лениво/динамически
hidden += ['gostcrypto', 'gostcrypto.gostpbkdf', 'requests', 'cryptography',
           'openpyxl', 'win32crypt']
# python-docx (Word-экспорт журнала/ведомости) — импортируется лениво (data/exports.py).
# Пакет ставится как python-docx, а импортируется как `docx`; ему нужны его шаблоны
# (docx/templates/*.docx), поэтому тянем и submodules, и data-файлы.
hidden += collect_submodules('docx')

datas = []
datas += collect_data_files('docx')   # шаблон default.docx и пр. — иначе Document() падает
for folder in ('emotions', 'emotes', 'vector_assets', 'fonts'):
    if os.path.isdir(os.path.join(ROOT, folder)):
        datas.append((folder, folder))
for f in ('icon.ico', 'icon.png'):
    if os.path.isfile(os.path.join(ROOT, f)):
        datas.append((f, '.'))

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
