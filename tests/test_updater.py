import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ferreteria_core import Database
from ferreteria_core.services import ProductService,SalesService
import updater_core
from updater_app import UpdaterWindow
from updater_core import (apply_update,compare_versions,create_database_backup,default_candidate_paths,
                          detect_installations,load_package,open_pos,sha256,validate_database,
                          validate_installation)


@pytest.fixture(scope="module")
def app():return QApplication.instance() or QApplication([])


def make_install(root:Path,version="1.1.2"):
    root.mkdir(parents=True);(root/"PuntoDeVenta.exe").write_bytes(b"OLD-EXE");(root/"_internal").mkdir();(root/"_internal"/"old.dll").write_bytes(b"OLD")
    (root/"version.json").write_text(json.dumps({"version":version}),encoding="utf-8")
    db=Database(root/"data"/"ferreteria.db");db.migrate();product=ProductService(db).crear_producto_externo("7500000060001","Temporal",Decimal("10"),3);SalesService(db).crear_venta([{"producto_id":product.id,"cantidad":1}],"TARJETA")
    for directory,file in (("data/branding","logo.txt"),("tickets","ticket.txt"),("logs","existing.log"),("backups/manual","old.db")):
        path=root/directory;path.mkdir(parents=True,exist_ok=True);(path/file).write_text("PRESERVAR",encoding="utf-8")
    return validate_installation(root)


def make_package(root:Path,version="1.1.4",*,required=9,target=9,migration=False):
    root.mkdir(parents=True);payload=root/"payload";payload.mkdir();(payload/"PuntoDeVenta.exe").write_bytes(b"NEW-EXE");(payload/"_internal").mkdir();(payload/"_internal"/"new.dll").write_bytes(b"NEW")
    (root/"version.json").write_text(json.dumps({"version":version,"required_schema_min":required,"target_schema":target,"migration_required":migration}),encoding="utf-8")
    return load_package(root)


def make_v111_install(root:Path):
    from ferreteria_core.database.migrations import MIGRATIONS
    root.mkdir(parents=True);(root/"PuntoDeVenta.exe").write_bytes(b"OLD-EXE");(root/"_internal").mkdir();(root/"_internal"/"old.dll").write_bytes(b"OLD");(root/"version.json").write_text(json.dumps({"version":"1.1.1"}),encoding="utf-8")
    database=root/"data"/"ferreteria.db";database.parent.mkdir();connection=__import__("sqlite3").connect(database)
    connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for version,sql in MIGRATIONS[:6]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    unit=connection.execute("INSERT INTO productos(codigo_barras,descripcion,precio_venta,existencia,es_truper,datos_completos,requiere_revision,tipo_venta) VALUES('7501','Martillo',1000,3,0,1,0,'UNIDAD')").lastrowid
    bulk=connection.execute("INSERT INTO productos(codigo_barras,descripcion,precio_venta,existencia,es_truper,datos_completos,requiere_revision,tipo_venta,existencia_granel_mg) VALUES('7502','Clavo',8000,0,0,1,0,'GRANEL',500000)").lastrowid
    connection.execute("INSERT INTO ventas(id,folio,fecha_hora,subtotal_centavos,descuento_centavos,total_centavos,metodo_pago,estado) VALUES(1,'V-000001',CURRENT_TIMESTAMP,1000,0,1000,'TARJETA','COMPLETADA')")
    connection.execute("INSERT INTO detalle_venta(venta_id,producto_id,descripcion_snapshot,cantidad,precio_unitario_centavos,subtotal_centavos,tipo_venta_snapshot) VALUES(1,?,'Martillo',1,1000,1000,'UNIDAD')",(unit,))
    connection.execute("INSERT INTO movimientos_inventario(producto_id,fecha_hora,tipo,cantidad,existencia_anterior,existencia_nueva) VALUES(?,CURRENT_TIMESTAMP,'VENTA',-1,4,3)",(unit,));connection.execute("UPDATE configuracion_negocio SET nombre_negocio='Prueba' WHERE id=1");connection.commit();connection.close()
    for directory,file in (("data/branding","logo.txt"),("tickets","ticket.txt"),("logs","existing.log"),("backups/manual","old.db")):
        path=root/directory;path.mkdir(parents=True,exist_ok=True);(path/file).write_text("PRESERVAR",encoding="utf-8")
    return validate_installation(root),bulk


def make_v113_install(root:Path):
    from ferreteria_core.database.migrations import MIGRATIONS
    import sqlite3
    root.mkdir(parents=True);(root/"PuntoDeVenta.exe").write_bytes(b"V113");(root/"_internal").mkdir();(root/"_internal"/"old.dll").write_bytes(b"OLD");(root/"version.json").write_text(json.dumps({"version":"1.1.3"}),encoding="utf-8")
    database=root/"data/ferreteria.db";database.parent.mkdir();connection=sqlite3.connect(database);connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for version,sql in MIGRATIONS[:7]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    connection.execute("INSERT INTO productos(descripcion,precio_venta,existencia,es_truper,datos_completos,requiere_revision) VALUES('Conservado',5100,2,0,1,0)");connection.commit();connection.close()
    return validate_installation(root)


