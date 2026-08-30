"""Identidad de la edición, fijada por configuración de ejecución/build."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Edition(str, Enum):
    FERRETERIA = "FERRETERIA"
    GENERAL = "GENERAL"


@dataclass(frozen=True)
class EditionConfig:
    edition: Edition
    app_name: str
    database_relative_path: Path
    truper_enabled: bool
    auto_recalculate_sale_price_from_cost: bool
    purchases_enabled: bool


EDITION_CONFIGS = {
    Edition.FERRETERIA: EditionConfig(Edition.FERRETERIA, "Ferretería POS", Path("data/ferreteria.db"), True, True, False),
    Edition.GENERAL: EditionConfig(Edition.GENERAL, "PuntoDeVenta General", Path("data/punto_venta.db"), False, False, True),
}


def parse_edition(value: str | Edition | None) -> Edition:
    if isinstance(value, Edition):
        return value
    normalized = (value or Edition.FERRETERIA.value).strip().upper()
    try:
        return Edition(normalized)
    except ValueError as exc:
        raise ValueError(f"Edición no válida: {value!r}") from exc


def get_edition_config(value: str | Edition | None = None, *, environ=None) -> EditionConfig:
    environment = os.environ if environ is None else environ
    selected = value if value is not None else environment.get("PUNTO_VENTA_EDITION")
    return EDITION_CONFIGS[parse_edition(selected)]


def resolve_database_path(root: Path, value: str | Edition | None = None, *, environ=None) -> Path:
    """Resuelve la base sin compartir overrides entre ediciones.

    ``FERRETERIA_DB`` es exclusivamente legacy de FERRETERIA. GENERAL sólo
    admite su override dedicado, por lo que una variable legacy presente en la
    máquina nunca puede redirigir accidentalmente la edición GENERAL.
    """
    environment = os.environ if environ is None else environ
    config = get_edition_config(value, environ=environment)
    override_name = "FERRETERIA_DB" if config.edition is Edition.FERRETERIA else "PUNTO_VENTA_GENERAL_DB"
    override = environment.get(override_name)
    return Path(override).expanduser() if override else Path(root) / config.database_relative_path


EDITION = get_edition_config()
