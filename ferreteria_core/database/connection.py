import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from .migrations import MIGRATIONS


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.create_function("NORMALIZE_TEXT", 1, _normalize_text, deterministic=True)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version not in applied:
                    try:
                        connection.executescript(f"BEGIN IMMEDIATE;\n{sql}\nINSERT INTO schema_migrations(version) VALUES ({int(version)});\nCOMMIT;")
                    except Exception:
                        connection.rollback()
                        raise

    def needs_migration(self):
        if not self.path.is_file() or self.path.stat().st_size==0:return False
        connection=sqlite3.connect(self.path)
        try:
            exists=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
            if not exists:return False
            current=connection.execute("SELECT coalesce(max(version),0) FROM schema_migrations").fetchone()[0]
            return current<MIGRATIONS[-1][0]
        finally:connection.close()

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _normalize_text(value):
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join("".join(char for char in normalized if not unicodedata.combining(char)).split())


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self,exc_type,exc_value,traceback):
        try:return super().__exit__(exc_type,exc_value,traceback)
        finally:self.close()
