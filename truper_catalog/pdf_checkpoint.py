from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .pdf_merge import pdf_product_from_json, pdf_product_to_json


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def load_checkpoint(path: Path, fresh: bool):
    if fresh or not path.exists():
        return {"completed_pages": [], "products": {}, "errors": [], "started_at": time.time()}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["products"] = {code: pdf_product_from_json(row) for code, row in data["products"].items()}
    return data


def save_checkpoint(path: Path, state) -> None:
    payload = dict(state)
    payload["products"] = {code: pdf_product_to_json(product) for code, product in state["products"].items()}
    atomic_json(path, payload)
