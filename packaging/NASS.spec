# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the NASS desktop application.

Build from the repository root:

    pyinstaller packaging/NASS.spec --noconfirm

All inputs are resolved relative to the repository root, so the command works
regardless of the current working directory.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

VERSION = "1.0.1"
APP_NAME = f"NASS_v{VERSION}"

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "backend"), "backend"),
    (str(ROOT / "database" / "seed.sqlite3"), "database"),
    (str(ROOT / "desktop_app" / "assets"), "assets"),
]
binaries = []
hiddenimports = ["rest_framework"]

pyqt = collect_all("PyQt5")
datas += pyqt[0]
binaries += pyqt[1]
hiddenimports += pyqt[2]

a = Analysis(
    [str(ROOT / "desktop_app" / "main.py")],
    pathex=[str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
