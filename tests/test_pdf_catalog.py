from decimal import Decimal

from truper_catalog.pdf_catalog import (
    MasterProduct,
    decode_pdf_glyphs,
    extract_products_from_words,
    normalize_code_token,
    parse_decimal_price,
)
from truper_catalog.pdf_fonts import decode_cids_with_font


def word(text, x0, top, x1=None, size=7):
    return {"text": text, "x0": x0, "x1": x1 if x1 is not None else x0 + 10, "top": top, "size": size, "height": size}


def fixture_words(code="14991*", public="$ 35"):
    public_parts = [word("$", 200, 100), word(public.replace("$", "").strip(), 204, 100)] if public else []
    return [
        word("18", 45, 35), word("TRUPER", 45, 45, size=10),
        word("Aceites", 45, 60, size=10), word("sintéticos", 80, 60, size=10),
        word("de", 135, 60, size=10), word("2", 150, 60, size=10), word("tiempos", 160, 60, size=10),
        word("Código", 45, 90), word("Clave", 80, 90), word("Contenido", 115, 90),
        word("May.", 150, 90), word("½ May.", 175, 90), word("Púb.", 200, 90),
        word(code, 45, 100, 65), word("ACES-2", 80, 100, 105),
        word("60", 115, 100), word("ml", 127, 100),
        word("$", 150, 100), word("29", 154, 100),
        word("$", 175, 100), word("32", 179, 100), *public_parts,
    ]


MASTER = {"14991": MasterProduct("14991", "ACES-2", "", "", False)}


def test_known_product_and_starred_code_are_normalized():
    product = extract_products_from_words(fixture_words(), MASTER, 20)[0]
    assert product.codigo_truper == "14991"
    assert product.clave == "ACES-2"
    assert product.descripcion_familia == "Aceites sintéticos de 2 tiempos"
    assert product.pagina_catalogo == 18


def test_stylized_and_cid_digits_are_decoded():
    assert decode_pdf_glyphs("(cid:91)(cid:89)(cid:92)(cid:95)(cid:93)(cid:93)") == "102533"
    assert normalize_code_token(r"[Y\_]]Þ", {"102533"}) == "102533"


def test_public_price_is_not_confused_with_mayoreo():
    product = extract_products_from_words(fixture_words(), MASTER, 20)[0]
    assert product.precio_catalogo_mayoreo == Decimal("29")
    assert product.precio_catalogo_medio_mayoreo == Decimal("32")
    assert product.precio_catalogo_publico == Decimal("35")


def test_missing_public_price_requires_review():
    product = extract_products_from_words(fixture_words(public=""), MASTER, 20)[0]
    assert product.precio_catalogo_publico is None
    assert product.requiere_revision is True


def test_unknown_code_is_ignored():
    assert extract_products_from_words(fixture_words(code="99999"), MASTER, 20) == []


def test_price_is_decimal_and_commas_are_normalized():
    value = parse_decimal_price("$1,234.50")
    assert value == Decimal("1234.50")
    assert isinstance(value, Decimal)


def test_cid_key_parts_are_recovered_without_ground_truth():
    maps = {"ToolboxClose2-Regular": {41: "V", 21: "G"}}
    assert decode_cids_with_font(
        "(cid:41)(cid:21)C-562", "ABCDEF+ToolboxClose2-Regular", maps
    ) == "VGC-562"


def test_multiple_tables_keep_their_own_public_price():
    words = fixture_words()
    words += [
        word("Código", 260, 90), word("Clave", 295, 90), word("Púb.", 410, 90),
        word("15000", 260, 100), word("OTRA-1", 295, 100), word("$", 410, 100), word("999", 414, 100),
    ]
    product = extract_products_from_words(words, MASTER, 20, column_mode=True)[0]
    assert product.precio_catalogo_publico == Decimal("35")


def test_split_key_is_joined_in_column_mode():
    words = fixture_words()
    for item in words:
        if item["text"] == "ACES-2":
            item["text"] = "ACES-"
            item["x1"] = 96
            break
    words.append(word("2", 97, 100, 101))
    product = extract_products_from_words(words, MASTER, 20, column_mode=True)[0]
    assert product.clave == "ACES-2"
