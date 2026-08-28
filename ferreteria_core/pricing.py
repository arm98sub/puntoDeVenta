from decimal import Decimal,InvalidOperation,ROUND_HALF_UP


def normalizar_porcentaje(value):
    if value is None or str(value).strip()=="":return None
    try:result=Decimal(str(value).strip().replace("%",""))
    except InvalidOperation as exc:raise ValueError("Ganancia inválida") from exc
    if not result.is_finite() or result < 0:raise ValueError("La ganancia debe ser un porcentaje no negativo")
    result=result.quantize(Decimal("0.0001"),rounding=ROUND_HALF_UP)
    return format(result,"f").rstrip("0").rstrip(".") or "0"


def precio_venta_sugerido(precio_proveedor_centavos,porcentaje):
    if precio_proveedor_centavos is None or porcentaje is None:return None
    if not isinstance(precio_proveedor_centavos,int) or precio_proveedor_centavos<0:raise ValueError("Precio proveedor inválido")
    pct=Decimal(normalizar_porcentaje(porcentaje));result=Decimal(precio_proveedor_centavos)*(Decimal(1)+pct/Decimal(100))
    return int(result.quantize(Decimal("1"),rounding=ROUND_HALF_UP))


def porcentaje_real(precio_proveedor_centavos,precio_venta_centavos):
    if precio_proveedor_centavos is None or precio_venta_centavos is None or precio_proveedor_centavos==0:return None
    if precio_proveedor_centavos<0 or precio_venta_centavos<0:raise ValueError("Los precios no pueden ser negativos")
    value=(Decimal(precio_venta_centavos)/Decimal(precio_proveedor_centavos)-Decimal(1))*Decimal(100)
    if value<0:value=Decimal(0)
    return normalizar_porcentaje(value)