def test_actualiza_v113_schema7_a_v114_schema8(tmp_path):
    install=make_v113_install(tmp_path/"install");package=make_package(tmp_path/"package",required=7,target=8,migration=True);result=apply_update(package,install,running_check=lambda:False)
    assert validate_database(install.path/"data/ferreteria.db").schema_version==8 and read_version(install.path)=="1.1.4"
    with __import__("sqlite3").connect(install.path/"data/ferreteria.db") as connection:assert connection.execute("SELECT descripcion,precio_venta,existencia,precio_variable FROM productos").fetchone()==("Conservado",5100,2,0)


def test_fallo_migracion_v114_restaura_db_y_binarios(tmp_path):
    install=make_v113_install(tmp_path/"install");database=install.path/"data/ferreteria.db";before=sha256(database);package=make_package(tmp_path/"package",required=7,target=8,migration=True)
    def fail(stage):
        if stage=="migration":raise RuntimeError("fallo migración")
    with pytest.raises(RuntimeError,match="restaurada"):apply_update(package,install,running_check=lambda:False,failure_hook=fail)
    assert sha256(database)==before and validate_database(database).schema_version==7 and (install.path/"PuntoDeVenta.exe").read_bytes()==b"V113"


def test_rutas_automaticas():
    paths=default_candidate_paths({"USERPROFILE":"C:/Users/Test","OneDrive":"C:/Users/Test/OneDrive"})
    assert Path("C:/PuntoDeVenta") in paths and Path("C:/Users/Test/Documents/PuntoDeVenta") in paths and Path("C:/Users/Test/Desktop/PuntoDeVenta") in paths


def test_detecta_candidato_simulado(tmp_path):
    install=make_install(tmp_path/"C"/"PuntoDeVenta");found=detect_installations([install.path])
    assert len(found)==1 and found[0].path==install.path


def test_detecta_documents(tmp_path):
    install=make_install(tmp_path/"User"/"Documents"/"PuntoDeVenta")
    assert detect_installations([install.path])[0].version=="1.1.2"


def test_ninguna_y_multiples_instalaciones(tmp_path):
    assert detect_installations([tmp_path/"no"] )==[]
    one=make_install(tmp_path/"one");two=make_install(tmp_path/"two")
    assert len(detect_installations([one.path,two.path]))==2


def test_seleccion_manual_valida_carpeta(tmp_path):
    install=make_install(tmp_path/"manual");assert validate_installation(install.path).database.valid
    assert validate_installation(tmp_path/"incorrecta") is None


def test_base_valida_y_corrupta(tmp_path):
    install=make_install(tmp_path/"valid");assert validate_database(install.path/"data/ferreteria.db").valid
    corrupt=tmp_path/"bad.db";corrupt.write_bytes(b"not sqlite");assert not validate_database(corrupt).valid


@pytest.mark.parametrize(("installed","new","expected"),[("1.1.3","1.1.4",-1),("1.1.4","1.1.4",0),("1.2.0","1.1.4",1),("Desconocida","1.1.4",None)])
def test_comparacion_versiones(installed,new,expected):assert compare_versions(installed,new)==expected


def test_paquete_rechaza_db(tmp_path):
    package=make_package(tmp_path/"package");(package.payload/"ferreteria.db").write_bytes(b"x")
    with pytest.raises(ValueError,match="base de datos"):load_package(package.root)


def test_pos_abierto_detiene_sin_copiar(tmp_path):
    install=make_install(tmp_path/"install");package=make_package(tmp_path/"package")
    with pytest.raises(RuntimeError,match="abierto"):apply_update(package,install,running_check=lambda:True)
    assert (install.path/"PuntoDeVenta.exe").read_bytes()==b"OLD-EXE"


def test_backup_sqlite_seguro(tmp_path):
    install=make_install(tmp_path/"install");database=install.path/"data/ferreteria.db";before=sha256(database)
    backup=create_database_backup(database,install.path/"backups/manual","1.1.4")
    assert backup.is_file() and validate_database(backup).valid and sha256(database)==before


def test_backup_falla_y_no_actualiza(tmp_path,monkeypatch):
    install=make_install(tmp_path/"install");package=make_package(tmp_path/"package")
    monkeypatch.setattr(updater_core,"create_database_backup",lambda *_args,**_kwargs:(_ for _ in ()).throw(OSError("sin espacio")))
    with pytest.raises(RuntimeError,match="respaldo"):apply_update(package,install,running_check=lambda:False)
    assert (install.path/"PuntoDeVenta.exe").read_bytes()==b"OLD-EXE"


