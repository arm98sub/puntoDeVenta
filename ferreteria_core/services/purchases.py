import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP

from ferreteria_core.money import decimal_a_centavos
from ferreteria_core.quantity import cantidad_desde_mayor,MG_PER_KG
from ferreteria_core.repositories import InventoryRepository,ProductRepository,PurchasePresentationRepository,PurchaseRepository,SupplierRepository
from .catalogs import display_catalog_name,normalize_catalog_name


GENERAL_PURCHASE_PRESENTATIONS=("Pieza","Caja","Paquete","Display")


class PurchasePresentationService:
    def __init__(self,database):self.database=database
    def listar_activas(self):
        with self.database.connect() as connection:return PurchasePresentationRepository.list(connection,True)
    def listar_todas(self):
        with self.database.connect() as connection:return PurchasePresentationRepository.list(connection,False)
    def obtener(self,item_id):
        with self.database.connect() as connection:return PurchasePresentationRepository.get(connection,item_id)
    def crear(self,nombre):
        name=display_catalog_name(nombre);normalized=normalize_catalog_name(name)
        if not normalized:raise ValueError("El nombre de la presentación es obligatorio")
        try:
            with self.database.transaction() as connection:return PurchasePresentationRepository.insert(connection,name,normalized)
        except sqlite3.IntegrityError as exc:raise ValueError("La presentación ya existe") from exc
    def editar(self,item_id,nombre):
        name=display_catalog_name(nombre);normalized=normalize_catalog_name(name)
        if not normalized:raise ValueError("El nombre de la presentación es obligatorio")
        try:
            with self.database.transaction() as connection:return PurchasePresentationRepository.update(connection,item_id,name,normalized)
        except sqlite3.IntegrityError as exc:raise ValueError("La presentación ya existe") from exc
    def desactivar(self,item_id):return self._active(item_id,False)
    def reactivar(self,item_id):return self._active(item_id,True)
    def _active(self,item_id,active):
        with self.database.transaction() as connection:return PurchasePresentationRepository.set_active(connection,item_id,active)


def seed_general_purchase_presentations(database):
    service=PurchasePresentationService(database);existing={normalize_catalog_name(item.nombre) for item in service.listar_todas()}
    for name in GENERAL_PURCHASE_PRESENTATIONS:
        if normalize_catalog_name(name) not in existing:service.crear(name)
    return service.listar_todas()


@dataclass(frozen=True)
class PurchaseLine:
    producto_id:int
    presentacion_id:int|None
    presentacion_nombre:str
    cantidad_presentaciones:Decimal
    contenido_por_presentacion:int
    cantidad_base:int
    costo_presentacion_centavos:int
    costo_unitario_centavos:int
    subtotal_centavos:int
    tipo_venta_snapshot:str
    unidad_granel_snapshot:str|None


