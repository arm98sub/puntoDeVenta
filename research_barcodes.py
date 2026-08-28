from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from truper_catalog.extractor import HttpConfig, TruperExtractor
from truper_catalog.models import Product
from truper_catalog.storage import load_csv, save_csv


BARCODE_PATTERN = re.compile(
    r"EAN|UPC|GTIN|c[oó]digo de barras|barcode|c[oó]digo comercial", re.IGNORECASE
)
LONG_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{8,14}(?!\d)")


@dataclass(slots=True)
class ProductEvidence:
    codigo: str
    clave: str
    ficha_url: str = ""
    ficha_web_id: str = ""
    barcode_terms: list[str] | None = None
    numeric_identifiers: list[str] | None = None
    matching_labels: list[str] | None = None
    json_ld_blocks: int = 0
    data_attributes: int = 0
    codigo_barras: str = ""
    error: str = ""


def inspect_product(client: TruperExtractor, product: Product) -> ProductEvidence:
    entry_url = (
        "https://www.truper.com/ficha_tecnica/controllers/index.php"
        f"?codigo={product.codigo}&origen=nal"
    )
    page = client._request("GET", entry_url)
    soup = BeautifulSoup(page.text, "html.parser")
    token_node = soup.select_one('meta[name="csrf-token"]')
    token = token_node.get("content", "") if token_node else ""
    endpoint = urljoin(page.url, "findProductsCod")
    detail = client._request(
        "POST",
        endpoint,
        json={"producto": product.codigo},
        headers={"X-CSRF-TOKEN": token, "Content-Type": "application/json"},
    )
    payload = detail.json()
    joined = " ".join(payload) if isinstance(payload, list) else str(payload)
    detail_soup = BeautifulSoup(joined, "html.parser")
    combined = page.text + " " + joined
    labels = [node.get_text(" ", strip=True) for node in detail_soup.select("th")]
    visible_text = detail_soup.get_text(" ", strip=True)
    web_id_match = re.search(r"-(\d+)\.html", page.url)
    matching_labels = sorted({label for label in labels if BARCODE_PATTERN.search(label)})
    terms = sorted({match.group(0) for match in BARCODE_PATTERN.finditer(combined)})
    long_numbers = sorted(set(LONG_NUMBER_PATTERN.findall(visible_text)))

    # Un número sólo se acepta como barcode si el HTML lo etiqueta explícitamente.
    # En la investigación actual no se infiere ni calcula desde codigo/clave.
    barcode = ""
    return ProductEvidence(
        codigo=product.codigo,
        clave=product.clave,
        ficha_url=page.url,
        ficha_web_id=web_id_match.group(1) if web_id_match else "",
        barcode_terms=terms,
        numeric_identifiers=long_numbers,
        matching_labels=matching_labels,
        json_ld_blocks=len(soup.select('script[type="application/ld+json"]')),
        data_attributes=len(soup.select("[data-zoom-image], [data-fancybox], [data-width]")),
        codigo_barras=barcode,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Investiga EAN/UPC/GTIN en fichas públicas")
    parser.add_argument("--input", default="output/truper_expanded_sample.csv")
    parser.add_argument("--output", default="output/truper_barcode_sample.csv")
    parser.add_argument("--report", default="output/truper_barcode_evidence.json")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    products = load_csv(args.input)[: max(0, min(args.limit, 20))]
    client = TruperExtractor(
        config=HttpConfig(
            delay=args.delay,
            user_agent="ferreteria-catalog-barcode-research/0.1 (public metadata audit)",
        )
    )
    started = time.monotonic()
    evidence: list[ProductEvidence] = []
    errors = 0
    for product in products:
        try:
            item = inspect_product(client, product)
            evidence.append(item)
        except Exception as exc:
            errors += 1
            evidence.append(ProductEvidence(product.codigo, product.clave, error=str(exc)))

    save_csv(products, args.output)
    report = {
        "requests": client.request_count,
        "products_inspected": len(products),
        "barcodes_found": sum(bool(item.codigo_barras) for item in evidence),
        "errors": errors,
        "elapsed_seconds": time.monotonic() - started,
        "evidence": [asdict(item) for item in evidence],
    }
    destination = Path(args.report)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "evidence"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
