import os
from pathlib import Path
from .paths import PATHS

PROJECT_ROOT=PATHS.root
DATABASE_PATH=Path(os.environ.get("FERRETERIA_DB",PATHS.database))
LOG_DIR=Path(os.environ.get("FERRETERIA_LOG_DIR",PATHS.logs))
APP_NAME = "Ferretería POS"
PAGE_SIZE = 50
TICKET_ROOT=PATHS.tickets
BRANDING_DIR=PATHS.branding
BACKUP_ROOT=PATHS.backups
