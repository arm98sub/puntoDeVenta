from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Product


BASE_URL = "https://www.truper.com/CatVigente/"
SEARCH_URL = urljoin(BASE_URL, "producto/searching")
FULL_SEARCH_URL = urljoin(BASE_URL, "buscador")

# Sólo marcas visibles en el menú público del catálogo. El orden evita que
# "TRUPER" gane antes que "TRUPER EXPERT".
KNOWN_BRANDS = (
    "TRUPER EXPERT",
    "VOLTECK LAIT",
    "TRUPER",
    "PRETUL",
    "VOLTECK",
    "FOSET",
    "FIERO",
    "HERMEX",
    "KLINTEK",
    "EXPERT",
)

BRAND_ALIASES = {
    "TRUPER": "TRUPER",
    "TRUPER EXPERT": "TRUPER EXPERT",
    "EXPERT": "TRUPER EXPERT",
    "PRETUL": "PRETUL",
    "VOLTECK": "VOLTECK",
    "VOLTECK LAIT": "VOLTECK LAIT",
    "FOSET": "FOSET",
    "FIERO": "FIERO",
    "HERMEX": "HERMEX",
    "KLINTEK": "KLINTEK",
}


@dataclass(frozen=True, slots=True)
class HttpConfig:
    timeout: float = 20.0
    delay: float = 1.0
    retries: int = 2
    user_agent: str = "ferreteria-catalog-prototype/0.2 (respectful public-catalog test)"
    observed_page_size: int = 30


@dataclass(slots=True)
class ExtractionStats:
    requests: int = 0
    products_seen: int = 0
    unique_products: int = 0
    duplicates: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


