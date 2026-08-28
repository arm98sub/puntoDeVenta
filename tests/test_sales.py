from decimal import Decimal

import pytest

from ferreteria_core import Database
from ferreteria_core.services import Cart, ProductService, SalesService, respaldar_base


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "ventas.db"); database.migrate(); return database


@pytest.fixture
def make_product(db):
    counter = 0
    def make(description="Martillo", price="51.00", stock=10):
        nonlocal counter; counter += 1
        return ProductService(db).crear_producto_externo(f"750000000{counter:04d}", description,
                                                          Decimal(price) if price is not None else Decimal("1"), stock)
    return make


def sell(service, product, quantity=1, **kwargs):
    return service.crear_venta([{"producto_id":product.id,"cantidad":quantity}], kwargs.pop("metodo_pago", "EFECTIVO"),
                               kwargs.pop("efectivo_recibido", Decimal("1000")), **kwargs)


def test_migracion_ventas(db):
    with db.connect() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ventas", "detalle_venta"} <= names


def test_carrito_vacio(db):
    cart = Cart(db); assert cart.cantidad_articulos == 0 and cart.total_centavos == 0
    with pytest.raises(ValueError, match="vacío"): SalesService(db).crear_venta([], "EFECTIVO", Decimal("1"))


def test_agregar_producto(db, make_product):
    p = make_product(); item = Cart(db).agregar_producto(p.id)
    assert item.producto_id == p.id and item.cantidad == 1


def test_mismo_producto_incrementa(db, make_product):
    p = make_product(); cart = Cart(db)
    cart.agregar_por_barcode(p.codigo_barras); cart.agregar_por_barcode(p.codigo_barras); cart.incrementar(p.id)
    assert len(cart.items) == 1 and cart.cantidad_articulos == 3


def test_modificar_y_quitar_producto(db, make_product):
    p = make_product(); cart = Cart(db); cart.agregar_producto(p.id, 3); cart.decrementar(p.id); cart.establecer_cantidad(p.id, 1); cart.eliminar(p.id)
    assert not cart.items


def test_vaciar_carrito(db, make_product):
    cart = Cart(db); cart.agregar_producto(make_product().id); cart.vaciar(); assert cart.cantidad_articulos == 0


def test_producto_sin_precio(db, make_product):
    p = make_product()
    with db.connect() as c: c.execute("UPDATE productos SET precio_venta=NULL WHERE id=?", (p.id,))
    with pytest.raises(ValueError, match="no tiene precio"): Cart(db).agregar_producto(p.id)


def test_carrito_cantidad_y_total(db, make_product):
    p = make_product(price="51.00"); cart = Cart(db); cart.agregar_producto(p.id, 2)
    assert cart.cantidad_articulos == 2 and cart.total == Decimal("102")


def test_carrito_avisa_stock(db, make_product):
    from ferreteria_core.services import InsufficientStockError
    p = make_product(stock=1); cart = Cart(db)
    with pytest.raises(InsufficientStockError): cart.agregar_producto(p.id, 2)
    assert cart.cantidad_articulos == 0


def test_venta_simple(db, make_product):
    sale = sell(SalesService(db), make_product())
    assert sale.estado == "COMPLETADA" and sale.total_centavos == 5100


def test_venta_varios_productos(db, make_product):
    a, b = make_product(price="10"), make_product(price="20")
    sale = SalesService(db).crear_venta([{"producto_id":a.id,"cantidad":2},{"producto_id":b.id,"cantidad":3}], "TARJETA")
    assert len(sale.detalles) == 2 and sale.total_centavos == 8000


def test_detalle_y_snapshots_correctos(db, make_product):
    p = make_product(description="Pinza"); sale = sell(SalesService(db), p, 2)
    detail = sale.detalles[0]
    assert (detail.producto_id,detail.descripcion_snapshot,detail.codigo_barras_snapshot,detail.cantidad,detail.precio_unitario_centavos,detail.subtotal_centavos) == (p.id,"Pinza",p.codigo_barras,2,5100,10200)


def test_subtotal_descuento_total(db, make_product):
    sale = sell(SalesService(db), make_product(price="50"), 2, efectivo_recibido=Decimal("100"), descuento=Decimal("30"))
    assert (sale.subtotal_centavos,sale.descuento_centavos,sale.total_centavos) == (10000,3000,7000)


def test_descuento_invalido(db, make_product):
    with pytest.raises(ValueError, match="descuento"): sell(SalesService(db), make_product(price="5"), descuento=Decimal("6"))


def test_efectivo_y_cambio(db, make_product):
    sale = sell(SalesService(db), make_product(), efectivo_recibido=Decimal("100"))
    assert (sale.efectivo_recibido_centavos,sale.cambio_centavos) == (10000,4900)


def test_efectivo_obligatorio_e_insuficiente(db, make_product):
    p = make_product(); service = SalesService(db)
    with pytest.raises(ValueError, match="obligatorio"): service.crear_venta([{"producto_id":p.id,"cantidad":1}], "EFECTIVO")
    with pytest.raises(ValueError, match="insuficiente"): sell(service, p, efectivo_recibido=Decimal("50"))


@pytest.mark.parametrize("method", ["TRANSFERENCIA", "TARJETA", "OTRO"])
def test_pago_no_efectivo_sin_cambio(db, make_product, method):
    sale = SalesService(db).crear_venta([{"producto_id":make_product().id,"cantidad":1}], method, Decimal("999"))
    assert sale.efectivo_recibido_centavos is None and sale.cambio_centavos is None


