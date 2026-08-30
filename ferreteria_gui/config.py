import os
from pathlib import Path
from .paths import PATHS
from edition import EDITION

PROJECT_ROOT=PATHS.root
DATABASE_PATH=PATHS.database
LOG_DIR=Path(os.environ.get("FERRETERIA_LOG_DIR",PATHS.logs))
APP_NAME = EDITION.app_name
APP_EDITION = EDITION.edition
TRUPER_ENABLED = EDITION.truper_enabled
PURCHASES_ENABLED = EDITION.purchases_enabled
PAGE_SIZE = 50
TICKET_ROOT=PATHS.tickets
BRANDING_DIR=PATHS.branding
BACKUP_ROOT=PATHS.backups
