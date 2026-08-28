"""Núcleo transaccional del actualizador; no depende de la GUI del POS."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


EXPECTED_TABLES={"productos","movimientos_inventario","ventas","detalle_venta","schema_migrations"}
PERSISTENT_NAMES={"data","tickets","backups","logs"}
CURRENT_SCHEMA=8


@dataclass(frozen=True)
class DatabaseValidation:
    path:Path
    valid:bool
    schema_version:int|None
    message:str


@dataclass(frozen=True)
class Installation:
    path:Path
    version:str
    database:DatabaseValidation
    modified_at:str


@dataclass(frozen=True)
class Package:
    root:Path
    payload:Path
    version:str
    required_schema_min:int
    target_schema:int
    migration_required:bool

    @property
    def schema_version(self):return self.target_schema
    @property
    def requires_migration(self):return self.migration_required


@dataclass(frozen=True)
class UpdateResult:
    installation:Path
    old_version:str
    new_version:str
    backup:Path
    database_hash:str
    log_path:Path


def sha256(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda:source.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()


def load_package(root:Path)->Package:
    root=Path(root).resolve();metadata=root/"version.json";payload=root/"payload"
    if not metadata.is_file():raise ValueError("El paquete no contiene version.json")
    data=json.loads(metadata.read_text(encoding="utf-8"));version=str(data.get("version") or "").strip()
    if not version:raise ValueError("La versión del paquete está vacía")
    if not (payload/"PuntoDeVenta.exe").is_file() or not (payload/"_internal").is_dir():raise ValueError("El paquete de aplicación está incompleto")
    if any(payload.rglob("ferreteria.db")):raise ValueError("El paquete contiene una base de datos prohibida")
    if any((payload/name).exists() for name in PERSISTENT_NAMES):raise ValueError("El payload contiene carpetas de datos de usuario")
    target=int(data.get("target_schema",data.get("schema_version",CURRENT_SCHEMA)))
    required=int(data.get("required_schema_min",target))
    migration=bool(data.get("migration_required",data.get("requires_migration",False)))
    if required>target:raise ValueError("Los metadatos de esquema son inválidos")
    return Package(root,payload,version,required,target,migration)


def default_candidate_paths(environ=None)->list[Path]:
    env=os.environ if environ is None else environ;profile=Path(env.get("USERPROFILE",Path.home()))
    candidates=[Path("C:/PuntoDeVenta"),profile/"Documents"/"PuntoDeVenta",profile/"Desktop"/"PuntoDeVenta"]
    for variable in ("OneDrive","OneDriveCommercial","OneDriveConsumer"):
        if env.get(variable):candidates.extend([Path(env[variable])/"Documents"/"PuntoDeVenta",Path(env[variable])/"Desktop"/"PuntoDeVenta"])
    result=[]
    for path in candidates:
        resolved=path.expanduser()
        if resolved not in result:result.append(resolved)
    return result


def validate_database(path:Path)->DatabaseValidation:
    path=Path(path)
    try:
        if not path.is_file():return DatabaseValidation(path,False,None,"No se encontró data\\ferreteria.db")
        with path.open("rb") as source:
            if source.read(16)!=b"SQLite format 3\x00":return DatabaseValidation(path,False,None,"La cabecera no corresponde a SQLite")
        connection=sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True,timeout=10)
        try:
            integrity=connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity!="ok":return DatabaseValidation(path,False,None,f"Falló integrity_check: {integrity}")
            tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing=EXPECTED_TABLES-tables
            if missing:return DatabaseValidation(path,False,None,"Faltan tablas: "+", ".join(sorted(missing)))
            schema=connection.execute("SELECT coalesce(max(version),0) FROM schema_migrations").fetchone()[0]
            if not 1<=schema<=CURRENT_SCHEMA:return DatabaseValidation(path,False,schema,f"Esquema incompatible: {schema}")
            return DatabaseValidation(path,True,schema,"Encontrada y válida")
        finally:connection.close()
    except Exception as exc:return DatabaseValidation(path,False,None,f"No fue posible validar la base: {exc}")


def read_installed_version(path:Path)->str:
    metadata=Path(path)/"version.json"
    try:return str(json.loads(metadata.read_text(encoding="utf-8")).get("version") or "Desconocida")
    except Exception:return "Desconocida"


def validate_installation(path:Path)->Installation|None:
    path=Path(path).expanduser().resolve()
    if not (path/"PuntoDeVenta.exe").is_file():return None
    database=validate_database(path/"data"/"ferreteria.db")
    modified=datetime.fromtimestamp((path/"PuntoDeVenta.exe").stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return Installation(path,read_installed_version(path),database,modified)


def detect_installations(paths:Iterable[Path]|None=None,environ=None)->list[Installation]:
    found=[]
    for path in paths or default_candidate_paths(environ):
        installation=validate_installation(path)
        if installation and installation.path not in {item.path for item in found}:found.append(installation)
    return found


def version_tuple(value:str):
    try:return tuple(int(part) for part in value.split("."))
    except Exception:return ()


def compare_versions(installed:str,new:str)->int|None:
    left,right=version_tuple(installed),version_tuple(new)
    if not left or not right:return None
    return (left>right)-(left<right)


def pos_is_running()->bool:
    if os.name!="nt":return False
    flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    result=subprocess.run(["tasklist","/FI","IMAGENAME eq PuntoDeVenta.exe","/FO","CSV","/NH"],capture_output=True,text=True,creationflags=flags,check=False)
    return '"PuntoDeVenta.exe"' in result.stdout


def configure_update_log(installation:Path)->tuple[logging.Logger,Path]:
    log_dir=installation/"logs";log_dir.mkdir(parents=True,exist_ok=True);path=log_dir/f"updater_{datetime.now():%Y-%m-%d}.log"
    logger=logging.getLogger(f"pdv_updater.{uuid.uuid4().hex}");logger.setLevel(logging.INFO);logger.propagate=False
    handler=logging.FileHandler(path,encoding="utf-8");handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"));logger.addHandler(handler)
    return logger,path


def create_database_backup(database:Path,backup_dir:Path,version:str)->Path:
    backup_dir.mkdir(parents=True,exist_ok=True);stamp=datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")[:-3];target=backup_dir/f"pre_update_v{version}_{stamp}.db"
    source=sqlite3.connect(f"file:{database.resolve()}?mode=ro",uri=True,timeout=30);destination=sqlite3.connect(target)
    try:source.backup(destination);destination.commit()
    except Exception:
        destination.close();source.close()
        if target.exists():target.unlink()
        raise
    finally:
        try:destination.close()
        except Exception:pass
        try:source.close()
        except Exception:pass
    validation=validate_database(target)
    if not validation.valid:
        target.unlink(missing_ok=True);raise RuntimeError("El respaldo creado no pasó la validación")
    return target


PRESERVED_QUERIES={
    "productos":"SELECT count(*) FROM productos",
    "ventas":"SELECT count(*) FROM ventas",
    "detalles":"SELECT count(*) FROM detalle_venta",
    "movimientos":"SELECT count(*) FROM movimientos_inventario",
    "configuracion":"SELECT count(*) FROM configuracion_negocio",
    "barcodes":"SELECT count(*) FROM productos WHERE codigo_barras IS NOT NULL AND trim(codigo_barras)<>''",
}


def database_counts(database:Path)->dict[str,int]:
    with sqlite3.connect(database) as connection:
        return {name:int(connection.execute(sql).fetchone()[0]) for name,sql in PRESERVED_QUERIES.items()}


def migrate_database(database:Path,current:int,target:int,hook=lambda _stage:None):
    if current==target:return
    if current not in {6,7} or target not in {7,8} or current>=target:raise RuntimeError(f"No existe una migración segura de esquema {current} a {target}")
    connection=sqlite3.connect(database,timeout=30,isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON");connection.execute("BEGIN IMMEDIATE")
        if current==6:
            connection.execute("ALTER TABLE productos ADD COLUMN unidad_granel TEXT CHECK(unidad_granel IS NULL OR unidad_granel IN ('PESO','VOLUMEN'))")
            connection.execute("UPDATE productos SET unidad_granel='PESO' WHERE tipo_venta='GRANEL'")
            connection.execute("ALTER TABLE detalle_venta ADD COLUMN unidad_granel_snapshot TEXT CHECK(unidad_granel_snapshot IS NULL OR unidad_granel_snapshot IN ('PESO','VOLUMEN'))")
            connection.execute("UPDATE detalle_venta SET unidad_granel_snapshot='PESO' WHERE tipo_venta_snapshot='GRANEL'")
            connection.execute("INSERT INTO schema_migrations(version) VALUES(7)");current=7
        if current==7 and target==8:
            connection.execute("ALTER TABLE productos ADD COLUMN precio_variable INTEGER NOT NULL DEFAULT 0 CHECK(precio_variable IN (0,1))")
            connection.execute("INSERT INTO schema_migrations(version) VALUES(8)")
        hook("migration")
        connection.commit()
    except Exception:
        connection.rollback();raise
    finally:connection.close()


def restore_database(database:Path,backup:Path):
    temporary=database.with_name(f".{database.name}.restore_{uuid.uuid4().hex}")
    source=sqlite3.connect(f"file:{backup.resolve()}?mode=ro",uri=True,timeout=30);destination=sqlite3.connect(temporary)
    try:source.backup(destination);destination.commit()
    finally:destination.close();source.close()
    for suffix in ("-wal","-shm"):
        Path(str(database)+suffix).unlink(missing_ok=True)
    os.replace(temporary,database)


def apply_update(package:Package,installation:Installation,*,running_check:Callable[[],bool]=pos_is_running,
                 progress:Callable[[str,int],None]|None=None,failure_hook:Callable[[str],None]|None=None)->UpdateResult:
    notify=progress or (lambda _message,_percent:None);hook=failure_hook or (lambda _stage:None)
    target=installation.path;database=target/"data"/"ferreteria.db";logger,log_path=configure_update_log(target)
    if running_check():raise RuntimeError("PuntoDeVenta está abierto. Ciérrelo e intente nuevamente.")
    current=validate_database(database)
    if not current.valid:raise RuntimeError("No se puede actualizar porque la base de datos no pasó la validación.")
    if not package.required_schema_min<=current.schema_version<=package.target_schema:raise RuntimeError("La versión instalada no es compatible con este paquete")
    migration_needed=current.schema_version!=package.target_schema
    if migration_needed and not package.migration_required:raise RuntimeError("El paquete no autoriza la migración requerida")
    old_hash=sha256(database);before_counts=database_counts(database);logger.info("Inicio: instalada=%s nueva=%s esquema=%s->%s ruta=%s",installation.version,package.version,current.schema_version,package.target_schema,target);logger.info("Conteos antes: %s",before_counts)
    notify("Creando respaldo...",15)
    try:backup=create_database_backup(database,target/"backups"/"manual",package.version);logger.info("Backup creado: %s",backup)
    except Exception as exc:logger.exception("Falló backup");raise RuntimeError("No fue posible crear el respaldo. La actualización fue cancelada.") from exc
    token=uuid.uuid4().hex;stage=target/f".pdv_update_{token}";previous=target/f".pdv_previous_{token}";moved=[];installed=[]
    try:
        notify("Preparando archivos...",35);shutil.copytree(package.payload,stage);shutil.copy2(package.root/"version.json",stage/"version.json");hook("staged")
        if not (stage/"PuntoDeVenta.exe").is_file() or not (stage/"_internal").is_dir():raise RuntimeError("Staging incompleto")
        previous.mkdir()
        notify("Actualizando aplicación...",60)
        for name in ("PuntoDeVenta.exe","_internal","version.json"):
            old=target/name
            if old.exists():shutil.move(str(old),str(previous/name));moved.append(name)
        hook("old_moved")
        for name in ("PuntoDeVenta.exe","_internal","version.json"):
            shutil.move(str(stage/name),str(target/name));installed.append(name);hook(f"installed_{name}")
        if migration_needed:
            notify("Actualizando base de datos...",75);hook("before_migration");migrate_database(database,current.schema_version,package.target_schema,hook)
        notify("Validando...",90)
        if read_installed_version(target)!=package.version:raise RuntimeError("No se pudo confirmar la versión instalada")
        if not (target/"PuntoDeVenta.exe").is_file() or not (target/"_internal").is_dir():raise RuntimeError("La aplicación instalada está incompleta")
        final_db=validate_database(database);after_counts=database_counts(database)
        if not final_db.valid or final_db.schema_version!=package.target_schema:raise RuntimeError("La base migrada no pasó la validación")
        if before_counts!=after_counts:raise RuntimeError("Los conteos de datos cambiaron durante la actualización")
        if not migration_needed and sha256(database)!=old_hash:raise RuntimeError("La base cambió durante la actualización")
        with sqlite3.connect(database) as connection:
            product_columns={row[1] for row in connection.execute("PRAGMA table_info(productos)")};detail_columns={row[1] for row in connection.execute("PRAGMA table_info(detalle_venta)")}
            if "unidad_granel" not in product_columns or "unidad_granel_snapshot" not in detail_columns:raise RuntimeError("Faltan columnas de la migración 7")
        final_hash=sha256(database);logger.info("Validación correcta; archivos=%s; hash_db_antes=%s; hash_db_despues=%s",",".join(installed),old_hash,final_hash);logger.info("Conteos después: %s",after_counts)
        shutil.rmtree(previous,ignore_errors=True);shutil.rmtree(stage,ignore_errors=True);notify("Completado.",100)
        return UpdateResult(target,installation.version,package.version,backup,final_hash,log_path)
    except Exception as exc:
        logger.exception("Error; iniciando rollback")
        try:
            for name in installed:
                value=target/name
                if value.is_dir():shutil.rmtree(value)
                elif value.exists():value.unlink()
            for name in moved:
                old=previous/name
                if old.exists():shutil.move(str(old),str(target/name))
            if sha256(database)!=old_hash:restore_database(database,backup)
            restored=validate_database(database)
            if not restored.valid or restored.schema_version!=current.schema_version or database_counts(database)!=before_counts:raise RuntimeError("No fue posible validar la restauración de la base")
            logger.info("Rollback de aplicación y base completado")
        except Exception:logger.exception("Falló rollback de aplicación/base")
        finally:shutil.rmtree(stage,ignore_errors=True);shutil.rmtree(previous,ignore_errors=True)
        raise RuntimeError("La actualización no pudo completarse. La versión anterior fue restaurada.") from exc


def open_pos(installation:Path)->bool:
    executable=Path(installation)/"PuntoDeVenta.exe"
    if not executable.is_file():return False
    subprocess.Popen([str(executable)],cwd=str(installation),close_fds=True)
    return True
