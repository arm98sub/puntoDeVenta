import os
import sys
from dataclasses import dataclass
from pathlib import Path
from edition import EDITION, resolve_database_path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    @property
    def data_dir(self): return self.root / "data"
    @property
    def database(self): return resolve_database_path(self.root, EDITION.edition)
    @property
    def branding(self): return self.data_dir / "branding"
    @property
    def tickets(self): return self.root / "tickets"
    @property
    def backups(self): return self.root / "backups"
    @property
    def logs(self): return self.root / "logs"


def resolve_app_root(*, frozen=None, executable=None, module_file=None, environ=None):
    environment=os.environ if environ is None else environ
    if environment.get("FERRETERIA_HOME"):return Path(environment["FERRETERIA_HOME"]).expanduser().resolve()
    is_frozen=getattr(sys,"frozen",False) if frozen is None else frozen
    if is_frozen:return Path(executable or sys.executable).resolve().parent
    return Path(module_file or __file__).resolve().parent.parent


PATHS=AppPaths(resolve_app_root())
