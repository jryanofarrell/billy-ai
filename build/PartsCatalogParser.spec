# ruff: noqa: F821
# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Parts Catalog Parser desktop app.
#
# Run via scripts/build.py (not directly) — that script installs Playwright
# Chromium with PLAYWRIGHT_BROWSERS_PATH=0 first so the browser lands in
# playwright/driver/package/.local-browsers/ and is picked up below.
from pathlib import Path

import playwright as _pw

_pw_browsers = Path(_pw.__file__).parent / "driver" / "package" / ".local-browsers"

_chromium_datas = []
if _pw_browsers.exists():
    _chromium_datas = [
        (str(d), f"playwright/driver/package/.local-browsers/{d.name}")
        for d in _pw_browsers.iterdir()
        if d.is_dir() and d.name.startswith("chromium")
    ]

a = Analysis(
    ["../src/parts_parser/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=_chromium_datas,
    hiddenimports=[
        "playwright",
        "playwright.sync_api",
        "playwright.async_api",
        "PySide6.QtCore",
        "PySide6.QtWidgets",
        "PySide6.QtGui",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Parts Catalog Parser",
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
    name="PartsCatalogParser",
)