class TruperExtractor:
    """Cliente HTTP del buscador público; no contiene lógica de persistencia."""

    def __init__(self, pause_seconds: float | None = None, timeout: float | None = None,
                 config: HttpConfig | None = None):
        base = config or HttpConfig()
        self.config = HttpConfig(
            timeout=base.timeout if timeout is None else timeout,
            delay=base.delay if pause_seconds is None else max(0.0, pause_seconds),
            retries=base.retries,
            user_agent=base.user_agent,
            observed_page_size=base.observed_page_size,
        )
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.config.user_agent})
        retry = Retry(
            total=self.config.retries,
            connect=self.config.retries,
            read=self.config.retries,
            status=self.config.retries,
            # 429 se devuelve inmediatamente al llamador para detener la corrida;
            # no se insiste contra un rate limit. Retry-After queda disponible.
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(("GET", "POST")),
            backoff_factor=1.0,
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._category_cache: dict[str, str] = {}
        self._last_request_at = 0.0
        self.request_count = 0

    def _wait(self) -> None:
        remaining = self.config.delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._wait()
        response = self.session.request(method, url, timeout=self.config.timeout, **kwargs)
        self._last_request_at = time.monotonic()
        self.request_count += 1
        response.raise_for_status()
        return response

    def search(self, term: str, limit: int = 5) -> list[Product]:
        term = term.strip()
        if not term:
            raise ValueError("El término de búsqueda no puede estar vacío")
        if limit < 1:
            return []

        payload = self._request("POST", SEARCH_URL, data={"word": term}).json()
        rows = payload.get("data") or []
        products: list[Product] = []
        seen: set[tuple[str, str]] = set()

        for row in rows:
            code = str(row.get("codigo") or "").strip()
            sku = str(row.get("clave") or "").strip()
            description = str(row.get("pn") or "").strip()
            if not code and not sku:
                continue
            identity = (code, sku.upper())
            if identity in seen:
                continue

            page_url = self._first_page_url(row)
            category = self._category_from_page(page_url) if page_url else ""
            product = Product(
                codigo=code,
                clave=sku,
                descripcion=description,
                marca=detect_brand(description),
                categoria=category,
            )
            seen.add(identity)
            products.append(product)
            if len(products) >= limit:
                break
        return products

    @staticmethod
    def _first_page_url(row: dict) -> str:
        pages = row.get("pages") or []
        if pages and isinstance(pages[0], dict):
            return str(pages[0].get("url") or "").strip()
        return ""

    def _category_from_page(self, relative_url: str) -> str:
        absolute_url = urljoin(BASE_URL, relative_url)
        if absolute_url in self._category_cache:
            return self._category_cache[absolute_url]
        html = self._request("GET", absolute_url).text
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        category = re.sub(r"^TRUPER\s*-\s*", "", title, flags=re.IGNORECASE).strip()
        self._category_cache[absolute_url] = category
        return category

    def search_page(self, term: str, page: int = 1) -> tuple[list[Product], int]:
        """Lee una página de la tabla completa y devuelve productos y última página."""
        response = self._request("GET", FULL_SEARCH_URL, params={"palabra": term, "page": page})
        soup = BeautifulSoup(response.text, "html.parser")
        products: list[Product] = []
        for row in soup.select("tr.kpi-track-click"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 5:
                continue
            code = str(row.get("data-documentid") or "").strip()
            sku = str(row.get("data-objectname") or "").strip()
            if not code:
                continue
            brand_img = cells[1].find("img")
            brand = ""
            if brand_img and brand_img.get("src"):
                brand = normalize_brand(Path(str(brand_img["src"])).stem)
            description_node = cells[4].select_one(".description-search")
            description = description_node.get_text(" ", strip=True) if description_node else _leading_text(cells[4])
            source = str(cells[0].get("data-source") or "").strip()
            category = self._category_from_page(source) if source else ""
            products.append(Product(code, sku, description, brand, category))

        pages = [1]
        for anchor in soup.select(".pagination a[href]"):
            match = re.search(r"[?&]page=(\d+)", str(anchor.get("href")))
            if match:
                pages.append(int(match.group(1)))
        return products, max(pages)

    def enumerate_search(
        self,
        terms: list[str],
        limit: int,
        checkpoint_path: str | Path,
        error_log_path: str | Path,
        seed: list[Product] | None = None,
        ignore_checkpoint: bool = False,
    ) -> tuple[list[Product], ExtractionStats]:
        started = time.monotonic()
        checkpoint_file = Path(checkpoint_path)
        checkpoint = {"completed": []} if ignore_checkpoint else _read_checkpoint(checkpoint_file)
        completed = set(checkpoint.get("completed", []))
        by_code = {p.codigo: p for p in (seed or [])}
        stats = ExtractionStats()

        for term in terms:
            page = 1
            last_page = 1
            while page <= last_page and len(by_code) < limit:
                key = f"{term}:{page}"
                if key in completed:
                    page += 1
                    continue
                try:
                    rows, last_page = self.search_page(term, page)
                    stats.products_seen += len(rows)
                    consumed_all = True
                    for product in rows:
                        if product.codigo in by_code:
                            stats.duplicates += 1
                        else:
                            by_code[product.codigo] = product
                            if len(by_code) >= limit:
                                consumed_all = False
                                break
                    if consumed_all:
                        completed.add(key)
                        _write_checkpoint(checkpoint_file, completed)
                except Exception as exc:
                    stats.errors += 1
                    _append_error(error_log_path, term, page, exc)
                    break
                page += 1

        stats.requests = self.request_count
        stats.unique_products = len(by_code)
        stats.elapsed_seconds = time.monotonic() - started
        return list(by_code.values())[:limit], stats


def detect_brand(description: str) -> str:
    normalized = " ".join(description.upper().split()).rstrip(" .")
    for brand in KNOWN_BRANDS:
        if re.search(rf"(?:,|\s)\s*{re.escape(brand)}$", normalized):
            return normalize_brand(brand)
    return ""


def normalize_brand(value: str) -> str:
    normalized = " ".join(value.upper().replace("_", " ").replace("-", " ").split())
    return BRAND_ALIASES.get(normalized, normalized)


def normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def _leading_text(cell) -> str:
    container = cell.find("a", recursive=False) or cell
    for child in container.children:
        if isinstance(child, str) and child.strip():
            return " ".join(child.split())
    return ""


def _read_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {"completed": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_checkpoint(path: Path, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"completed": sorted(completed), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_error(path: str | Path, term: str, page: int, exc: Exception) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = {"term": term, "page": page, "error": str(exc), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
