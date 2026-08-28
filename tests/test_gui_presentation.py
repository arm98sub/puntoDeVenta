from decimal import Decimal
from types import SimpleNamespace

import pytest

from ferreteria_core import Database
from ferreteria_core.services import Cart, ProductService
from ferreteria_gui.presentation import calcular_pago, limpiar_estado_venta, moneda, nombre_producto, parsear_importe


class FakeLineEdit:
    def __init__(self,value=""): self.value=value
    def setText(self,value): self.value=value
    def clear(self): self.value=""


def test_formato_moneda_mxn():
    assert moneda(125050) == "$1,250.50" and moneda(0) == "$0.00" and moneda(None) == "—"


@pytest.mark.parametrize(("description","key","code","expected"), [
    ("Silicón", "SIL-85T", "17562", "Silicón"),
    (None, "SIL-85T", "17562", "SIL-85T"),
    (None, None, "17562", "Producto Truper 17562"),
])
def test_representacion_producto(description,key,code,expected):
    assert nombre_producto(SimpleNamespace(descripcion=description,clave=key,codigo_truper=code,id=1)) == expected


def test_integracion_carrito_por_barcode(tmp_path):
    db=Database(tmp_path/"gui.db"); db.migrate(); product=ProductService(db).crear_producto_externo("7501206683729","Silicón",Decimal("51"),10)
    cart=Cart(db); cart.agregar_por_barcode("7501206683729"); cart.agregar_por_barcode("7501206683729")
    assert len(cart.items)==1 and cart.items[0].producto_id==product.id and cart.cantidad_articulos==2


def test_limpieza_tras_venta(tmp_path):
    db=Database(tmp_path/"gui.db"); db.migrate(); product=ProductService(db).crear_producto_externo("7501206683729","Silicón",Decimal("51"),10)
    cart=Cart(db); cart.agregar_producto(product.id); discount=FakeLineEdit("5"); barcode=FakeLineEdit("750")
    limpiar_estado_venta(cart,discount,barcode)
    assert cart.cantidad_articulos==0 and discount.value=="0.00" and barcode.value==""


def test_pago_efectivo_y_cambio():
    payment=calcular_pago(5100,"EFECTIVO","100.00")
    assert payment.puede_confirmar and payment.recibido_centavos==10000 and payment.cambio_centavos==4900


def test_pago_efectivo_insuficiente():
    payment=calcular_pago(5100,"EFECTIVO","50")
    assert not payment.puede_confirmar and payment.cambio_centavos is None and "insuficiente" in payment.mensaje


def test_pago_no_efectivo_ignora_recibido():
    payment=calcular_pago(5100,"TARJETA","100")
    assert payment.puede_confirmar and payment.recibido_centavos is None and payment.cambio_centavos is None


def test_parsear_importe_sin_float():
    assert parsear_importe("$1,250.50") == 125050
    with pytest.raises(ValueError): parsear_importe("abc")
