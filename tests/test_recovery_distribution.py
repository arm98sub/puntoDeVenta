import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from ferreteria_core import Database
from ferreteria_core.services import BackupService,BusinessConfigService,ProductService,SalesService,validar_respaldo
from ferreteria_core.version import __version__
from ferreteria_gui.paths import resolve_app_root


@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"data"/"ferreteria.db");value.migrate();p=ProductService(value).crear_producto_externo("7500000000001","Producto",Decimal("10"),5);SalesService(value).crear_venta([{"producto_id":p.id,"cantidad":1}],"TARJETA");BusinessConfigService(value,tmp_path/"data"/"branding").guardar(nombre_negocio="Negocio respaldado");return value


def test_resolucion_ruta_desarrollo(tmp_path):
    module=tmp_path/"project"/"ferreteria_gui"/"paths.py"
    assert resolve_app_root(frozen=False,module_file=module,environ={})==tmp_path/"project"


def test_resolucion_ruta_empaquetada_y_override(tmp_path):
    exe=tmp_path/"portable"/"PuntoDeVenta.exe"
    assert resolve_app_root(frozen=True,executable=exe,environ={})==exe.parent
    assert resolve_app_root(frozen=True,executable=exe,environ={"FERRETERIA_HOME":str(tmp_path/"otra")})==tmp_path/"otra"


def test_version():assert __version__=="1.1.4"


def test_paquete_actualizacion_preserva_datos_de_usuario():
    root=Path(__file__).resolve().parents[1]
    build=(root/"build_update_v111.ps1").read_text(encoding="utf-8")
    updater=(root/"actualizar_v1.1.1.ps1").read_text(encoding="utf-8")
    assert "--confirm-real-data" not in build and "prepare_distribution_data" not in build
    assert "PuntoDeVenta.exe" in updater and "_internal" in updater
    assert "Copy-Item -LiteralPath $Database -Destination $BackupPath" in updater
    assert "data\\branding" not in updater and "tickets\\" not in updater


def test_crear_y_validar_backup_completo(db,tmp_path):
    service=BackupService(db,tmp_path/"backups");path=service.crear_manual();validation=validar_respaldo(path)
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT count(*) FROM productos").fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM ventas").fetchone()[0]==1
        assert c.execute("SELECT sum(existencia) FROM productos").fetchone()[0]==4
        assert c.execute("SELECT nombre_negocio FROM configuracion_negocio").fetchone()[0]=="Negocio respaldado"
    assert validation.schema_version==8 and path.parent.name=="manual"


def test_restaurar_recupera_datos_y_crea_pre_restore(db,tmp_path):
    service=BackupService(db,tmp_path/"backups");backup=service.crear_manual();ProductService(db).crear_producto_externo("7500000000002","Extra",Decimal("5"),1)
    safety=service.restaurar(backup)
    with db.connect() as c:assert c.execute("SELECT count(*) FROM productos").fetchone()[0]==1 and c.execute("SELECT count(*) FROM ventas").fetchone()[0]==1
    assert safety.exists() and safety.name.startswith("pre_restore_")


def test_archivo_corrupto_rechazado(tmp_path):
    path=tmp_path/"bad.db";path.write_bytes(b"no sqlite")
    with pytest.raises(ValueError):validar_respaldo(path)


def test_sqlite_esquema_incorrecto_rechazado(tmp_path):
    path=tmp_path/"wrong.db"
    with sqlite3.connect(path) as c:c.execute("CREATE TABLE otra(id INTEGER)")
    with pytest.raises(ValueError,match="esquema esperado"):validar_respaldo(path)


def test_fallo_restore_conserva_original(db,tmp_path,monkeypatch):
    import ferreteria_core.services.recovery as recovery
    service=BackupService(db,tmp_path/"backups");backup=service.crear_manual();ProductService(db).crear_producto_externo("7500000000002","Actual",Decimal("5"),1);real_backup=recovery._sqlite_backup;calls=[]
    def flaky(source,target):
        calls.append(1)
        if len(calls)==3:raise OSError("fallo simulado")
        return real_backup(source,target)
    monkeypatch.setattr(recovery,"_sqlite_backup",flaky)
    with pytest.raises(OSError):service.restaurar(backup)
    with db.connect() as c:assert c.execute("SELECT count(*) FROM productos").fetchone()[0]==2


def test_backup_automatico_retencion(db,tmp_path):
    service=BackupService(db,tmp_path/"backups",automatic_retention=2)
    for _ in range(4):service.crear_automatico()
    assert len(list(service.automatic_dir.glob("*.db")))==2 and not list(service.manual_dir.glob("*.db"))
