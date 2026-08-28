from __future__ import annotations

import re
from dataclasses import asdict
from decimal import Decimal
from typing import Mapping

from .pdf_catalog import PdfProduct


def valid_key(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)*", value)) and any(ch.isalpha() for ch in value)


def pdf_product_to_json(product: PdfProduct) -> dict:
    row = asdict(product)
    for field in ("precio_catalogo_mayoreo", "precio_catalogo_medio_mayoreo", "precio_catalogo_publico"):
        row[field] = None if row[field] is None else str(row[field])
    return row


def pdf_product_from_json(row: Mapping) -> PdfProduct:
    data = dict(row)
    for field in ("precio_catalogo_mayoreo", "precio_catalogo_medio_mayoreo", "precio_catalogo_publico"):
        data[field] = None if data.get(field) in {None, ""} else Decimal(str(data[field]))
    return PdfProduct(**data)


def choose_pdf_product(existing: PdfProduct | None, candidate: PdfProduct) -> PdfProduct:
    if existing is None:
        return candidate
    rank = {"alta": 3, "media": 2, "baja": 1}
    score = lambda p: (rank.get(p.confianza_extraccion, 0), bool(p.precio_catalogo_publico), bool(p.descripcion), valid_key(p.clave))
    return candidate if score(candidate) > score(existing) else existing


def merge_master_row(master_row: Mapping[str, str], pdf: PdfProduct | None) -> tuple[dict, list[str]]:
    code = master_row["codigo_truper"].strip()
    prior_key = master_row.get("clave", "").strip()
    prior_description = master_row.get("descripcion", "").strip()
    reasons: list[str] = []
    pdf_key = pdf.clave.strip() if pdf else ""
    if pdf and prior_key and pdf_key and prior_key.upper() != pdf_key.upper():
        reasons.append("discrepancia_clave")
    if pdf and prior_description and pdf.descripcion and prior_description.casefold() != pdf.descripcion.casefold():
        reasons.append("discrepancia_descripcion")
    accepted_key = pdf_key if pdf and valid_key(pdf_key) and pdf.clave_confianza == "ALTA" else ""
    key = prior_key or accepted_key
    description = prior_description or (pdf.descripcion if pdf and pdf.confianza_extraccion in {"alta", "media"} else "")
    public_price = pdf.precio_catalogo_publico if pdf else None
    if pdf and pdf.requiere_revision:
        reasons.append("extraccion_ambigua")
    if pdf and not valid_key(pdf_key):
        reasons.append("clave_ambigua")
    if pdf and not pdf.descripcion and not prior_description:
        reasons.append("descripcion_ambigua")
    if pdf and public_price is None:
        reasons.append("precio_no_recuperado")
    prior_complete = master_row.get("datos_completos", "").strip().lower() in {"true", "1", "si", "sí"}
    priority_complete = bool(key and description and public_price is not None)
    confidence = pdf.confianza_extraccion if pdf else "baja"
    requires_review = bool(reasons) or pdf is None
    if pdf is None:
        reasons.append("no_encontrado_en_pdf")
    price_text = "" if public_price is None else format(public_price, "f")
    row = {
        "codigo_truper": code,
        "codigo_barras": "",
        "clave": key,
        "descripcion": description,
        "descripcion_familia": pdf.descripcion_familia if pdf else "",
        "marca": master_row.get("marca", "").strip() or (pdf.marca if pdf else ""),
        "categoria": master_row.get("categoria", "").strip(),
        "presentacion": pdf.presentacion if pdf else "",
        "precio_catalogo_mayoreo": "" if not pdf or pdf.precio_catalogo_mayoreo is None else format(pdf.precio_catalogo_mayoreo, "f"),
        "precio_catalogo_medio_mayoreo": "" if not pdf or pdf.precio_catalogo_medio_mayoreo is None else format(pdf.precio_catalogo_medio_mayoreo, "f"),
        "precio_catalogo_publico": price_text,
        "precio_venta": price_text,
        "existencia": "",
        "datos_completos": str(prior_complete or priority_complete),
        "confianza_extraccion": confidence,
        "requiere_revision": str(requires_review),
        "pagina_catalogo": "" if not pdf or pdf.pagina_catalogo is None else str(pdf.pagina_catalogo),
        "encontrado_en_pdf": str(pdf is not None),
    }
    return row, sorted(set(reasons))
