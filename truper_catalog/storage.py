from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .models import Product


FIELDS = ("codigo", "codigo_barras", "clave", "descripcion", "marca", "categoria")


def save_csv(products: Iterable[Product], destination: str | Path) -> int:
    """Guarda productos únicos en CSV UTF-8 (con BOM para Excel en español)."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    unique: dict[str, Product] = {}
    for product in products:
        unique.setdefault(product.codigo.strip(), product)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for product in unique.values():
            writer.writerow({field: getattr(product, field) for field in FIELDS})
    return len(unique)


def load_csv(source: str | Path) -> list[Product]:
    path = Path(source)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        products = []
        for row in csv.DictReader(handle):
            row.setdefault("codigo_barras", "")
            products.append(Product(**row))
        return products
