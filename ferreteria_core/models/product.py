from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    id: int
    codigo_truper: str | None
    codigo_barras: str | None
    clave: str | None
    descripcion: str | None
    marca: str | None
    categoria: str | None
    precio_catalogo_publico: int | None
    precio_venta: int | None
    existencia: int
    stock_minimo: int
    es_truper: bool
    datos_completos: bool
    requiere_revision: bool
    activo: bool
    tipo_venta: str
    existencia_granel_mg: int
    stock_minimo_granel_mg: int
    precio_proveedor: int | None
    porcentaje_ganancia: str | None
    controla_inventario: bool
    unidad_granel: str | None
    precio_variable: bool

    @classmethod
    def from_row(cls, row):
        fields = cls.__dataclass_fields__
        values = {name: row[name] for name in fields}
        for name in ("es_truper", "datos_completos", "requiere_revision", "activo", "controla_inventario", "precio_variable"):
            values[name] = bool(values[name])
        return cls(**values)