def test_actualizacion_end_to_end_preserva_todo(tmp_path):
    install=make_install(tmp_path/"install");package=make_package(tmp_path/"package");database=install.path/"data/ferreteria.db";before=sha256(database)
    with Database(database).connect() as connection:counts=tuple(connection.execute("SELECT count(*) FROM "+table).fetchone()[0] for table in ("productos","ventas"))
    result=apply_update(package,install,running_check=lambda:False)
    assert (install.path/"PuntoDeVenta.exe").read_bytes()==b"NEW-EXE" and (install.path/"_internal/new.dll").is_file()
    assert sha256(database)==before==result.database_hash and read_version(install.path)=="1.1.4"
    with Database(database).connect() as connection:assert tuple(connection.execute("SELECT count(*) FROM "+table).fetchone()[0] for table in ("productos","ventas"))==counts
    for path in ("data/branding/logo.txt","tickets/ticket.txt","logs/existing.log","backups/manual/old.db"):assert (install.path/path).read_text(encoding="utf-8")=="PRESERVAR"
    assert result.backup.is_file() and result.log_path.is_file()


def read_version(path):return json.loads((path/"version.json").read_text(encoding="utf-8"))["version"]


def test_fallo_copia_hace_rollback(tmp_path):
    install=make_install(tmp_path/"install");package=make_package(tmp_path/"package");before=sha256(install.path/"data/ferreteria.db")
    def fail(stage):
        if stage=="installed_PuntoDeVenta.exe":raise OSError("fallo simulado")
    with pytest.raises(RuntimeError,match="restaurada"):apply_update(package,install,running_check=lambda:False,failure_hook=fail)
    assert (install.path/"PuntoDeVenta.exe").read_bytes()==b"OLD-EXE" and (install.path/"_internal/old.dll").is_file()
    assert read_version(install.path)=="1.1.2" and sha256(install.path/"data/ferreteria.db")==before


def test_validacion_post_hash_y_log(tmp_path):
    install=make_install(tmp_path/"install");package=make_package(tmp_path/"package");messages=[]
    result=apply_update(package,install,running_check=lambda:False,progress=lambda text,value:messages.append((text,value)))
    assert messages[-1]==("Completado.",100) and "hash_db" in result.log_path.read_text(encoding="utf-8")


def test_gui_muestra_multiples_y_base_valida(app,tmp_path):
    package=make_package(tmp_path/"package");one=make_install(tmp_path/"one");two=make_install(tmp_path/"two")
    window=UpdaterWindow(package.root,[one.path,two.path]);window.show();app.processEvents()
    assert window.selector.count()==2 and "varias" in window.message.text() and "válida" in window.database.text();window.close()


def test_gui_sin_instalacion_permite_buscar(app,tmp_path):
    package=make_package(tmp_path/"package");window=UpdaterWindow(package.root,[tmp_path/"none"]);window.show();app.processEvents()
    assert not window.selector.isVisible() and window.browse.isEnabled() and not window.update.isEnabled();window.close()


def test_abrir_pos_usa_ejecutable(tmp_path,monkeypatch):
    install=make_install(tmp_path/"install");calls=[]
    monkeypatch.setattr(updater_core.subprocess,"Popen",lambda args,**kwargs:calls.append((args,kwargs)))
    assert open_pos(install.path) and calls[0][0][0].endswith("PuntoDeVenta.exe")


def test_actualizacion_6_a_7_preserva_datos_y_archivos(tmp_path):
    install,bulk_id=make_v111_install(tmp_path/"install");package=make_package(tmp_path/"package",version="1.1.2",required=6,target=7,migration=True);database=install.path/"data/ferreteria.db"
    result=apply_update(package,install,running_check=lambda:False)
    with __import__("sqlite3").connect(database) as connection:
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]==7
        assert connection.execute("SELECT unidad_granel FROM productos WHERE id=?",(bulk_id,)).fetchone()[0]=="PESO"
        assert connection.execute("SELECT count(*) FROM ventas").fetchone()[0]==1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    assert result.backup.name.startswith("pre_update_v1.1.2_")
    for path in ("data/branding/logo.txt","tickets/ticket.txt","logs/existing.log","backups/manual/old.db"):assert (install.path/path).read_text(encoding="utf-8")=="PRESERVAR"


def test_fallo_migracion_restaura_db_y_binarios(tmp_path):
    install,_=make_v111_install(tmp_path/"install");package=make_package(tmp_path/"package",version="1.1.2",required=6,target=7,migration=True);database=install.path/"data/ferreteria.db";before=sha256(database)
    def fail(stage):
        if stage=="migration":raise OSError("fallo de migración simulado")
    with pytest.raises(RuntimeError,match="restaurada"):apply_update(package,install,running_check=lambda:False,failure_hook=fail)
    assert (install.path/"PuntoDeVenta.exe").read_bytes()==b"OLD-EXE" and (install.path/"_internal/old.dll").is_file()
    assert read_version(install.path)=="1.1.1" and sha256(database)==before and validate_database(database).schema_version==6
