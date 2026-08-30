import os
from pathlib import Path

from pyinstaller_edition import write_edition_runtime_hook

root = Path(SPECPATH).resolve()
runtime_edition = os.environ.get("PUNTO_VENTA_EDITION", "FERRETERIA")
edition_hook = write_edition_runtime_hook(root, runtime_edition)

a = Analysis(
    [str(root / "pos_app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(edition_hook)],
    excludes=["truper_catalog", "pdfplumber", "bs4", "requests", "pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PuntoDeVenta",
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
    name="PuntoDeVenta",
)
