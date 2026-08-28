from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MG_PER_GRAM = 1_000
MG_PER_KG = 1_000_000
UL_PER_LITER = 1_000_000
ROUNDING = ROUND_HALF_UP


def gramos_a_mg(value) -> int:
    try:
        grams = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Peso inválido") from exc
    if not grams.is_finite() or grams <= 0:
        raise ValueError("El peso debe ser positivo")
    return int((grams * MG_PER_GRAM).quantize(Decimal("1"), rounding=ROUNDING))


def kg_a_mg(value, *, allow_zero=False) -> int:
    try:
        kilograms = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Peso inválido") from exc
    if not kilograms.is_finite() or kilograms < 0 or (kilograms == 0 and not allow_zero):
        raise ValueError("El peso debe ser positivo" if not allow_zero else "El peso no puede ser negativo")
    return int((kilograms * MG_PER_KG).quantize(Decimal("1"), rounding=ROUNDING))


def litros_a_ul(value, *, allow_zero=False) -> int:
    try:liters=Decimal(str(value).strip())
    except (InvalidOperation,AttributeError) as exc:raise ValueError("Volumen inválido") from exc
    if not liters.is_finite() or liters<0 or (liters==0 and not allow_zero):raise ValueError("El volumen debe ser positivo" if not allow_zero else "El volumen no puede ser negativo")
    return int((liters*UL_PER_LITER).quantize(Decimal("1"),rounding=ROUNDING))


def subtotal_granel_centavos(precio_por_kg_centavos: int, cantidad_mg: int) -> int:
    if not isinstance(precio_por_kg_centavos, int) or precio_por_kg_centavos < 0:
        raise ValueError("Precio a granel inválido")
    if not isinstance(cantidad_mg, int) or cantidad_mg <= 0:
        raise ValueError("La cantidad debe ser positiva")
    value = Decimal(precio_por_kg_centavos) * Decimal(cantidad_mg) / Decimal(MG_PER_KG)
    return int(value.quantize(Decimal("1"), rounding=ROUNDING))


def importe_a_mg(importe_centavos: int, precio_por_kg_centavos: int) -> int:
    if not isinstance(importe_centavos, int) or importe_centavos <= 0:
        raise ValueError("El importe debe ser positivo")
    if not isinstance(precio_por_kg_centavos, int) or precio_por_kg_centavos <= 0:
        raise ValueError("El precio a granel debe ser mayor que cero")
    value = Decimal(importe_centavos) * Decimal(MG_PER_KG) / Decimal(precio_por_kg_centavos)
    result = int(value.quantize(Decimal("1"), rounding=ROUNDING))
    if result <= 0:
        raise ValueError("El importe produce una cantidad menor a la unidad interna")
    return result


def importe_a_cantidad(importe_centavos:int,precio_por_unidad_centavos:int,unidad_granel="PESO")->int:
    if unidad_granel not in {"PESO","VOLUMEN"}:raise ValueError("Unidad de granel inválida")
    return importe_a_mg(importe_centavos,precio_por_unidad_centavos)


def formato_cantidad(tipo_venta: str, *, unidades=0, miligramos=0, unidad_granel="PESO") -> str:
    if tipo_venta == "UNIDAD":
        return f"{unidades} pza" if unidades == 1 else f"{unidades} pzas"
    if tipo_venta != "GRANEL":
        raise ValueError("Tipo de venta inválido")
    if not isinstance(miligramos, int) or miligramos < 0:raise ValueError("Cantidad interna inválida")
    return formato_granel(miligramos,unidad_granel)


def formato_kg(miligramos:int,max_decimals=4)->str:
    if not isinstance(miligramos,int) or miligramos<0:raise ValueError("Cantidad en miligramos inválida")
    value=Decimal(miligramos)/Decimal(MG_PER_KG);quantum=Decimal(1).scaleb(-max_decimals);shown=value.quantize(quantum,rounding=ROUNDING)
    text=f"{shown:.{max_decimals}f}".rstrip("0").rstrip(".")
    return f"{text} kg"


def formato_litros(microlitros:int,max_decimals=4)->str:
    if not isinstance(microlitros,int) or microlitros<0:raise ValueError("Cantidad en microlitros inválida")
    value=Decimal(microlitros)/Decimal(UL_PER_LITER);quantum=Decimal(1).scaleb(-max_decimals);shown=value.quantize(quantum,rounding=ROUNDING)
    text=f"{shown:.{max_decimals}f}".rstrip("0").rstrip(".") or "0"
    return f"{text} L"


def formato_granel(cantidad:int,unidad_granel="PESO",max_decimals=4)->str:
    return formato_litros(cantidad,max_decimals) if unidad_granel=="VOLUMEN" else formato_kg(cantidad,max_decimals)


def auxiliar_granel(cantidad:int,unidad_granel="PESO")->str:
    divisor=Decimal(1000);value=Decimal(cantidad)/divisor;text=f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{text} ml" if unidad_granel=="VOLUMEN" else f"{text} g"


def cantidad_desde_mayor(value,unidad_granel="PESO",allow_zero=False)->int:
    return litros_a_ul(value,allow_zero=allow_zero) if unidad_granel=="VOLUMEN" else kg_a_mg(value,allow_zero=allow_zero)
