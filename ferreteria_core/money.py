from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def decimal_a_centavos(valor: Decimal | str | int | None) -> int | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        decimal = valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except InvalidOperation as exc:
        raise ValueError("Importe monetario inválido") from exc
    if not decimal.is_finite() or decimal < 0:
        raise ValueError("El importe no puede ser negativo ni infinito")
    return int((decimal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def centavos_a_decimal(centavos: int | None) -> Decimal | None:
    if centavos is None:
        return None
    if not isinstance(centavos, int) or centavos < 0:
        raise ValueError("Los centavos deben ser un entero no negativo")
    return Decimal(centavos) / Decimal(100)
