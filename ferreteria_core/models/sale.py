from dataclasses import dataclass, field


@dataclass(frozen=True)
class SaleDetail:
    id: int
    producto_id: int
    codigo_barras_snapshot: str | None
    codigo_truper_snapshot: str | None
    clave_snapshot: str | None
    descripcion_snapshot: str | None
    cantidad: int
    precio_unitario_centavos: int
    subtotal_centavos: int
    tipo_venta_snapshot: str = "UNIDAD"
    cantidad_mg: int | None = None
    unidad_snapshot: str = "PZA"
    precio_por_kg_centavos: int | None = None
    controla_inventario_snapshot: bool = True
    unidad_granel_snapshot: str | None = None


@dataclass(frozen=True)
class Sale:
    id: int
    folio: str
    fecha_hora: str
    subtotal_centavos: int
    descuento_centavos: int
    total_centavos: int
    metodo_pago: str
    efectivo_recibido_centavos: int | None
    cambio_centavos: int | None
    estado: str
    nota: str | None
    created_at: str
    detalles: list[SaleDetail] = field(default_factory=list)
