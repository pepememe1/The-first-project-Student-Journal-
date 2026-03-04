# -*- mode: python ; coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════
#  GradeBookAI.spec — файл сборки PyInstaller
#
#  Как использовать:
#    pyinstaller GradeBookAI.spec
#
#  Или с нуля (эквивалентная команда):
#    pyinstaller --onefile --windowed --icon=icon.ico
#                --name=GradeBookAI
#                --add-data "icon.ico;."
#                --add-data "icon.png;."
#                main.py
#
#  ВАЖНО: subjects.json, secure_data.enc, vsgutu_grades.db
#  НЕ включаются в exe — они создаются/хранятся рядом с exe.
# ═══════════════════════════════════════════════════════════════

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Иконка встраивается в exe (для отображения в заголовке окна)
        ('icon.ico', '.'),
        ('icon.png', '.'),
    ],
    hiddenimports=[
        # PySide6
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtSvg',
        # Криптография
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.backends.openssl',
        # Excel
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'openpyxl.writer.excel',
        'openpyxl.reader.excel',
        # HTTP запросы (ИИ помощник)
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests.models',
        'requests.sessions',
        'urllib3',
        'urllib3.util',
        'urllib3.util.retry',
        'certifi',
        'charset_normalizer',
        'idna',
        # Стандартные
        'sqlite3',
        'zipfile',
        'json',
        'uuid',
        'hashlib',
        'secrets',
        'tempfile',
        'shutil',
        # Модули проекта
        'GUI',
        'admin_panel',
        'core',
        'security',
        'subjects',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Исключаем тяжёлые неиспользуемые пакеты
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'torch',
        'tensorflow',
        'pytest',
        'IPython',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GradeBookAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # UPX сжатие — уменьшает размер exe (~30%)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # Без консольного окна (windowed)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',    # Иконка exe-файла
    version_file=None,
)
