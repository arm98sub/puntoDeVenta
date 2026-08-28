from __future__ import annotations

import csv
import difflib
import json
import re
import time
import unicodedata
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from truper_catalog.pdf_catalog import extract_products_from_words, extract_products_v2, load_master_catalog
from truper_catalog.pdf_fonts import build_page_font_maps


PAGES = tuple(round(20 + index * (600 - 20) / 71) for index in range(72))


def normalize_description(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return re.sub(r" (?:truper expert|truper|pretul|volteck|foset|fiero|hermex|klintek)$", "", value)


def metrics(rows, prefix):
    count = len(rows)
    exact_key = sum(row[f"{prefix}_clave_exacta"] == "true" for row in rows)
    exact_desc = sum(row[f"{prefix}_descripcion_exacta"] == "true" for row in rows)
    norm_desc = sum(row[f"{prefix}_descripcion_normalizada"] == "true" for row in rows)
    similar_desc = sum(row[f"{prefix}_descripcion_similar"] == "true" for row in rows)
    public = sum(bool(row[f"{prefix}_precio_publico"]) for row in rows)
    usable = sum(bool(row[f"{prefix}_descripcion"]) for row in rows)
    high = sum(row[f"{prefix}_confianza"] == "alta" for row in rows)
    review = sum(row[f"{prefix}_revision"] == "true" for row in rows)
    pct = lambda value: round(value * 100 / count, 2) if count else 0
    return {
        "productos_ground_truth": count,
        "codigo_exacto": {"cantidad": count, "porcentaje": pct(count)},
        "clave_exacta": {"cantidad": exact_key, "porcentaje": pct(exact_key)},
        "precio_publico_recuperado": {"cantidad": public, "porcentaje": pct(public)},
        "descripcion_utilizable": {"cantidad": usable, "porcentaje": pct(usable)},
        "descripcion_exacta": {"cantidad": exact_desc, "porcentaje": pct(exact_desc)},
        "descripcion_normalizada": {"cantidad": norm_desc, "porcentaje": pct(norm_desc)},
        "descripcion_similar_60": {"cantidad": similar_desc, "porcentaje": pct(similar_desc)},
        "confianza_alta": {"cantidad": high, "porcentaje": pct(high)},
        "revision_necesaria": {"cantidad": review, "porcentaje": pct(review)},
        "errores_clave": count - exact_key,
    }


def main():
    master = load_master_catalog("output/catalogo_truper_master.csv")
    enriched = {code: product for code, product in master.items() if product.datos_completos}
    reader = PdfReader("catalogo_nacional_2026.pdf")
    old_results, new_results = {}, {}
    page_times = []
    started = time.perf_counter()
    with pdfplumber.open("catalogo_nacional_2026.pdf") as pdf:
        for page_number in PAGES:
            page_started = time.perf_counter()
            words = pdf.pages[page_number - 1].extract_words(extra_attrs=["fontname", "size"])
            old = extract_products_from_words(words, master, page_number)
            font_maps = build_page_font_maps(reader.pages[page_number - 1])
            new = extract_products_v2(words, master, page_number, font_maps)
            for product in old:
                if product.codigo_truper in enriched:
                    old_results.setdefault(product.codigo_truper, product)
            for product in new:
                if product.codigo_truper in enriched:
                    new_results.setdefault(product.codigo_truper, product)
            page_times.append(time.perf_counter() - page_started)

    codes = sorted(set(old_results) | set(new_results))
    rows = []
    for code in codes:
        truth = enriched[code]
        old = old_results.get(code)
        new = new_results.get(code)
        row = {
            "codigo_truper": code,
            "pagina_catalogo": (new or old).pagina_catalogo,
            "clave_ground_truth": truth.clave,
            "descripcion_ground_truth": truth.descripcion,
            "marca_ground_truth": truth.marca,
        }
        for prefix, product in (("anterior", old), ("nuevo", new)):
            key = product.clave if product else ""
            description = product.descripcion if product else ""
            normalized_description = normalize_description(description)
            normalized_truth = normalize_description(truth.descripcion)
            similarity = difflib.SequenceMatcher(None, normalized_description, normalized_truth).ratio() if normalized_description else 0
            row.update({
                f"{prefix}_clave": key,
                f"{prefix}_clave_exacta": str(key.upper() == truth.clave.upper()).lower(),
                f"{prefix}_descripcion": description,
                f"{prefix}_descripcion_exacta": str(description == truth.descripcion).lower(),
                f"{prefix}_descripcion_normalizada": str(bool(description) and normalized_description == normalized_truth).lower(),
                f"{prefix}_descripcion_similitud": f"{similarity:.4f}",
                f"{prefix}_descripcion_similar": str(similarity >= 0.60).lower(),
                f"{prefix}_marca": product.marca if product else "",
                f"{prefix}_precio_publico": "" if not product or product.precio_catalogo_publico is None else format(product.precio_catalogo_publico, "f"),
                f"{prefix}_confianza": product.confianza_extraccion if product else "baja",
                f"{prefix}_clave_confianza": product.clave_confianza if product else "BAJA",
                f"{prefix}_revision": str(product.requiere_revision if product else True).lower(),
            })
        rows.append(row)

    destination = Path("output/validacion_parser_pdf.csv")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    elapsed = time.perf_counter() - started
    report = {
        "pdf": "catalogo_nacional_2026.pdf",
        "paginas_pdf": len(reader.pages),
        "paginas_muestra": list(PAGES),
        "cantidad_paginas_muestra": len(PAGES),
        "ground_truth_disponible": len(enriched),
        "comparados": len(rows),
        "parser_anterior": metrics(rows, "anterior"),
        "parser_nuevo": metrics(rows, "nuevo"),
        "rendimiento": {
            "duracion_segundos": round(elapsed, 3),
            "extraccion_paginas_segundos": round(sum(page_times), 3),
            "segundos_por_pagina": round(sum(page_times) / len(PAGES), 3),
            "estimacion_644_paginas_segundos": round(sum(page_times) / len(PAGES) * 644, 1),
        },
        "fuentes": {
            "pymupdf_disponible_localmente": False,
            "metodo_nuevo": "pdfplumber para coordenadas + cmap/glyf TrueType embebido mediante pypdf",
            "hallazgo": "Los subconjuntos CID carecen de cmap utilizable; se emparejan contornos con la copia TrueType de la misma familia.",
        },
    }
    Path("output/reporte_validacion_parser.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
