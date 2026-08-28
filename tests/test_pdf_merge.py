from decimal import Decimal

from truper_catalog.pdf_catalog import PdfProduct
from truper_catalog.pdf_merge import choose_pdf_product, merge_master_row
from truper_catalog.pdf_checkpoint import load_checkpoint, save_checkpoint


def pdf(**changes):
    data = dict(
        codigo_truper="10001", clave="PDF-1", descripcion="Descripción PDF",
        descripcion_familia="Familia", presentacion="1 pza", marca="TRUPER",
        precio_catalogo_mayoreo=Decimal("10"), precio_catalogo_medio_mayoreo=Decimal("11"),
        precio_catalogo_publico=Decimal("12"), pagina_catalogo=10, estado_previo="pendiente",
        confianza_extraccion="alta", clave_confianza="ALTA", requiere_revision=False,
    )
    data.update(changes)
    return PdfProduct(**data)


def master(**changes):
    data = dict(codigo_truper="10001", clave="WEB-1", descripcion="Descripción existente",
                marca="TRUPER", categoria="Categoría", datos_completos="True")
    data.update(changes)
    return data


def test_merge_preserves_existing_reliable_key_and_description():
    row, reasons = merge_master_row(master(), pdf())
    assert row["clave"] == "WEB-1"
    assert row["descripcion"] == "Descripción existente"
    assert "discrepancia_clave" in reasons


def test_public_price_initializes_independent_sale_price():
    row, _ = merge_master_row(master(), pdf(precio_catalogo_publico=Decimal("140.00")))
    assert row["precio_catalogo_publico"] == "140.00"
    assert row["precio_venta"] == "140.00"


def test_not_found_product_is_kept_and_marked():
    row, reasons = merge_master_row(master(), None)
    assert row["codigo_truper"] == "10001"
    assert row["encontrado_en_pdf"] == "False"
    assert "no_encontrado_en_pdf" in reasons


def test_incomplete_master_can_receive_pdf_description():
    row, _ = merge_master_row(master(clave="PDF-1", descripcion="", datos_completos="False"), pdf())
    assert row["descripcion"] == "Descripción PDF"
    assert row["datos_completos"] == "True"


def test_ambiguous_key_does_not_replace_master():
    row, reasons = merge_master_row(master(clave="CF-1/2P"), pdf(clave="CF-12P"))
    assert row["clave"] == "CF-1/2P"
    assert "discrepancia_clave" in reasons


def test_best_checkpoint_product_wins_without_duplication():
    low = pdf(confianza_extraccion="baja", requiere_revision=True)
    high = pdf(confianza_extraccion="alta")
    chosen = choose_pdf_product(low, high)
    assert chosen is high
    assert choose_pdf_product(chosen, low) is high


def test_checkpoint_can_resume(monkeypatch, tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    state = {"completed_pages": [1, 2], "products": {"10001": pdf()}, "errors": [], "started_at": 1.0}
    save_checkpoint(checkpoint, state)
    loaded = load_checkpoint(checkpoint, False)
    assert loaded["completed_pages"] == [1, 2]
    assert loaded["products"]["10001"].clave == "PDF-1"
