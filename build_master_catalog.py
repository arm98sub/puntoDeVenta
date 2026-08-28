from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from truper_catalog.storage import load_csv


MASTER_FIELDS = (
    "codigo_truper",
    "codigo_barras",
    "clave",
    "descripcion",
    "marca",
    "categoria",
    "precio_venta",
    "existencia",
    "datos_completos",
)


def build_master(
    enriched_csv: Path,
    validation_checkpoint: Path,
    search_checkpoint: Path | None = None,
    error_log: Path | None = None,
) -> tuple[list[dict], dict]:
    enriched = {product.codigo: product for product in load_csv(enriched_csv)}
    validation = json.loads(validation_checkpoint.read_text(encoding="utf-8"))
    ficha = validation.get("codes", {})
    all_codes = sorted(set(ficha) | set(enriched), key=lambda value: (len(value), value))
    rows: list[dict] = []
    duplicates = 0
    for code in all_codes:
        product = enriched.get(code)
        ficha_data = ficha.get(code, {})
        clave = product.clave if product and product.clave else str(ficha_data.get("clave") or "").strip()
        complete = bool(product and clave and product.descripcion and product.marca and product.categoria)
        rows.append({
            "codigo_truper": code,
            "codigo_barras": "",
            "clave": clave,
            "descripcion": product.descripcion if product else "",
            "marca": product.marca if product else "",
            "categoria": product.categoria if product else "",
            "precio_venta": "",
            "existencia": "",
            "datos_completos": complete,
        })
    original_search_count = 1201
    search_state = json.loads(search_checkpoint.read_text(encoding="utf-8")) if search_checkpoint and search_checkpoint.exists() else {"stats": {}}
    errors = error_log.read_text(encoding="utf-8").splitlines() if error_log and error_log.exists() else []
    report = {
        "total_unique_codes": len(rows),
        "enriched_products": sum(row["datos_completos"] for row in rows),
        "pending_enrichment": sum(not row["datos_completos"] for row in rows),
        "recovered_before_429": max(0, len(enriched) - original_search_count),
        "enriched_rows_in_source": len(enriched),
        "codes_from_ficha_fichas": len(ficha),
        "search_only_codes": len(set(enriched) - set(ficha)),
        "duplicates": int(search_state.get("stats", {}).get("duplicates", duplicates)),
        "http_errors": len(errors),
        "http_429_errors": sum("429" in line for line in errors),
        "products_by_brand_enriched": dict(sorted(Counter(
            row["marca"] for row in rows if row["datos_completos"]
        ).items())),
    }
    return rows, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Construye el catálogo maestro sin solicitudes web")
    parser.add_argument("--enriched", default="output/catalogo_truper.csv")
    parser.add_argument("--validation", default="state/ficha_validation_checkpoint.json")
    parser.add_argument("--output", default="output/catalogo_truper_master.csv")
    parser.add_argument("--report", default="output/reporte_catalogo_master.json")
    parser.add_argument("--search-checkpoint", default="state/full_search_checkpoint.json")
    parser.add_argument("--errors", default="logs/catalogo_errors.jsonl")
    args = parser.parse_args()

    rows, report = build_master(
        Path(args.enriched), Path(args.validation), Path(args.search_checkpoint), Path(args.errors)
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MASTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
