from PyInstaller.utils.hooks import collect_all


playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all(
    "playwright"
)

# NOTE: Browser binaries are injected by scripts/build.py post-install, not by this spec.
a = Analysis(
    ["../src/parts_parser/__main__.py"],
    pathex=[],
    binaries=playwright_binaries,
    datas=playwright_datas,
    hiddenimports=playwright_hiddenimports,
    excludes=["tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Parts Catalog Parser",
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="PartsCatalogParser",
)
