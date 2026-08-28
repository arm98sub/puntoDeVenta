from truper_catalog.extractor import TruperExtractor, detect_brand, normalize_brand, normalize_text
from truper_catalog.models import Product
from truper_catalog.storage import save_csv
from truper_catalog.enrichment import enriquecer_producto


def test_detect_brand_only_when_explicit_at_end():
    assert detect_brand("Martillo tubular, TRUPER") == "TRUPER"
    assert detect_brand("Demoledor, TRUPER EXPERT") == "TRUPER EXPERT"
    assert detect_brand("Producto sin marca explícita") == ""


def test_csv_removes_duplicate_code_and_sku(tmp_path):
    product = Product("16702", "MTR-16", "Martillo, TRUPER", "TRUPER", "Martillos")
    destination = tmp_path / "sample.csv"
    assert save_csv([product, product], destination) == 1
    text = destination.read_text(encoding="utf-8-sig")
    assert text.count("16702") == 1
    assert "codigo,codigo_barras,clave,descripcion,marca,categoria" in text


def test_search_page_parser_without_network(monkeypatch):
    html = '''<table><tr class="kpi-track-click" data-documentid="16702" data-objectname="MTR-16">
      <td data-source="martillos-truper-280.html">1</td>
      <td><img src="/marcas/TRUPER.svg"></td><td>16702</td><td>MTR-16</td>
      <td><a><div class="description-search">Martillo tubular</div><div class="hidden">ruido</div></a></td></tr></table>
      <div class="pagination"><a href="?palabra=truper&page=3">3</a></div>'''
    extractor = TruperExtractor(pause_seconds=0)

    class Response:
        text = html

        def raise_for_status(self):
            return None

    monkeypatch.setattr(extractor, "_request", lambda *a, **k: Response())
    monkeypatch.setattr(extractor, "_category_from_page", lambda url: "Martillos")
    products, last_page = extractor.search_page("truper", 1)
    assert last_page == 3
    assert products == [Product("16702", "MTR-16", "Martillo tubular", "TRUPER", "Martillos")]


def test_barcode_is_optional_and_not_derived():
    product = Product("16702", "MTR-16", "Martillo", "TRUPER", "Martillos")
    assert product.codigo == "16702"
    assert product.codigo_barras == ""


def test_normalization_preserves_identifiers_and_accents():
    assert normalize_text("  Martillo   geológico  ") == "Martillo geológico"
    assert normalize_brand("truper-expert") == "TRUPER EXPERT"


def test_single_product_enrichment_does_not_process_lists(monkeypatch):
    expected = Product("16702", "MTR-16", "Martillo", "TRUPER", "Martillos")
    monkeypatch.setattr(TruperExtractor, "search", lambda self, code, limit=5: [expected])
    assert enriquecer_producto("16702", delay=1) == expected


def test_single_product_enrichment_rejects_empty_code():
    try:
        enriquecer_producto("  ")
    except ValueError:
        pass
    else:
        raise AssertionError("Debió rechazar un código vacío")
