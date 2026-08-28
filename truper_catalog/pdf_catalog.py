from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .pdf_fonts import decode_cids_with_font


PDF_DIGIT_TRANSLATION = str.maketrans({
    "Y": "0", "[": "1", "\\": "2", "]": "3", "^": "4",
    "_": "5", "`": "6", "a": "7", "b": "8", "c": "9",
})
KNOWN_BRANDS = ("TRUPER", "PRETUL", "VOLTECK", "FOSET", "FIERO", "HERMEX", "KLINTEK")
OUTPUT_FIELDS = (
    "codigo_truper", "clave", "descripcion", "descripcion_familia",
    "presentacion", "marca", "precio_catalogo_mayoreo",
    "precio_catalogo_medio_mayoreo", "precio_catalogo_publico",
    "pagina_catalogo", "estado_previo", "confianza_extraccion",
    "clave_confianza", "requiere_revision",
)


@dataclass(frozen=True, slots=True)
class MasterProduct:
    codigo_truper: str
    clave: str
    descripcion: str
    marca: str
    datos_completos: bool


@dataclass(frozen=True, slots=True)
class PdfProduct:
    codigo_truper: str
    clave: str
    descripcion: str
    descripcion_familia: str
    presentacion: str
    marca: str
    precio_catalogo_mayoreo: Decimal | None
    precio_catalogo_medio_mayoreo: Decimal | None
    precio_catalogo_publico: Decimal | None
    pagina_catalogo: int | None
    estado_previo: str
    confianza_extraccion: str
    clave_confianza: str
    requiere_revision: bool


