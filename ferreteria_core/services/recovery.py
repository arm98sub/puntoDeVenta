import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ferreteria_core.database.migrations import MIGRATIONS


REQUIRED_TABLES={"productos","movimientos_inventario","ventas","detalle_venta","configuracion_negocio","schema_migrations"}


@dataclass(frozen=True)
class BackupValidation:
    path:Path
    schema_version:int
    tables:frozenset[str]


def validar_respaldo(path):
    path=Path(path)
    if not path.is_file():raise ValueError("El archivo de respaldo no existe")
    try:
        with path.open("rb") as stream:
            if stream.read(16)!=b"SQLite format 3\x00":raise ValueError("El archivo no es una base SQLite válida")
        connection=sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro",uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ValueError("El respaldo no supera integrity_check")
            tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing=REQUIRED_TABLES-tables
            if missing:raise ValueError(f"El respaldo no contiene el esquema esperado: {', '.join(sorted(missing))}")
            versions=[row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
            latest=MIGRATIONS[-1][0]
            known={version for version,_ in MIGRATIONS}
            if not versions or any(version not in known for version in versions) or versions!=list(range(1,versions[-1]+1)) or versions[-1]>latest:
                raise ValueError(f"Versión de esquema incompatible; máximo admitido {latest}")
            return BackupValidation(path,versions[-1],frozenset(tables))
        finally:connection.close()
    except sqlite3.DatabaseError as exc:raise ValueError("El archivo SQLite está corrupto o no puede leerse") from exc


class BackupService:
    def __init__(self,database,root="backups",automatic_retention=30):
        self.database=database;self.root=Path(root);self.manual_dir=self.root/"manual";self.automatic_dir=self.root/"automatic";self.automatic_retention=automatic_retention
    def crear_manual(self):return self._create(self.manual_dir,"ferreteria")
    def crear_pre_migracion(self):return self._create(self.manual_dir,"pre_migration")
    def crear_pre_build(self,version):return self._create(self.manual_dir,f"pre_build_v{version}")
    def crear_automatico(self):
        path=self._create(self.automatic_dir,"ferreteria_auto");self._retain();return path
    def restaurar(self,backup_path):
        source=validar_respaldo(backup_path);self.root.mkdir(parents=True,exist_ok=True);target=self.database.path;target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(f".{target.name}.restore.tmp")
        temporary.unlink(missing_ok=True)
        _sqlite_backup(source.path,temporary);validar_respaldo(temporary)
        safety=self._create(self.manual_dir,"pre_restore")
        try:
            _sqlite_backup(temporary,target)
            self.database.migrate()
            validar_respaldo(target)
            return safety
        except Exception:
            if safety.exists():
                _sqlite_backup(safety,target)
            raise
        finally:
            temporary.unlink(missing_ok=True)
    def _create(self,directory,prefix):
        directory.mkdir(parents=True,exist_ok=True);stamp=datetime.now().strftime("%Y-%m-%d_%H%M%S_%f");path=directory/f"{prefix}_{stamp}.db";_sqlite_backup(self.database.path,path);validar_respaldo(path);return path
    def _retain(self):
        files=sorted(self.automatic_dir.glob("ferreteria_auto_*.db"),key=lambda p:p.stat().st_mtime,reverse=True)
        for old in files[self.automatic_retention:]:old.unlink()


def _sqlite_backup(source_path,target_path):
    source=sqlite3.connect(source_path);destination=sqlite3.connect(target_path)
    try:source.backup(destination)
    finally:destination.close();source.close()
