from __future__ import annotations

import requests

from .extractor import HttpConfig, TruperExtractor
from .models import Product


class RateLimitError(RuntimeError):
    """El sitio respondió HTTP 429; no debe reintentarse automáticamente."""


def enriquecer_producto(
    codigo_truper: str,
    *,
    delay: float = 5.0,
    timeout: float = 30.0,
    retries: int = 2,
) -> Product | None:
    """Consulta un único código solicitado explícitamente.

    No guarda archivos ni procesa listas. Ante HTTP 429 se detiene inmediatamente.
    """
    code = codigo_truper.strip()
    if not code:
        raise ValueError("codigo_truper no puede estar vacío")
    client = TruperExtractor(
        config=HttpConfig(
            timeout=timeout,
            delay=max(1.0, delay),
            retries=retries,
            user_agent="ferreteria-catalog-on-demand-enrichment/0.1",
        )
    )
    try:
        matches = client.search(code, limit=5)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            retry_after = exc.response.headers.get("Retry-After")
            suffix = f" Retry-After: {retry_after}." if retry_after else ""
            raise RateLimitError(f"Truper respondió HTTP 429.{suffix}") from exc
        raise
    return next((product for product in matches if product.codigo == code), None)
