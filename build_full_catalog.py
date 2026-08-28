from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from truper_catalog.extractor import BASE_URL, HttpConfig, TruperExtractor, normalize_brand, normalize_text
from truper_catalog.models import Product
from truper_catalog.storage import load_csv, save_csv


DEFAULT_TERMS = ["truper", "pretul", "volteck", "foset", "fiero", "hermex", "klintek"]


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_product(product: Product) -> Product:
    return Product(
        codigo=product.codigo.strip(),
        clave=product.clave.strip(),
        descripcion=normalize_text(product.descripcion),
        marca=normalize_brand(product.marca),
        categoria=normalize_text(product.categoria),
        codigo_barras="",
    )


def extraction_stage(client: TruperExtractor, args, started: float) -> tuple[dict[str, Product], dict]:
    output = Path(args.output)
    state_path = Path(args.search_checkpoint)
    cache_path = Path(args.category_cache)
    if args.fresh:
        products: dict[str, Product] = {}
        state = {"terms": {}, "stats": {"rows_seen": 0, "duplicates": 0, "errors": 0}}
        client._category_cache = {}
    else:
        products = {p.codigo: p for p in load_csv(output)}
        state = read_json(state_path, {"terms": {}, "stats": {"rows_seen": 0, "duplicates": 0, "errors": 0}})
        client._category_cache = read_json(cache_path, {})

    for term in DEFAULT_TERMS:
        term_state = state["terms"].setdefault(term, {"next_page": 1, "done": False})
        while not term_state["done"]:
            page = int(term_state["next_page"])
            try:
                rows, last_page = client.search_page(term, page)
                if not rows:
                    term_state["done"] = True
                else:
                    state["stats"]["rows_seen"] += len(rows)
                    for raw in rows:
                        product = normalize_product(raw)
                        if product.codigo in products:
                            state["stats"]["duplicates"] += 1
                        else:
                            products[product.codigo] = product
                    term_state["next_page"] = page + 1
                    term_state["done"] = page >= last_page
                save_csv(products.values(), output)
                write_json(cache_path, client._category_cache)
                state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                write_json(state_path, state)
                print(f"SEARCH {term} page={page} rows={len(rows)} unique={len(products)} requests={client.request_count}", flush=True)
            except Exception as exc:
                state["stats"]["errors"] += 1
                with Path(args.errors).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"stage": "search", "term": term, "page": page, "error": str(exc)}, ensure_ascii=False) + "\n")
                write_json(state_path, state)
                raise

    search_report = {
        "products_from_brand_search": len(products),
        "rows_seen": state["stats"]["rows_seen"],
        "duplicates": state["stats"]["duplicates"],
        "errors": state["stats"]["errors"],
        "products_by_brand": dict(sorted(Counter(p.marca or "SIN MARCA" for p in products.values()).items())),
        "requests_current_run": client.request_count,
        "elapsed_seconds_current_run": time.monotonic() - started,
    }
    write_json(Path(args.search_report), search_report)
    return products, search_report


def parse_ficha_codes(payload: dict, page: int) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for module, html in payload.items():
        soup = BeautifulSoup(str(html), "html.parser")
        for code_node in soup.select("span.code"):
            link = code_node.find_parent("a")
            sku_node = link.select_one("span.sku") if link else None
            code = normalize_text(code_node.get_text(" ", strip=True))
            if code:
                found[code] = {
                    "clave": normalize_text(sku_node.get_text(" ", strip=True)) if sku_node else "",
                    "page": page,
                    "module": str(module),
                }
    return found


def validation_stage(client: TruperExtractor, products: dict[str, Product], args, started: float) -> dict:
    checkpoint_path = Path(args.validation_checkpoint)
    state = {"next_page": 1, "codes": {}, "errors": 0} if args.fresh_validation else read_json(
        checkpoint_path, {"next_page": 1, "codes": {}, "errors": 0}
    )
    for page_number in range(int(state["next_page"]), args.max_catalog_page + 1):
        try:
            page = client._request("GET", urljoin(BASE_URL, "searchPage"), params={"page": page_number})
            soup = BeautifulSoup(page.text, "html.parser")
            modules = sorted({str(node.get("data-modulo")).strip() for node in soup.select("[data-modulo]") if node.get("data-modulo")})
            if modules:
                response = client._request(
                    "POST", urljoin(BASE_URL, "ficha/fichas"), data=[("modulos[]", module) for module in modules]
                )
                state["codes"].update(parse_ficha_codes(response.json(), page_number))
            state["next_page"] = page_number + 1
            if page_number % 10 == 0 or modules:
                write_json(checkpoint_path, state)
                print(f"VALIDATE page={page_number} modules={len(modules)} codes={len(state['codes'])} requests={client.request_count}", flush=True)
        except Exception as exc:
            state["errors"] += 1
            with Path(args.errors).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"stage": "validation", "page": page_number, "error": str(exc)}, ensure_ascii=False) + "\n")
            state["next_page"] = page_number + 1
            write_json(checkpoint_path, state)
    write_json(checkpoint_path, state)

    search_codes = set(products)
    ficha_codes = set(state["codes"])
    missing = sorted(ficha_codes - search_codes)
    # La recuperación se realiza aparte por prefijos con recover_missing_catalog.py.
    recovered: list[str] = []

    final_codes = set(products)
    incomplete = [p.codigo for p in products.values() if not p.clave or not p.descripcion or not p.marca or not p.categoria]
    report = {
        "products_from_brand_search": len(search_codes),
        "codes_from_ficha_fichas": len(ficha_codes),
        "codes_in_both_sources": len(search_codes & ficha_codes),
        "codes_only_in_ficha_fichas_before_recovery": missing,
        "codes_only_in_searches": sorted(search_codes - ficha_codes),
        "missing_count_before_recovery": len(missing),
        "recovered_codes": recovered,
        "recovered_count": len(recovered),
        "final_unique_products": len(final_codes),
        "incomplete_records": incomplete,
        "incomplete_count": len(incomplete),
        "validation_errors": state["errors"],
        "requests_current_run_total": client.request_count,
        "elapsed_seconds_current_run_total": time.monotonic() - started,
    }
    write_json(Path(args.validation_report), report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrae y valida el catálogo público completo de Truper")
    parser.add_argument("--output", default="output/catalogo_truper.csv")
    parser.add_argument("--search-checkpoint", default="state/full_search_checkpoint.json")
    parser.add_argument("--validation-checkpoint", default="state/ficha_validation_checkpoint.json")
    parser.add_argument("--category-cache", default="state/category_cache.json")
    parser.add_argument("--search-report", default="output/reporte_extraccion.json")
    parser.add_argument("--validation-report", default="output/reporte_validacion.json")
    parser.add_argument("--errors", default="logs/catalogo_errors.jsonl")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-catalog-page", type=int, default=601)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--fresh-validation", action="store_true")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--skip-recovery", action="store_true", default=True)
    args = parser.parse_args()
    Path(args.errors).parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    client = TruperExtractor(config=HttpConfig(timeout=args.timeout, delay=max(1.0, args.delay), retries=args.retries))
    products, search_report = extraction_stage(client, args, started)
    validation_report = None if args.skip_validation else validation_stage(client, products, args, started)
    print(json.dumps({"search": search_report, "validation": validation_report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
