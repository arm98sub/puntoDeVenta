from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from truper_catalog.pdf_catalog import extract_all_products_v2, load_master_catalog
from truper_catalog.pdf_fonts import build_page_font_maps
from truper_catalog.pdf_checkpoint import atomic_json, load_checkpoint, save_checkpoint
from truper_catalog.pdf_merge import (
    choose_pdf_product, merge_master_row, pdf_product_from_json, pdf_product_to_json, valid_key,
)


CHECKPOINT = Path("state/pdf_full_checkpoint.json")
MASTER_CSV = Path("output/catalogo_truper_master.csv")
OUTPUT_CSV = Path("output/catalogo_truper_enriquecido.csv")
UNKNOWN_CSV = Path("output/productos_pdf_no_master.csv")
REPORT = Path("output/reporte_extraccion_pdf_completa.json")
SKIP_PAGES = set(range(616, 645))  # índices código-página y contraportada


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            safe = {
                key: ("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value)
                for key, value in row.items()
            }
            writer.writerow(safe)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description="Extracción completa local y reanudable del PDF Truper")
    parser.add_argument("--fresh", action="store_true", help="Ignora el checkpoint e inicia desde la página 1")
    parser.add_argument("--checkpoint-every", type=int, default=5)
    args = parser.parse_args()

    master = load_master_catalog(MASTER_CSV)
    with MASTER_CSV.open(encoding="utf-8-sig", newline="") as handle:
        master_rows = {row["codigo_truper"].strip(): row for row in csv.DictReader(handle)}
    if len(master_rows) != 11_124:
        raise RuntimeError(f"El maestro debe contener 11,124 códigos; contiene {len(master_rows):,}")

    state = load_checkpoint(CHECKPOINT, args.fresh)
    state.setdefault("products", {})
    state["products"] = {
        code: product for code, product in state["products"].items()
        if product.pagina_catalogo is None or product.pagina_catalogo < 614
    }
    state["products"] = {
        code: product for code, product in state["products"].items()
        if "índice de referencia" not in product.descripcion_familia.casefold()
    }
    completed = set(state["completed_pages"])
    started = time.perf_counter()
    reader = PdfReader("catalogo_nacional_2026.pdf")
    with pdfplumber.open("catalogo_nacional_2026.pdf") as pdf:
        total_pages = len(pdf.pages)
        for page_number in range(1, total_pages + 1):
            if page_number in SKIP_PAGES:
                completed.add(page_number)
                state["completed_pages"] = sorted(completed)
                continue
            if page_number in completed:
                continue
            try:
                words = pdf.pages[page_number - 1].extract_words(extra_attrs=["fontname", "size"])
                font_maps = build_page_font_maps(reader.pages[page_number - 1])
                products = extract_all_products_v2(words, master, page_number, font_maps)
                for product in products:
                    state["products"][product.codigo_truper] = choose_pdf_product(
                        state["products"].get(product.codigo_truper), product
                    )
            except Exception as exc:  # continúa y conserva el error por página
                state["errors"].append({"page": page_number, "error": f"{type(exc).__name__}: {exc}"})
            completed.add(page_number)
            state["completed_pages"] = sorted(completed)
            if page_number % args.checkpoint_every == 0 or page_number == total_pages:
                save_checkpoint(CHECKPOINT, state)
            if page_number % 25 == 0:
                print(f"progreso={page_number}/{total_pages} productos={len(state['products'])}", flush=True)

    save_checkpoint(CHECKPOINT, state)

    pdf_products = state["products"]
    final_rows, review_rows = [], []
    discrepancies_key = discrepancies_description = 0
    for code, master_row in master_rows.items():
        row, reasons = merge_master_row(master_row, pdf_products.get(code))
        final_rows.append(row)
        if "discrepancia_clave" in reasons:
            discrepancies_key += 1
        if "discrepancia_descripcion" in reasons:
            discrepancies_description += 1
        if reasons:
            review_rows.append({**row, "motivo_revision": ";".join(reasons)})

    unknown_rows = []
    accepted_unknown = []
    for code, product in sorted(pdf_products.items()):
        if code in master_rows:
            continue
        accepted = (
            product.confianza_extraccion == "alta" and valid_key(product.clave)
            and bool(product.descripcion or product.descripcion_familia)
        )
        unknown_rows.append({
            "codigo_truper": code, "clave": product.clave, "descripcion": product.descripcion,
            "descripcion_familia": product.descripcion_familia, "presentacion": product.presentacion,
            "marca": product.marca,
            "precio_catalogo_publico": "" if product.precio_catalogo_publico is None else format(product.precio_catalogo_publico, "f"),
            "pagina_catalogo": product.pagina_catalogo or "", "confianza_extraccion": product.confianza_extraccion,
            "requiere_revision": str(product.requiere_revision), "elegible_para_maestro": str(accepted),
        })
        if accepted:
            accepted_unknown.append(code)

    # Los códigos adicionales se reportan, pero no se incorporan automáticamente:
    # requieren revisión humana antes de ampliar el universo maestro.
    write_csv(OUTPUT_CSV, final_rows)
    if unknown_rows:
        write_csv(UNKNOWN_CSV, unknown_rows)
    else:
        write_csv(UNKNOWN_CSV, [{
            "codigo_truper": "", "clave": "", "descripcion": "", "descripcion_familia": "",
            "presentacion": "", "marca": "", "precio_catalogo_publico": "", "pagina_catalogo": "",
            "confianza_extraccion": "", "requiere_revision": "", "elegible_para_maestro": "",
        }])
    review_csv = Path("output/productos_requieren_revision.csv")
    write_csv(review_csv, review_rows)

    counts = Counter(row["confianza_extraccion"] for row in final_rows if row["encontrado_en_pdf"] == "True")
    found_master = sum(row["encontrado_en_pdf"] == "True" for row in final_rows)
    report = {
        "paginas_procesadas": len(completed),
        "paginas_con_productos": len({p.pagina_catalogo for p in pdf_products.values() if p.pagina_catalogo is not None}),
        "productos_encontrados": len(pdf_products),
        "codigos_unicos_encontrados": len(pdf_products),
        "productos_maestro_encontrados_pdf": found_master,
        "productos_enriquecidos": sum(row["datos_completos"] == "True" for row in final_rows),
        "productos_siguen_pendientes": sum(row["datos_completos"] != "True" for row in final_rows),
        "claves_recuperadas_pdf": sum(bool(p.clave) and valid_key(p.clave) for p in pdf_products.values() if p.codigo_truper in master_rows),
        "precios_publicos_recuperados": sum(bool(row["precio_catalogo_publico"]) for row in final_rows),
        "descripciones_recuperadas": sum(bool(row["descripcion"]) for row in final_rows),
        "confianza_alta": counts["alta"], "confianza_media": counts["media"], "confianza_baja": counts["baja"],
        "productos_requieren_revision": len(review_rows),
        "codigos_maestro_no_encontrados_pdf": len(master_rows) - found_master,
        "codigos_pdf_no_presentes_maestro": len(unknown_rows),
        "codigos_pdf_elegibles_revision_para_maestro": len(accepted_unknown),
        "discrepancias_clave": discrepancies_key,
        "discrepancias_descripcion": discrepancies_description,
        "errores": state["errors"],
        "duracion_total_segundos_corrida_actual": round(time.perf_counter() - started, 3),
        "duracion_total_desde_inicio_checkpoint_segundos": round(time.time() - state["started_at"], 3),
        "registros_finales": len(final_rows),
    }
    atomic_json(REPORT, report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