def test_metodo_invalido(db, make_product):
    with pytest.raises(ValueError, match="Método"): sell(SalesService(db), make_product(), metodo_pago="CHEQUE")


def test_stock_suficiente_y_descuento_inventario(db, make_product):
    p = make_product(stock=3); sell(SalesService(db), p, 2)
    assert ProductService(db).get(p.id).existencia == 1


def test_stock_insuficiente_sin_efectos(db, make_product):
    p = make_product(stock=1)
    with pytest.raises(ValueError, match="disponible 1, solicitado 5"): sell(SalesService(db), p, 5)
    with db.connect() as c:
        assert c.execute("SELECT count(*) FROM ventas").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM detalle_venta").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM movimientos_inventario WHERE tipo='VENTA'").fetchone()[0] == 0


def test_movimiento_venta_negativo(db, make_product):
    p = make_product(stock=5); sale = sell(SalesService(db), p, 2)
    with db.connect() as c: row = c.execute("SELECT * FROM movimientos_inventario WHERE tipo='VENTA'").fetchone()
    assert (row["cantidad"],row["existencia_anterior"],row["existencia_nueva"],row["referencia"]) == (-2,5,3,f"VENTA:{sale.folio}")


def test_rollback_critico_dos_productos(db, make_product):
    a, b = make_product(stock=10), make_product(stock=1); service = SalesService(db)
    with pytest.raises(ValueError): service.crear_venta([{"producto_id":a.id,"cantidad":2},{"producto_id":b.id,"cantidad":5}], "EFECTIVO", Decimal("1000"))
    with db.connect() as c:
        assert c.execute("SELECT existencia FROM productos WHERE id=?",(a.id,)).fetchone()[0] == 10
        assert c.execute("SELECT existencia FROM productos WHERE id=?",(b.id,)).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM ventas").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM detalle_venta").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM movimientos_inventario WHERE tipo='VENTA'").fetchone()[0] == 0


def test_precio_y_nombre_historicos(db, make_product):
    p = make_product(description="Original", price="51"); sale = sell(SalesService(db), p)
    with db.connect() as c: c.execute("UPDATE productos SET descripcion='Nuevo',precio_venta=9999 WHERE id=?",(p.id,))
    detail = SalesService(db).obtener_por_id(sale.id).detalles[0]
    assert detail.descripcion_snapshot == "Original" and detail.precio_unitario_centavos == 5100


def test_folios_unicos_secuenciales(db, make_product):
    service = SalesService(db); first = sell(service, make_product()); second = sell(service, make_product())
    assert (first.folio, second.folio) == ("V-000001", "V-000002")


def test_folio_no_consumido_tras_fallo(db, make_product):
    service = SalesService(db); bad = make_product(stock=0)
    with pytest.raises(ValueError): sell(service, bad)
    assert sell(service, make_product()).folio == "V-000001"


def test_consultar_por_folio_y_listar(db, make_product):
    service = SalesService(db); sale = sell(service, make_product())
    assert service.obtener_por_folio(sale.folio).id == sale.id and service.ultimas_ventas(1)[0].folio == sale.folio


def test_listar_por_rango(db, make_product):
    service = SalesService(db); sale = sell(service, make_product())
    assert service.ventas_por_rango("2000-01-01", "2999-12-31") [0].id == sale.id


def test_cancelar_devuelve_inventario_y_registra(db, make_product):
    p = make_product(stock=5); service = SalesService(db); sale = sell(service, p, 2)
    cancelled = service.cancelar_venta(sale.id, "Cliente desistió")
    with db.connect() as c: row = c.execute("SELECT * FROM movimientos_inventario WHERE tipo='DEVOLUCION'").fetchone()
    assert cancelled.estado == "CANCELADA" and ProductService(db).get(p.id).existencia == 5
    assert (row["cantidad"],row["referencia"]) == (2,f"CANCELACION:{sale.folio}")


def test_impedir_doble_cancelacion(db, make_product):
    service = SalesService(db); sale = sell(service, make_product()); service.cancelar_venta(sale.id, "Uno")
    with pytest.raises(ValueError, match="COMPLETADA"): service.cancelar_venta(sale.id, "Dos")


def test_cancelar_producto_inactivo(db, make_product):
    p = make_product(); service = SalesService(db); sale = sell(service, p)
    with db.connect() as c: c.execute("UPDATE productos SET activo=0 WHERE id=?",(p.id,))
    assert service.cancelar_venta(sale.id, "Devolución").estado == "CANCELADA"


def test_producto_inactivo_rechazado(db, make_product):
    p = make_product()
    with db.connect() as c: c.execute("UPDATE productos SET activo=0 WHERE id=?",(p.id,))
    with pytest.raises(ValueError, match="inactivo"): sell(SalesService(db), p)


def test_cantidad_cero_rechazada(db, make_product):
    p = make_product()
    with pytest.raises(ValueError, match="positivos"): SalesService(db).crear_venta([{"producto_id":p.id,"cantidad":0}], "TARJETA")


def test_backup_incluye_ventas(db, make_product, tmp_path):
    sell(SalesService(db), make_product()); target = respaldar_base(db, tmp_path / "backup")
    backup = Database(target)
    with backup.connect() as c: assert c.execute("SELECT count(*) FROM ventas").fetchone()[0] == 1