class PurchaseService:
    def __init__(self,database):self.database=database
    def crear_linea(self,producto_id,presentacion_id,cantidad_presentaciones,contenido,costo_presentacion):
        with self.database.connect() as connection:
            product=ProductRepository.get(connection,producto_id)
            if product is None or not product.activo:raise LookupError("Producto inexistente o inactivo")
            presentation=PurchasePresentationRepository.get(connection,presentacion_id) if presentacion_id else None
            if presentation is None and presentacion_id is not None:raise LookupError("Presentación inexistente")
            if presentation is not None and not presentation.activo:raise ValueError("La presentación está inactiva")
        count=_positive_decimal(cantidad_presentaciones,"cantidad de presentaciones")
        content=_content_internal(product,contenido)
        base_decimal=count*Decimal(content)
        if base_decimal!=base_decimal.to_integral_value():raise ValueError("La conversión produce una fracción menor que la unidad interna")
        base=int(base_decimal);cost=decimal_a_centavos(costo_presentacion)
        if cost is None or cost<0:raise ValueError("El costo de presentación es obligatorio")
        subtotal=int((count*Decimal(cost)).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
        divisor=Decimal(content) if product.tipo_venta=="UNIDAD" else Decimal(content)/Decimal(MG_PER_KG)
        unit_cost=int((Decimal(cost)/divisor).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
        return PurchaseLine(product.id,presentation.id if presentation else None,presentation.nombre if presentation else "Pieza",count,content,base,cost,unit_cost,subtotal,product.tipo_venta,product.unidad_granel)
    def confirmar(self,lineas,proveedor_id=None,folio_proveedor=None,fecha=None,notas=None,failure_hook=None):
        lines=list(lineas);hook=failure_hook or (lambda _stage:None)
        if not lines:raise ValueError("La compra debe contener al menos una línea")
        if not all(isinstance(line,PurchaseLine) for line in lines):raise ValueError("Línea de compra inválida")
        with self.database.transaction() as connection:
            supplier=SupplierRepository.get(connection,proveedor_id) if proveedor_id else None
            if proveedor_id and (supplier is None or not supplier.activo):raise ValueError("El proveedor no existe o está inactivo")
            products={};validated=[]
            for line in lines:
                product=ProductRepository.get(connection,line.producto_id)
                if product is None or not product.activo:raise LookupError("Un producto no existe o está inactivo")
                validated.append(_revalidate_line(connection,line,product));products[line.producto_id]=product
            lines=validated;total=sum(line.subtotal_centavos for line in lines);temporary="TMP-"+uuid.uuid4().hex
            purchase_id,folio=PurchaseRepository.insert_header(connection,{"folio":temporary,"proveedor_id":proveedor_id,"proveedor_nombre_snapshot":supplier.nombre if supplier else None,"folio_proveedor":_optional(folio_proveedor),"fecha":str(fecha or date.today().isoformat()),"total_centavos":total,"notas":_optional(notas)})
            hook("header")
            for index,line in enumerate(lines):
                product=products[line.producto_id]
                PurchaseRepository.insert_detail(connection,{"compra_id":purchase_id,"producto_id":product.id,"descripcion_snapshot":product.descripcion or product.clave or f"Producto {product.id}","tipo_venta_snapshot":product.tipo_venta,"unidad_granel_snapshot":product.unidad_granel,"presentacion_id":line.presentacion_id,"presentacion_snapshot":line.presentacion_nombre,"cantidad_presentaciones":format(line.cantidad_presentaciones,"f"),"contenido_por_presentacion":line.contenido_por_presentacion,"cantidad_base":line.cantidad_base,"costo_presentacion_centavos":line.costo_presentacion_centavos,"costo_unitario_centavos":line.costo_unitario_centavos,"subtotal_centavos":line.subtotal_centavos,"controla_inventario_snapshot":int(product.controla_inventario)})
                if product.controla_inventario:
                    if product.tipo_venta=="GRANEL":InventoryRepository.update_bulk(connection,product.id,product.existencia_granel_mg+line.cantidad_base,"COMPRA",line.cantidad_base,folio,"Entrada por compra")
                    else:InventoryRepository.update(connection,product.id,product.existencia+line.cantidad_base,"COMPRA",line.cantidad_base,folio,"Entrada por compra")
                ProductRepository.update_fields(connection,product.id,{"precio_proveedor":line.costo_unitario_centavos})
                products[product.id]=ProductRepository.get(connection,product.id)
                hook(f"line_{index}")
            return PurchaseRepository.get(connection,purchase_id)
    def obtener(self,purchase_id):
        with self.database.connect() as connection:return PurchaseRepository.get(connection,purchase_id)
    def listar(self,estado=None,limit=100):
        if estado not in {None,"CONFIRMADA","CANCELADA"}:raise ValueError("Estado de compra inválido")
        with self.database.connect() as connection:return PurchaseRepository.list(connection,estado,limit)
    def cancelar(self,purchase_id):
        with self.database.transaction() as connection:
            purchase=PurchaseRepository.get(connection,purchase_id)
            if purchase is None:raise LookupError("La compra no existe")
            if purchase.estado!="CONFIRMADA":raise ValueError("La compra ya fue cancelada")
            products={detail.producto_id:ProductRepository.get(connection,detail.producto_id) for detail in purchase.detalles}
            required={}
            for detail in purchase.detalles:
                if not detail.controla_inventario_snapshot:continue
                quantity,kind=required.get(detail.producto_id,(0,detail.tipo_venta_snapshot));required[detail.producto_id]=(quantity+detail.cantidad_base,kind)
            for product_id,(quantity,kind) in required.items():
                product=products[product_id]
                current=product.existencia_granel_mg if kind=="GRANEL" else product.existencia
                if current<quantity:raise ValueError(f"No se puede cancelar {purchase.folio}: una existencia sería negativa")
            for detail in purchase.detalles:
                if not detail.controla_inventario_snapshot:continue
                product=ProductRepository.get(connection,detail.producto_id)
                if detail.tipo_venta_snapshot=="GRANEL":InventoryRepository.update_bulk(connection,product.id,product.existencia_granel_mg-detail.cantidad_base,"CANCELACION_COMPRA",-detail.cantidad_base,purchase.folio,"Cancelación de compra",require_active=False)
                else:InventoryRepository.update(connection,product.id,product.existencia-detail.cantidad_base,"CANCELACION_COMPRA",-detail.cantidad_base,purchase.folio,"Cancelación de compra",require_active=False)
            PurchaseRepository.cancel(connection,purchase_id)
            return PurchaseRepository.get(connection,purchase_id)


def _positive_decimal(value,label):
    try:result=Decimal(str(value).strip())
    except (InvalidOperation,AttributeError) as exc:raise ValueError(f"{label} inválida") from exc
    if not result.is_finite() or result<=0:raise ValueError(f"{label} debe ser positiva")
    return result


def _content_internal(product,value):
    if product.tipo_venta=="UNIDAD":
        number=_positive_decimal(value,"contenido")
        if number!=number.to_integral_value():raise ValueError("El contenido por presentación debe ser un entero para productos por unidad")
        return int(number)
    return cantidad_desde_mayor(value,product.unidad_granel or "PESO")


def _revalidate_line(connection,line,product):
    if line.tipo_venta_snapshot!=product.tipo_venta:
        raise ValueError("El tipo de venta del producto cambió; reconstruya la línea")
    if line.unidad_granel_snapshot!=product.unidad_granel:
        raise ValueError("La unidad de granel del producto cambió; reconstruya la línea")
    presentation=PurchasePresentationRepository.get(connection,line.presentacion_id) if line.presentacion_id is not None else None
    if line.presentacion_id is not None and presentation is None:raise LookupError("La presentación de compra ya no existe")
    if presentation is not None and not presentation.activo:raise ValueError("La presentación de compra está inactiva")
    count=_positive_decimal(line.cantidad_presentaciones,"cantidad de presentaciones")
    if not isinstance(line.contenido_por_presentacion,int) or isinstance(line.contenido_por_presentacion,bool) or line.contenido_por_presentacion<=0:
        raise ValueError("El contenido interno de la línea es inválido")
    content=line.contenido_por_presentacion
    if not isinstance(line.costo_presentacion_centavos,int) or isinstance(line.costo_presentacion_centavos,bool) or line.costo_presentacion_centavos<0:
        raise ValueError("El costo de presentación de la línea es inválido")
    base_decimal=count*Decimal(content)
    if base_decimal!=base_decimal.to_integral_value():raise ValueError("La conversión produce una fracción menor que la unidad interna")
    base=int(base_decimal);cost=line.costo_presentacion_centavos
    subtotal=int((count*Decimal(cost)).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    divisor=Decimal(content) if product.tipo_venta=="UNIDAD" else Decimal(content)/Decimal(MG_PER_KG)
    unit_cost=int((Decimal(cost)/divisor).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    if (line.cantidad_base,line.costo_unitario_centavos,line.subtotal_centavos)!=(base,unit_cost,subtotal):
        raise ValueError("La línea de compra es inconsistente; reconstruya la línea")
    return PurchaseLine(product.id,line.presentacion_id,presentation.nombre if presentation else "Pieza",count,content,base,cost,unit_cost,subtotal,product.tipo_venta,product.unidad_granel)


def _optional(value):return (value or "").strip() or None
