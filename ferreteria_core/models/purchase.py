from dataclasses import dataclass


@dataclass(frozen=True)
class PurchasePresentation:
    id:int
    nombre:str
    activo:bool
    @classmethod
    def from_row(cls,row):return cls(row["id"],row["nombre"],bool(row["activo"]))


@dataclass(frozen=True)
class PurchaseDetail:
    id:int
    compra_id:int
    producto_id:int
    descripcion_snapshot:str
    tipo_venta_snapshot:str
    unidad_granel_snapshot:str|None
    presentacion_snapshot:str
    cantidad_presentaciones:str
    contenido_por_presentacion:int
    cantidad_base:int
    costo_presentacion_centavos:int
    costo_unitario_centavos:int
    subtotal_centavos:int
    controla_inventario_snapshot:bool


@dataclass(frozen=True)
class Purchase:
    id:int
    folio:str
    proveedor_id:int|None
    proveedor_nombre_snapshot:str|None
    folio_proveedor:str|None
    fecha:str
    estado:str
    total_centavos:int
    notas:str|None
    detalles:tuple[PurchaseDetail,...]=()
