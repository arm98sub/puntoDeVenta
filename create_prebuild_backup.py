from pathlib import Path

from ferreteria_core import Database
from ferreteria_core.services import BackupService,validar_respaldo
from ferreteria_core.version import __version__


def main():
    database=Database(Path("data")/"ferreteria.db")
    if database.needs_migration():raise SystemExit("La base real tiene migraciones pendientes; no se inició el build")
    backup=BackupService(database,Path("backups")).crear_pre_build(__version__)
    validation=validar_respaldo(backup)
    print(f"Backup pre-build válido: {backup.resolve()} (migración {validation.schema_version})")


if __name__=="__main__":main()
