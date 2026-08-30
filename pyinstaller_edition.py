"""Genera el runtime hook que fija la edición de un build PyInstaller."""
from pathlib import Path


VALID_EDITIONS = {"FERRETERIA", "GENERAL"}


def write_edition_runtime_hook(root: Path, edition: str) -> Path:
    selected=(edition or "").strip().upper()
    if selected not in VALID_EDITIONS:
        raise ValueError(f"Edición de build no válida: {edition!r}")
    target=Path(root)/"build"/f"runtime_edition_{selected.lower()}.py"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(
        "# Generado por PuntoDeVenta.spec; se ejecuta antes de importar la aplicación.\n"
        "import os\n"
        f"os.environ['PUNTO_VENTA_EDITION'] = {selected!r}\n",
        encoding="utf-8",
    )
    return target
