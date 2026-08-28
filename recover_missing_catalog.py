from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

from build_full_catalog import normalize_product, read_json, write_json
from truper_catalog.extractor import HttpConfig, TruperExtractor
from truper_catalog.storage import load_csv, save_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Recupera productos faltantes mediante prefijos numéricos")
    parser.add_argument("--catalog", default="output/catalogo_truper.csv")
    parser.add_argument("--validation-checkpoint", default="state/ficha_validation_checkpoint.json")
    parser.add_argument("--checkpoint", default="state/prefix_recovery_checkpoint.json")
    parser.add_argument("--category-cache", default="state/category_cache.json")
    parser.add_argument("--report", default="output/reporte_validacion.json")
    parser.add_argument("--errors", default="logs/catalogo_errors.jsonl")
    parser.add_argument("--delay", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    started = time.monotonic()
    products = {p.codigo: p for p in load_csv(args.catalog)}
    initial_search_codes = set(products)
    validation = read_json(Path(args.validation_checkpoint), {"codes": {}, "errors": 0})
    ficha_codes = set(validation.get("codes", {}))
    missing = ficha_codes - set(products)
    groups: dict[str, set[str]] = defaultdict(set)
    for code in missing:
        groups[code[: min(4, len(code))]].add(code)

    state = read_json(Path(args.checkpoint), {
        "completed_prefixes": [], "recovered_codes": [], "requests": 0,
        "duplicates": 0, "errors": 0, "rate_limited": False,
    })
    completed = set(state["completed_prefixes"])
    recovered = set(state["recovered_codes"])
    client = TruperExtractor(config=HttpConfig(timeout=args.timeout, delay=max(1.0, args.delay), retries=args.retries))
    client._category_cache = read_json(Path(args.category_cache), {})

    try:
        for prefix in sorted(groups):
            if prefix in completed:
                continue
            page = 1
            last_page = 1
            prefix_ok = True
            while page <= last_page:
                rows, last_page = client.search_page(prefix, page)
                for raw in rows:
                    if raw.codigo not in ficha_codes:
                        continue
                    product = normalize_product(raw)
                    if product.codigo in products:
                        state["duplicates"] += 1
                    elif product.clave and product.descripcion and product.categoria:
                        products[product.codigo] = product
                        recovered.add(product.codigo)
                page += 1
            if prefix_ok:
                completed.add(prefix)
                save_csv(products.values(), args.catalog)
                state.update({
                    "completed_prefixes": sorted(completed),
                    "recovered_codes": sorted(recovered),
                    "requests": state["requests"] + client.request_count,
                    "rate_limited": False,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
                client.request_count = 0
                write_json(Path(args.checkpoint), state)
                write_json(Path(args.category_cache), client._category_cache)
                print(f"RECOVER prefix={prefix} recovered={len(recovered)} catalog={len(products)} completed={len(completed)}/{len(groups)}", flush=True)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        state["errors"] += 1
        state["rate_limited"] = status == 429
        state["requests"] += client.request_count
        write_json(Path(args.checkpoint), state)
        with Path(args.errors).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"stage": "prefix_recovery", "status": status, "error": str(exc)}, ensure_ascii=False) + "\n")
        if status == 429:
            print("RATE_LIMITED: ejecución detenida; reanude más tarde con el mismo comando", flush=True)
            raise SystemExit(75)
        raise

    final_codes = set(products)
    incomplete = [p.codigo for p in products.values() if not p.clave or not p.descripcion or not p.marca or not p.categoria]
    report = {
        "products_from_brand_search": len(initial_search_codes - recovered),
        "codes_from_ficha_fichas": len(ficha_codes),
        "codes_in_both_sources": len((initial_search_codes - recovered) & ficha_codes),
        "codes_only_in_ficha_fichas_before_recovery": len(ficha_codes - (initial_search_codes - recovered)),
        "codes_only_in_searches": len((initial_search_codes - recovered) - ficha_codes),
        "recovered_count": len(recovered),
        "remaining_missing_count": len(ficha_codes - final_codes),
        "final_unique_products": len(products),
        "products_by_brand": dict(sorted(Counter(p.marca or "SIN MARCA" for p in products.values()).items())),
        "duplicates_during_recovery": state["duplicates"],
        "incomplete_count": len(incomplete),
        "incomplete_codes": incomplete,
        "validation_errors": validation.get("errors", 0),
        "recovery_errors": state["errors"],
        "recovery_requests": state["requests"],
        "elapsed_seconds_current_run": time.monotonic() - started,
    }
    write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