def decode_pdf_glyphs(value: str) -> str:
    """Convierte CIDs ASCII y la fuente numérica estilizada usada por el PDF."""
    def cid(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return chr(number) if 0 <= number <= 255 else ""

    decoded = re.sub(r"\(cid:(\d+)\)", cid, value)
    # a, b y c también son letras normales: sólo se traducen cuando todo el
    # token tiene la forma de un número/precio compuesto con la fuente especial.
    if re.fullmatch(r"[\s$,.Y\[\\\]\^_`abc0-9*●Þ•†‡]+", decoded):
        return decoded.translate(PDF_DIGIT_TRANSLATION)
    return decoded


def normalize_code_token(value: str, known_codes: set[str] | None = None) -> str:
    decoded = decode_pdf_glyphs(value).strip().replace("●", "").replace("Þ", "")
    decoded = decoded.rstrip("*•†‡").strip()
    match = re.fullmatch(r"\D*(\d{4,6})\D*", decoded)
    code = match.group(1) if match else ""
    if known_codes is not None and code not in known_codes:
        return ""
    return code


def parse_decimal_price(value: str) -> Decimal | None:
    cleaned = decode_pdf_glyphs(value).replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def load_master_catalog(path: str | Path) -> dict[str, MasterProduct]:
    products: dict[str, MasterProduct] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = row["codigo_truper"].strip()
            products[code] = MasterProduct(
                codigo_truper=code,
                clave=row.get("clave", "").strip(),
                descripcion=row.get("descripcion", "").strip(),
                marca=row.get("marca", "").strip().upper(),
                datos_completos=row.get("datos_completos", "").strip().lower() in {"true", "1", "sí", "si"},
            )
    return products


def _clean_text(value: str) -> str:
    value = decode_pdf_glyphs(value).replace("●", "").replace("Þ", "")
    value = re.sub(r"[\x00-\x1f\x7f]", "", value)
    value = re.sub(r"\s+", " ", value).strip(" \t,;")
    return value


def _line_words(words: Sequence[Mapping[str, object]], top: float, tolerance: float = 1.25) -> list[Mapping[str, object]]:
    return sorted(
        (word for word in words if abs(float(word["top"]) - top) <= tolerance),
        key=lambda word: float(word["x0"]),
    )


def _header_for(words: Sequence[Mapping[str, object]], anchor: Mapping[str, object]) -> Mapping[str, object] | None:
    candidates = []
    for word in words:
        if _clean_text(str(word["text"])).lower() != "código":
            continue
        vertical = float(anchor["top"]) - float(word["top"])
        if 0 < vertical <= 95:
            candidates.append((abs(float(anchor["x0"]) - float(word["x0"])), vertical, word))
    return min(candidates, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]


def _segment_bounds(words: Sequence[Mapping[str, object]], header: Mapping[str, object]) -> tuple[float, float]:
    header_top = float(header["top"])
    starts = sorted(
        float(word["x0"]) for word in words
        if _clean_text(str(word["text"])).lower() == "código"
        and abs(float(word["top"]) - header_top) <= 12
    )
    x = float(header["x0"])
    index = min(range(len(starts)), key=lambda i: abs(starts[i] - x))
    left = max(0.0, starts[index] - 5)
    right = 10_000.0 if index == len(starts) - 1 else starts[index + 1] - 5
    return left, right


def _prices_from_row(row: Sequence[Mapping[str, object]]) -> list[Decimal]:
    prices: list[Decimal] = []
    index = 0
    while index < len(row):
        text = _clean_text(str(row[index]["text"]))
        if "$" in text:
            price = parse_decimal_price(text)
            if price is None and index + 1 < len(row):
                gap = float(row[index + 1]["x0"]) - float(row[index]["x1"])
                if gap <= 12:
                    price = parse_decimal_price(str(row[index + 1]["text"]))
                    index += 1
            if price is not None:
                prices.append(price)
        index += 1
    return prices[-3:]


def _header_words(words, header, bounds):
    labels = {"código", "codigo", "clave", "contenido", "caja", "máster", "master", "nc",
              "largo", "ancho", "color", "medidas", "capacidad", "presentación", "presentacion"}
    def is_header(word):
        text = _clean_text(str(word["text"])).lower().strip(".: ")
        return text in labels or text.startswith(("may", "púb", "pub")) or "may" in text
    return sorted((
        word for word in words
        if abs(float(word["top"]) - float(header["top"])) <= 12
        and bounds[0] <= float(word["x0"]) < bounds[1]
        and is_header(word)
    ), key=lambda word: float(word["x0"]))


def _column_prices(words, row, header, bounds):
    headers = _header_words(words, header, bounds)
    public_headers = [word for word in headers if _clean_text(str(word["text"])).lower().startswith(("púb", "pub"))]
    may_headers = [word for word in headers if _clean_text(str(word["text"])).lower().startswith("may")]
    amounts = []
    for index, word in enumerate(row):
        if "$" not in _clean_text(str(word["text"])):
            continue
        price = parse_decimal_price(str(word["text"]))
        if price is None and index + 1 < len(row):
            price = parse_decimal_price(str(row[index + 1]["text"]))
        if price is not None:
            amounts.append((float(word["x0"]), price))
    if not amounts or not public_headers:
        values = _prices_from_row(row)
        return (values + [None, None, None])[:3]
    public_x = float(public_headers[-1]["x0"])
    public = min(amounts, key=lambda item: abs(item[0] - public_x))[1]
    may_x = float(may_headers[0]["x0"]) if may_headers else amounts[0][0]
    may = min(amounts, key=lambda item: abs(item[0] - may_x))[1]
    between = [item for item in amounts if may_x < item[0] < public_x]
    medio = max(between, key=lambda item: item[0])[1] if between else None
    return may, medio, public


def _family_description(
    words: Sequence[Mapping[str, object]], header: Mapping[str, object], bounds: tuple[float, float]
) -> str:
    left, right = bounds
    header_top = float(header["top"])
    candidates = [
        word for word in words
        if left <= float(word["x0"]) < right
        and 12 < header_top - float(word["top"]) <= 180
        and float(word.get("size", word.get("height", 0))) >= 9.5
    ]
    grouped: dict[float, list[Mapping[str, object]]] = {}
    for word in candidates:
        key = round(float(word["top"]), 1)
        grouped.setdefault(key, []).append(word)
    usable: list[tuple[float, str]] = []
    excluded = {"CARACTERÍSTICAS:", "CARACTERÍSTICA:", *KNOWN_BRANDS}
    for top, line in grouped.items():
        text = _clean_text(" ".join(str(word["text"]) for word in sorted(line, key=lambda w: float(w["x0"]))))
        if text and text.upper() not in excluded and "PRECIOS DE ESTE CATÁLOGO" not in text.upper():
            usable.append((top, text))
    if not usable:
        return ""
    usable.sort()
    selected = [usable[-1]]
    if len(usable) > 1 and selected[0][0] - usable[-2][0] <= 13:
        selected.insert(0, usable[-2])
    return _clean_text(" ".join(text for _, text in selected))


def _brand_for(words: Sequence[Mapping[str, object]], header: Mapping[str, object], bounds: tuple[float, float]) -> str:
    left, right = bounds
    header_top = float(header["top"])
    matches = []
    for word in words:
        text = _clean_text(str(word["text"])).upper()
        if text in KNOWN_BRANDS and left <= float(word["x0"]) < right:
            distance = header_top - float(word["top"])
            if 0 < distance <= 190:
                matches.append((distance, text))
    return min(matches, default=(0, ""), key=lambda item: item[0])[1]


def _printed_page(words: Sequence[Mapping[str, object]], physical_page: int) -> int | None:
    candidates = []
    for word in words:
        if float(word["top"]) > 85:
            continue
        text = decode_pdf_glyphs(str(word["text"])).strip()
        if re.fullmatch(r"\d{1,3}", text) and abs(int(text) - physical_page) <= 5:
            candidates.append(int(text))
    return min(candidates, key=lambda value: abs(value - physical_page)) if candidates else None


def _text_is_reliable(value: str) -> bool:
    letters = len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", value))
    digits = len(re.findall(r"\d", value))
    if not value or letters < 4 or letters / max(letters + digits, 1) < 0.65:
        return False
    if re.search(r"[#¯ǟƓƐƜƱƳƴƵƶƷƸƹƺ<>%`]", value):
        return False
    if re.search(r"[a-záéíóúüñ][A-Z]", value):
        return False
    return not re.search(r"(?<=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])\d|\d(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])", value)


def extract_products_from_words(
    words: Sequence[Mapping[str, object]],
    master: Mapping[str, MasterProduct],
    physical_page: int,
    column_mode: bool = False,
) -> list[PdfProduct]:
    known_codes = set(master)
    results: list[PdfProduct] = []
    seen: set[str] = set()
    printed_page = _printed_page(words, physical_page)
    for anchor in words:
        code = normalize_code_token(str(anchor["text"]), known_codes)
        if not code or code in seen:
            continue
        header = _header_for(words, anchor)
        if header is None:
            continue
        bounds = _segment_bounds(words, header)
        row = [
            word for word in _line_words(words, float(anchor["top"]))
            if bounds[0] <= float(word["x0"]) < bounds[1]
        ]
        if not row:
            continue
        anchor_index = min(range(len(row)), key=lambda i: abs(float(row[i]["x0"]) - float(anchor["x0"])))
        after_code = row[anchor_index + 1:]
        clave = ""
        clave_word: Mapping[str, object] | None = None
        if column_mode:
            start_index = None
            for index, word in enumerate(after_code):
                candidate = _clean_text(str(word["text"])).strip("*•")
                if candidate and "$" not in candidate and re.search(r"[A-Z]", candidate, re.I):
                    start_index = index
                    clave_word = word
                    break
            if start_index is not None:
                parts = [_clean_text(str(after_code[start_index]["text"])).strip("*•")]
                previous = after_code[start_index]
                for word in after_code[start_index + 1:]:
                    candidate = _clean_text(str(word["text"])).strip("*•")
                    gap = float(word["x0"]) - float(previous["x1"])
                    if gap > 2.5 or not re.fullmatch(r"[A-Z0-9/-]+", candidate, re.I):
                        break
                    parts.append(candidate)
                    previous = word
                clave = "".join(parts)
        if not clave:
            for word in after_code:
                candidate = _clean_text(str(word["text"])).strip("*•")
                if candidate and "$" not in candidate and re.search(r"[A-Z]", candidate, re.I):
                    clave, clave_word = candidate, word
                    break
        mayoreo, medio, publico = _column_prices(words, row, header, bounds) if column_mode else tuple((_prices_from_row(row) + [None, None, None])[:3])
        first_price_x = min((float(word["x0"]) for word in row if "$" in _clean_text(str(word["text"]))), default=10_000)
        package_headers = [
            float(word["x0"]) for word in words
            if abs(float(word["top"]) - float(header["top"])) <= 12
            and bounds[0] <= float(word["x0"]) < bounds[1]
            and _clean_text(str(word["text"])).lower() in {"caja", "máster", "master"}
        ]
        presentation_end = min([first_price_x, *package_headers])
        presentation_start = float(clave_word["x1"]) if clave_word else float(anchor["x1"])
        presentation = _clean_text(" ".join(
            str(word["text"]) for word in row
            if presentation_start < float(word["x0"]) < presentation_end
        ))
        family = _family_description(words, header, bounds)
        family_reliable = _text_is_reliable(family)
        description = family if family_reliable else ""
        presentation_prefix = " ".join(presentation.lower().split()[:2])
        if description and presentation and presentation.lower() not in family.lower() and presentation_prefix not in family.lower():
            description = _clean_text(f"{family}, {presentation}")
        brand = _brand_for(words, header, bounds)
        previous = master[code]
        key_matches = bool(clave) and clave.upper() == previous.clave.upper()
        key_structural = bool(re.fullmatch(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)*", clave)) and any(ch.isalpha() for ch in clave)
        confidence = "alta" if key_structural and family_reliable and publico is not None else "media" if key_structural and (family_reliable or publico is not None) else "baja"
        review = confidence != "alta"
        results.append(PdfProduct(
            codigo_truper=code,
            clave=clave,
            descripcion=description,
            descripcion_familia=family,
            presentacion=presentation,
            marca=brand,
            precio_catalogo_mayoreo=mayoreo,
            precio_catalogo_medio_mayoreo=medio,
            precio_catalogo_publico=publico,
            pagina_catalogo=printed_page,
            estado_previo="enriquecido" if previous.datos_completos else "pendiente",
            confianza_extraccion=confidence,
            clave_confianza="ALTA" if key_structural else "BAJA",
            requiere_revision=review,
        ))
        seen.add(code)
    return results


def extract_products_v2(words, master, physical_page, font_maps):
    recovered = []
    for word in words:
        item = dict(word)
        item["text"] = decode_cids_with_font(str(word["text"]), str(word.get("fontname", "")), font_maps)
        recovered.append(item)
    return extract_products_from_words(recovered, master, physical_page, column_mode=True)


def extract_all_products_v2(words, master, physical_page, font_maps):
    recovered = []
    candidates = {}
    for word in words:
        item = dict(word)
        item["text"] = decode_cids_with_font(str(word["text"]), str(word.get("fontname", "")), font_maps)
        recovered.append(item)
        code = normalize_code_token(str(item["text"]))
        if code and code not in master:
            candidates[code] = MasterProduct(code, "", "", "", False)
    augmented = dict(master)
    augmented.update(candidates)
    return extract_products_from_words(recovered, augmented, physical_page, column_mode=True)


def save_pdf_sample_csv(products: Iterable[PdfProduct], destination: str | Path) -> int:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    unique: dict[str, PdfProduct] = {}
    for product in products:
        unique.setdefault(product.codigo_truper, product)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for product in unique.values():
            row = asdict(product)
            for field in ("precio_catalogo_mayoreo", "precio_catalogo_medio_mayoreo", "precio_catalogo_publico"):
                row[field] = "" if row[field] is None else format(row[field], "f")
            row["requiere_revision"] = str(row["requiere_revision"]).lower()
            writer.writerow(row)
    return len(unique)
