import csv
import sqlite3
from decimal import Decimal

import pytest

from ferreteria_core import Database
from ferreteria_core.money import centavos_a_decimal, decimal_a_centavos
from ferreteria_core.services import InitialInventoryService, InventoryService, ProductService, importar_catalogo_truper, respaldar_base


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "catalog.csv"
    fields = ["codigo_truper","codigo_barras","clave","descripcion","descripcion_familia","marca","categoria","presentacion","precio_catalogo_publico","precio_venta","datos_completos","confianza_extraccion","requiere_revision"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        writer.writerow(dict.fromkeys(fields, "") | {"codigo_truper":"10001","clave":"MAR-1","descripcion":"Martillo Truper","marca":"TRUPER","precio_catalogo_publico":"35.50","precio_venta":"35.50","datos_completos":"True","requiere_revision":"False"})
        writer.writerow(dict.fromkeys(fields, "") | {"codigo_truper":"10002","requiere_revision":"True"})
    return path


def imported(db, catalog):
    importar_catalogo_truper(db, catalog)
    return ProductService(db)


def test_crear_esquema(db):
    with db.connect() as c:
        assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {"productos","movimientos_inventario","schema_migrations"}


def test_importar_catalogo(db, catalog):
    assert importar_catalogo_truper(db, catalog) == {"leidos":2,"insertados":2,"actualizados":0}


def test_reimportar_no_duplica(db, catalog):
    importar_catalogo_truper(db, catalog); stats = importar_catalogo_truper(db, catalog)
    with db.connect() as c: assert c.execute("SELECT count(*) FROM productos").fetchone()[0] == 2
    assert stats["actualizados"] == 2


def test_reimportar_preserva_precio_local(db, catalog):
    products = imported(db, catalog); product = products.buscar_exacto("codigo_truper", "10001")
    with db.connect() as c: c.execute("UPDATE productos SET precio_venta=999 WHERE id=?", (product.id,))
    importar_catalogo_truper(db, catalog)
    assert products.get(product.id).precio_venta == 999


def test_reimportar_preserva_barcode_y_existencia(db, catalog):
    products = imported(db, catalog); product = products.buscar_exacto("codigo_truper", "10001")
    products.vincular_codigo_barras(product.id, "7501234567890"); InventoryService(db).registrar_entrada(product.id, 4)
    importar_catalogo_truper(db, catalog); product = products.get(product.id)
    assert (product.codigo_barras, product.existencia) == ("7501234567890", 4)


def test_producto_externo(db):
    product = ProductService(db).crear_producto_externo("7500000000001", "Tornillo externo", Decimal("8.50"), 3)
    assert not product.es_truper and product.codigo_truper is None and product.precio_venta == 850 and product.existencia == 3


def test_codigo_barras_unico(db):
    service = ProductService(db); service.crear_producto_externo("7500000000001", "Uno", Decimal("1"), 0)
    with pytest.raises(ValueError): service.crear_producto_externo("7500000000001", "Dos", Decimal("1"), 0)


def test_vincular_barcode(db, catalog):
    service = imported(db, catalog); p = service.buscar_exacto("codigo_truper", "10001")
    assert service.vincular_codigo_barras(p.id, "7501234567890").codigo_barras == "7501234567890"
    with pytest.raises(ValueError): service.vincular_codigo_barras(p.id, "7501234567891")


def test_buscar_barcode(db):
    s = ProductService(db); p = s.crear_producto_externo("7500000000001", "Uno", Decimal("1"), 0)
    assert s.buscar_exacto("codigo_barras", "7500000000001").id == p.id


def test_buscar_codigo_truper(db, catalog):
    assert imported(db, catalog).buscar_exacto("codigo_truper", "10001").clave == "MAR-1"


def test_buscar_clave(db, catalog):
    assert imported(db, catalog).buscar_exacto("clave", "MAR-1").codigo_truper == "10001"


def test_buscar_descripcion_sin_distinguir_mayusculas(db, catalog):
    assert len(imported(db, catalog).buscar(descripcion="mARTILLO")) == 1


def test_buscar_marca_y_revision(db, catalog):
    s = imported(db, catalog)
    assert len(s.buscar(marca="truper")) == 1 and len(s.buscar(requiere_revision=True)) == 1


def test_registrar_entrada(db):
    p = ProductService(db).crear_producto_externo("7500000000001", "Uno", Decimal("1"), 0)
    InventoryService(db).registrar_entrada(p.id, 5, "Compra")
    assert ProductService(db).get(p.id).existencia == 5


def test_ajustar_existencia(db):
    p = ProductService(db).crear_producto_externo("7500000000001", "Uno", Decimal("1"), 5)
    InventoryService(db).ajustar_existencia(p.id, 2, "Conteo")
    assert ProductService(db).get(p.id).existencia == 2


def test_impedir_existencia_negativa(db):
    p = ProductService(db).crear_producto_externo("7500000000001", "Uno", Decimal("1"), 0)
    with pytest.raises(ValueError): InventoryService(db).ajustar_existencia(p.id, -1, "No")
    with pytest.raises(sqlite3.IntegrityError), db.connect() as c: c.execute("UPDATE productos SET existencia=-1 WHERE id=?", (p.id,))


def test_movimiento_correcto(db):
    p = ProductService(db).crear_producto_externo("7500000000001", "Uno", Decimal("1"), 0)
    InventoryService(db).registrar_entrada(p.id, 4, "Factura")
    with db.connect() as c: row = c.execute("SELECT * FROM movimientos_inventario WHERE producto_id=?", (p.id,)).fetchone()
    assert (row["tipo"],row["cantidad"],row["existencia_anterior"],row["existencia_nueva"],row["nota"]) == ("ENTRADA",4,0,4,"Factura")


@pytest.mark.parametrize(("value","expected"), [(Decimal("35.00"),3500),("8.50",850),(140,14000)])
def test_decimal_a_centavos(value, expected): assert decimal_a_centavos(value) == expected


def test_centavos_a_decimal(): assert centavos_a_decimal(850) == Decimal("8.5")


def test_backup_sqlite(db, tmp_path):
    target = respaldar_base(db, tmp_path / "backups")
    with sqlite3.connect(target) as c: assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 9


def test_flujo_inventario_inicial_atomico(db, catalog):
    products = imported(db, catalog); product = products.buscar_exacto("codigo_truper", "10001")
    flow = InitialInventoryService(db)
    saved = flow.vincular_y_capturar(product.id, "7501234567890", 7)
    assert saved.existencia == 7 and flow.resolver_escaneo("7501234567890").id == product.id
