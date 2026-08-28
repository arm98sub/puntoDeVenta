from ferreteria_core import Database
from ferreteria_core.services import BackupService,validar_respaldo
from ferreteria_core.version import __version__
from edition import EDITION


def main():
    database=Database(EDITION.database_relative_path)
    if database.needs_migration():raise SystemExit("La base real tiene migraciones pendientes; no se inició el build")
    backup=BackupService(database,EDITION.database_relative_path.parent.parent/"backups").crear_pre_build(__version__)
    validation=validar_respaldo(backup)
    print(f"Backup pre-build válido: {backup.resolve()} (migración {validation.schema_version})")


if __name__=="__main__":main()
