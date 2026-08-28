from __future__ import annotations

import argparse
import time
from pathlib import Path

import pdfplumber

from truper_catalog.pdf_catalog import extract_products_from_words, load_master_catalog, save_pdf_sample_csv


DEFAULT_PAGES = (20, 60, 100, 140, 180, 220, 260, 300, 340, 380, 420, 460, 500, 540, 600)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba local y limitada del catálogo PDF de Truper")
    parser.add_argument("--pdf", default="catalogo_nacional_2026.pdf")
    parser.add_argument("--master", default="output/catalogo_truper_master.csv")
    parser.add_argument("--output", default="output/prueba_catalogo_pdf.csv")
    args = parser.parse_args()

    master = load_master_catalog(args.master)
    if len(master) != 11_124:
        raise RuntimeError(f"Se esperaban 11,124 códigos maestros; se encontraron {len(master):,}")

    started = time.perf_counter()
    per_page: list[list] = []
    page_times: list[float] = []
    open_started = time.perf_counter()
    with pdfplumber.open(Path(args.pdf)) as pdf:
        open_seconds = time.perf_counter() - open_started
        for page_number in DEFAULT_PAGES:
            page_started = time.perf_counter()
            words = pdf.pages[page_number - 1].extract_words(extra_attrs=["size"])
            products = extract_products_from_words(words, master, page_number)
            per_page.append(products)
            page_times.append(time.perf_counter() - page_started)

    selected = []
    seen = set()
    for products in per_page:
        for product in products:
            if product.codigo_truper not in seen:
                selected.append(product)
                seen.add(product.codigo_truper)
    written = save_pdf_sample_csv(selected, args.output)
    elapsed = time.perf_counter() - started
    complete = sum(product.estado_previo == "enriquecido" for product in selected)
    pending = sum(product.estado_previo == "pendiente" for product in selected)
    review = sum(product.requiere_revision for product in selected)
    print(f"PDF: {args.pdf}")
    print(f"Páginas inspeccionadas: {len(DEFAULT_PAGES)} ({', '.join(map(str, DEFAULT_PAGES))})")
    print(f"Productos escritos: {written} (enriquecidos={complete}, pendientes={pending})")
    print(f"Requieren revisión: {review}")
    print(f"Apertura PDF: {open_seconds:.3f} s")
    print(f"Extracción de páginas: {sum(page_times):.3f} s")
    print(f"Duración total: {elapsed:.3f} s")
    print(f"Rendimiento: {written / elapsed:.3f} productos/s")


if __name__ == "__main__":
    main()
