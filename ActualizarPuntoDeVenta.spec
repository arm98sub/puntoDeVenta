from pathlib import Path

root=Path(SPECPATH).resolve()
a=Analysis([str(root/"updater_app.py")],pathex=[str(root)],binaries=[],datas=[],hiddenimports=[],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=["reportlab","openpyxl","PIL","truper_catalog","pytest"],noarchive=False,optimize=1)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name="ActualizarPuntoDeVenta",debug=False,bootloader_ignore_signals=False,strip=False,upx=True,console=False,disable_windowed_traceback=False,argv_emulation=False,target_arch=None,codesign_identity=None,entitlements_file=None,contents_directory="_updater_internal")
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=True,upx_exclude=[],name="ActualizarPuntoDeVenta")
