import sqlite3
from datetime import datetime
from pathlib import Path


def respaldar_base(database, destination_dir="backups") -> Path:
    target_dir = Path(destination_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ferreteria_{datetime.now():%Y-%m-%d_%H%M%S}.db"
    source = database.connect()
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target
