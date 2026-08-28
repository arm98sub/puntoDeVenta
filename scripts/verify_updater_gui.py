"""Captura visual del actualizador usando sólo instalaciones temporales."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from ferreteria_core import Database
from updater_app import UpdaterWindow


def installation(root,version):
    root.mkdir();(root/"PuntoDeVenta.exe").write_bytes(b"old");(root/"version.json").write_text(json.dumps({"version":version}),encoding="utf-8");Database(root/"data/ferreteria.db").migrate();return root


def main(output="tmp/updater_visual"):
    target=Path(output);target.mkdir(parents=True,exist_ok=True);app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="pdv-updater-") as directory:
        root=Path(directory);package=root/"package";payload=package/"payload";payload.mkdir(parents=True);(payload/"PuntoDeVenta.exe").write_bytes(b"new");(payload/"_internal").mkdir();(package/"version.json").write_text(json.dumps({"version":"1.1.1","schema_version":6,"requires_migration":False}),encoding="utf-8")
        one=installation(root/"install-one","1.1.0");two=installation(root/"install-two","1.0.0")
        window=UpdaterWindow(package,[one,two]);window.show();app.processEvents();window.grab().save(str(target/"actualizador_varias_instalaciones.png"));window.close()
        empty=UpdaterWindow(package,[root/"none"]);empty.show();app.processEvents();empty.grab().save(str(target/"actualizador_sin_instalacion.png"));empty.close()
    print(target.resolve())


if __name__=="__main__":main()
