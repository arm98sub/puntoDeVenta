from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ferreteria_core.money import centavos_a_decimal, decimal_a_centavos
from ferreteria_core.quantity import formato_cantidad,formato_granel


def moneda(centavos: int | None) -> str:
    if centavos is None:
        return "—"
    return f"${centavos_a_decimal(centavos):,.2f}"


def nombre_producto(product) -> str:
    return product.descripcion or product.clave or (
        f"Producto Truper {product.codigo_truper}" if product.codigo_truper else f"Producto {product.id}"
    )


def cantidad_producto(product, value=None) -> str:
    if product.tipo_venta=="GRANEL":return formato_granel(product.existencia_granel_mg if value is None else value,product.unidad_granel or "PESO")
    return formato_cantidad("UNIDAD",unidades=product.existencia if value is None else value)


def precio_producto(product) -> str:
    value=moneda(product.precio_venta)
    suffix="L" if product.unidad_granel=="VOLUMEN" else "kg"
    return f"{value} / {suffix}" if product.tipo_venta=="GRANEL" and product.precio_venta is not None else value


def parsear_importe(texto: str, *, nombre="Importe", vacio_cero=True) -> int:
    clean = (texto or "").strip().replace("$", "").replace(",", "")
    if not clean and vacio_cero:
        return 0
    try:
        return decimal_a_centavos(Decimal(clean))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{nombre} inválido") from exc


@dataclass(frozen=True)
class PagoCalculado:
    total_centavos: int
    recibido_centavos: int | None
    cambio_centavos: int | None
    puede_confirmar: bool
    mensaje: str | None = None


def calcular_pago(total_centavos: int, metodo: str, recibido_texto="") -> PagoCalculado:
    method = metodo.strip().upper()
    if method != "EFECTIVO":
        return PagoCalculado(total_centavos, None, None, True)
    try:
        received = parsear_importe(recibido_texto, nombre="Efectivo recibido", vacio_cero=False)
    except ValueError as exc:
        return PagoCalculado(total_centavos, None, None, False, str(exc))
    change = received - total_centavos
    if change < 0:
        return PagoCalculado(total_centavos, received, None, False, "El efectivo recibido es insuficiente")
    return PagoCalculado(total_centavos, received, change, True)


def limpiar_estado_venta(cart, discount_widget=None, barcode_widget=None):
    cart.vaciar()
    if discount_widget is not None:
        discount_widget.setText("0.00")
    if barcode_widget is not None:
        barcode_widget.clear()
