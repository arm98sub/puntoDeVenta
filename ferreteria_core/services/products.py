import re
import sqlite3
from decimal import Decimal

from ferreteria_core.money import decimal_a_centavos
from ferreteria_core.pricing import normalizar_porcentaje,porcentaje_real,precio_venta_sugerido
from ferreteria_core.repositories import InventoryRepository, ProductRepository
from edition import EDITION


def validar_codigo_barras(value: str) -> str:
    barcode = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{4,64}", barcode):
        raise ValueError("Código de barras inválido: use 4-64 letras, números, punto, guion o guion bajo")
    return barcode


class ProductService:
    def __init__(self, database,edition_config=EDITION):
        self.database = database
        self.edition_config=edition_config

    def get(self, product_id):
        with self.database.connect() as connection:
            return ProductRepository.get(connection, product_id)

    def crear_producto_externo(self, codigo_barras: str, descripcion: str, precio_venta: Decimal | None, existencia: int, *, clave=None, marca=None, categoria=None,categoria_id=None,proveedor_principal_id=None, stock_minimo=0, tipo_venta="UNIDAD", unidad_granel=None, existencia_granel_mg=0, stock_minimo_granel_mg=0,precio_proveedor=None,porcentaje_ganancia=None,controla_inventario=True,permitir_sin_barcode=False,precio_variable=False):
        barcode = validar_codigo_barras(codigo_barras) if (codigo_barras or "").strip() else None
        if barcode is None and not permitir_sin_barcode:raise ValueError("El código de barras es obligatorio")
        description = (descripcion or "").strip()
        if not description:
            raise ValueError("La descripción es obligatoria")
        tipo_venta=_tipo(tipo_venta)
        _validar_precio_variable(tipo_venta,precio_variable)
        unidad_granel=_unidad(tipo_venta,unidad_granel)
        if not all(isinstance(v,int) and v>=0 for v in (existencia,stock_minimo,existencia_granel_mg,stock_minimo_granel_mg)):
            raise ValueError("Existencia y stock mínimo deben ser enteros no negativos")
        if tipo_venta=="UNIDAD" and existencia_granel_mg:raise ValueError("Un producto UNIDAD no usa existencia a granel")
        if tipo_venta=="GRANEL" and existencia:raise ValueError("Un producto GRANEL no usa existencia por piezas")
        cost=decimal_a_centavos(precio_proveedor);pct=normalizar_porcentaje(porcentaje_ganancia);sale=decimal_a_centavos(precio_venta)
        if sale is None and self.edition_config.auto_recalculate_sale_price_from_cost:sale=precio_venta_sugerido(cost,pct)
        if sale is None and not precio_variable and not self.edition_config.auto_recalculate_sale_price_from_cost:
            raise ValueError("El precio de venta es obligatorio para productos de precio fijo en GENERAL")
        values = dict(codigo_barras=barcode, clave=_clean(clave), descripcion=description, marca=_clean(marca),
                      categoria=_clean(categoria),categoria_id=categoria_id,proveedor_principal_id=proveedor_principal_id, precio_venta=sale,precio_proveedor=cost,porcentaje_ganancia=porcentaje_real(cost,sale) if cost is not None and sale is not None else pct,controla_inventario=int(bool(controla_inventario)),precio_variable=int(bool(precio_variable)),
                      existencia=0, stock_minimo=stock_minimo,tipo_venta=tipo_venta,
                      unidad_granel=unidad_granel,existencia_granel_mg=0,stock_minimo_granel_mg=stock_minimo_granel_mg)
        try:
            with self.database.transaction() as connection:
                product = ProductRepository.insert_external(connection, values)
                if controla_inventario and existencia:
                    InventoryRepository.update(connection, product.id, existencia, "AJUSTE", existencia, "ALTA_INICIAL", "Existencia inicial")
                if controla_inventario and existencia_granel_mg:
                    InventoryRepository.update_bulk(connection,product.id,existencia_granel_mg,"AJUSTE",existencia_granel_mg,"ALTA_INICIAL","Existencia inicial")
                return ProductRepository.get(connection, product.id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("El código de barras ya está vinculado") from exc

    def vincular_codigo_barras(self, producto_id: int, codigo_barras: str):
        barcode = validar_codigo_barras(codigo_barras)
        try:
            with self.database.transaction() as connection:
                product = ProductRepository.get(connection, producto_id)
                if product is None or not product.activo:
                    raise LookupError("Producto inexistente o inactivo")
                if product.codigo_barras:
                    if product.codigo_barras == barcode:
                        return product
                    raise ValueError("El producto ya tiene un código de barras; no se reemplazó")
                return ProductRepository.link_barcode(connection, producto_id, barcode)
        except sqlite3.IntegrityError as exc:
            raise ValueError("El código de barras pertenece a otro producto") from exc

    def alta_rapida_truper_existente(self, producto_id: int, codigo_barras: str,
                                     precio_venta: Decimal, existencia_actual: int | None = None,
                                     *, descripcion=None, existencia_granel_mg: int | None = None,
                                     permitir_reemplazo=False,tipo_venta=None,unidad_granel=None,
                                     controla_inventario=None,precio_variable=None):
        """Vincula barcode, precio y conteo físico en una sola transacción."""
        barcode = validar_codigo_barras(codigo_barras)
        cents = decimal_a_centavos(precio_venta)
        try:
            with self.database.transaction() as connection:
                product = ProductRepository.get(connection, producto_id)
                if product is None or not product.activo or not product.es_truper:
                    raise LookupError("Producto Truper inexistente o inactivo")
                if product.codigo_barras and product.codigo_barras != barcode and not permitir_reemplazo:
                    raise ValueError("El producto ya tiene otro código de barras; use la revinculación confirmada")
                kind=_tipo(tipo_venta or product.tipo_venta);bulk_unit=_unidad(kind,unidad_granel if tipo_venta is not None else product.unidad_granel)
                target_control=product.controla_inventario if controla_inventario is None else bool(controla_inventario)
                target_variable=product.precio_variable if precio_variable is None else bool(precio_variable);_validar_precio_variable(kind,target_variable)
                if product.tipo_venta=="GRANEL" and kind=="GRANEL" and (product.unidad_granel or "PESO")!=bulk_unit and product.controla_inventario and product.existencia_granel_mg!=0:raise ValueError("No se puede cambiar entre Peso y Volumen porque el producto controla inventario y su existencia no es cero. Ajuste primero la existencia a cero.")
                owner = ProductRepository.exact_any(connection, "codigo_barras", barcode, producto_id)
                if owner:
                    raise ValueError(_duplicate_message("código de barras", owner))
                ProductRepository.update_identity(connection, producto_id, "codigo_barras", barcode)
                ProductRepository.update_fields(connection, producto_id, {
                    "descripcion": _clean(descripcion),
                    "precio_venta": cents,
                    "tipo_venta":kind,"unidad_granel":bulk_unit,"controla_inventario":int(target_control),
                    "precio_variable":int(target_variable),"porcentaje_ganancia": porcentaje_real(product.precio_proveedor, cents)
                    if product.precio_proveedor is not None else product.porcentaje_ganancia,
                })
                if target_control and existencia_actual is not None:
                    if kind != "UNIDAD":raise ValueError("Use existencia_granel_mg para productos GRANEL")
                    if not isinstance(existencia_actual, int) or existencia_actual < 0:
                        raise ValueError("La existencia debe ser un entero no negativo")
                    if existencia_actual != product.existencia:
                        InventoryRepository.update(connection, producto_id, existencia_actual, "AJUSTE",
                                                   existencia_actual-product.existencia,
                                                   "ALTA_RAPIDA", "Alta/vinculación rápida")
                if target_control and existencia_granel_mg is not None:
                    if kind != "GRANEL":raise ValueError("La existencia a granel sólo aplica a productos GRANEL")
                    if not isinstance(existencia_granel_mg,int) or existencia_granel_mg<0:raise ValueError("La existencia en miligramos debe ser no negativa")
                    if existencia_granel_mg != product.existencia_granel_mg:
                        InventoryRepository.update_bulk(connection,producto_id,existencia_granel_mg,"AJUSTE",existencia_granel_mg-product.existencia_granel_mg,"ALTA_RAPIDA","Alta/vinculación rápida")
                return ProductRepository.get(connection, producto_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("El código de barras pertenece a otro producto") from exc

    def crear_producto_truper_minimo(self, codigo_truper: str, codigo_barras: str,
                                     precio_venta: Decimal, existencia: int = 0,
                                     *, descripcion=None, clave=None, controla_inventario=True,
                                     tipo_venta="UNIDAD",unidad_granel=None,existencia_granel_mg=0,precio_variable=False):
        code = (codigo_truper or "").strip()
        if not code:
            raise ValueError("El código Truper es obligatorio")
        barcode = validar_codigo_barras(codigo_barras) if (codigo_barras or "").strip() else None
        if not isinstance(existencia, int) or existencia < 0:
            raise ValueError("La existencia debe ser un entero no negativo")
        kind=_tipo(tipo_venta);bulk_unit=_unidad(kind,unidad_granel)
        _validar_precio_variable(kind,precio_variable)
        if not isinstance(existencia_granel_mg,int) or existencia_granel_mg<0:raise ValueError("La existencia interna de granel debe ser no negativa")
        values = {"codigo_truper": code, "codigo_barras": barcode, "clave": _clean(clave),
                  "descripcion": _clean(descripcion), "precio_venta": decimal_a_centavos(precio_venta),
                  "tipo_venta": kind,"unidad_granel":bulk_unit,"controla_inventario": int(bool(controla_inventario)),"precio_variable":int(bool(precio_variable))}
        try:
            with self.database.transaction() as connection:
                if ProductRepository.exact_any(connection, "codigo_truper", code):
                    raise ValueError("El código Truper ya pertenece a otro producto")
                if barcode and ProductRepository.exact_any(connection, "codigo_barras", barcode):
                    raise ValueError("El código de barras ya pertenece a otro producto")
                product = ProductRepository.insert_truper_minimal(connection, values)
                if controla_inventario and existencia:
                    InventoryRepository.update(connection, product.id, existencia, "AJUSTE", existencia,
                                               "ALTA_RAPIDA", "Alta/vinculación rápida")
                if controla_inventario and existencia_granel_mg:
                    InventoryRepository.update_bulk(connection,product.id,existencia_granel_mg,"AJUSTE",existencia_granel_mg,"ALTA_RAPIDA","Alta/vinculación rápida")
                return ProductRepository.get(connection, product.id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Código Truper o código de barras duplicado") from exc

    def revincular_codigo_barras(self, producto_id: int, nuevo_codigo: str):
        barcode = validar_codigo_barras(nuevo_codigo)
        with self.database.transaction() as connection:
            product = ProductRepository.get(connection, producto_id)
            if product is None:
                raise LookupError("El producto no existe")
            owner = ProductRepository.exact_any(connection, "codigo_barras", barcode, producto_id)
            if owner:
                raise ValueError(_duplicate_message("código de barras", owner))
            return ProductRepository.update_identity(connection, producto_id, "codigo_barras", barcode)

    def cambiar_codigo_truper(self, producto_id: int, nuevo_codigo: str):
        code = (nuevo_codigo or "").strip()
        if not code:
            raise ValueError("El código Truper es obligatorio")
        with self.database.transaction() as connection:
            product = ProductRepository.get(connection, producto_id)
            if product is None:
                raise LookupError("El producto no existe")
            owner = ProductRepository.exact_any(connection, "codigo_truper", code, producto_id)
            if owner:
                raise ValueError(_duplicate_message("código Truper", owner))
            return ProductRepository.update_identity(connection, producto_id, "codigo_truper", code)

    def estado_eliminacion(self, producto_id: int) -> dict:
        with self.database.connect() as connection:
            product = ProductRepository.get(connection, producto_id)
            if product is None:
                raise LookupError("El producto no existe")
            counts = ProductRepository.history_counts(connection, producto_id)
            return {"producto": product, **counts, "puede_eliminar": not any(counts.values())}

    def eliminar_o_desactivar(self, producto_id: int):
        with self.database.transaction() as connection:
            product = ProductRepository.get(connection, producto_id)
            if product is None:
                raise LookupError("El producto no existe")
            counts = ProductRepository.history_counts(connection, producto_id)
            if any(counts.values()):
                return {"accion": "DESACTIVADO", "producto": ProductRepository.update_fields(connection, producto_id, {"activo": 0})}
            ProductRepository.delete(connection, producto_id)
            return {"accion": "ELIMINADO", "producto": product}

    def reactivar_producto(self, producto_id: int):
        with self.database.transaction() as connection:
            return ProductRepository.update_fields(connection, producto_id, {"activo": 1})

    def buscar_exacto(self, campo, valor):
        with self.database.connect() as connection:
            return ProductRepository.exact(connection, campo, valor.strip())

    def buscar(self, **filters):
        with self.database.connect() as connection:
            return ProductRepository.search(connection, **filters)

    def actualizar_precio_venta(self, producto_id: int, nuevo_precio: Decimal):
        cents = decimal_a_centavos(nuevo_precio)
        with self.database.transaction() as connection:
            product=ProductRepository.get(connection,producto_id)
            if product is None:raise LookupError("El producto no existe")
            return ProductRepository.update_fields(connection,producto_id,{"precio_venta":cents,"porcentaje_ganancia":porcentaje_real(product.precio_proveedor,cents) if product.precio_proveedor is not None else product.porcentaje_ganancia})

    def actualizar_precio_proveedor(self,producto_id,nuevo_precio):
        cents=decimal_a_centavos(nuevo_precio)
        with self.database.transaction() as connection:
            product=ProductRepository.get(connection,producto_id)
            if product is None:raise LookupError("El producto no existe")
            values={"precio_proveedor":cents}
            if self.edition_config.auto_recalculate_sale_price_from_cost:
                suggested=precio_venta_sugerido(cents,product.porcentaje_ganancia)
                if suggested is not None:values["precio_venta"]=suggested
            return ProductRepository.update_fields(connection,producto_id,values)

    def actualizar_porcentaje_ganancia(self,producto_id,porcentaje):
        pct=normalizar_porcentaje(porcentaje)
        with self.database.transaction() as connection:
            product=ProductRepository.get(connection,producto_id)
            if product is None:raise LookupError("El producto no existe")
            values={"porcentaje_ganancia":pct}
            if self.edition_config.auto_recalculate_sale_price_from_cost:
                suggested=precio_venta_sugerido(product.precio_proveedor,pct)
                if suggested is not None:values["precio_venta"]=suggested
            return ProductRepository.update_fields(connection,producto_id,values)

    def actualizar_precio_catalogo(self,producto_id,nuevo_precio):
        cents=decimal_a_centavos(nuevo_precio)
        with self.database.transaction() as connection:return ProductRepository.update_fields(connection,producto_id,{"precio_catalogo_publico":cents})

    def modificar_producto(self,producto_id,*,descripcion,tipo_venta,unidad_granel=None,precio_catalogo_publico=None,precio_proveedor=None,porcentaje_ganancia=None,precio_venta=None,controla_inventario=True,activo=True,precio_variable=False,categoria_id=Ellipsis,proveedor_principal_id=Ellipsis,stock_minimo=Ellipsis,stock_minimo_granel_mg=Ellipsis):
        cost=decimal_a_centavos(precio_proveedor);sale=decimal_a_centavos(precio_venta);pct=normalizar_porcentaje(porcentaje_ganancia)
        kind=_tipo(tipo_venta);bulk_unit=_unidad(kind,unidad_granel)
        _validar_precio_variable(kind,precio_variable)
        with self.database.transaction() as connection:
            product=ProductRepository.get(connection,producto_id)
            if product is None:raise LookupError("El producto no existe")
            if sale is None:
                sale=precio_venta_sugerido(cost,pct) if self.edition_config.auto_recalculate_sale_price_from_cost else product.precio_venta
            actual_pct=(porcentaje_real(cost,sale) if cost is not None and sale is not None else pct) if self.edition_config.auto_recalculate_sale_price_from_cost else (pct if porcentaje_ganancia is not None else product.porcentaje_ganancia)
            values={"descripcion":_clean(descripcion),"tipo_venta":kind,"unidad_granel":bulk_unit,"precio_catalogo_publico":decimal_a_centavos(precio_catalogo_publico),"precio_proveedor":cost,"porcentaje_ganancia":actual_pct,"precio_venta":sale,"controla_inventario":int(bool(controla_inventario)),"activo":int(bool(activo)),"precio_variable":int(bool(precio_variable))}
            for field,value in (("categoria_id",categoria_id),("proveedor_principal_id",proveedor_principal_id),("stock_minimo",stock_minimo),("stock_minimo_granel_mg",stock_minimo_granel_mg)):
                if value is not Ellipsis:values[field]=value
            if product.tipo_venta=="GRANEL" and kind=="GRANEL" and (product.unidad_granel or "PESO")!=bulk_unit and product.controla_inventario and product.existencia_granel_mg!=0:raise ValueError("No se puede cambiar entre Peso y Volumen porque el producto controla inventario y su existencia no es cero. Ajuste primero la existencia a cero.")
            return ProductRepository.update_fields(connection,producto_id,values)

    def actualizar_descripcion_producto(self, producto_id: int, descripcion: str | None):
        value=(descripcion or "").strip() or None
        with self.database.transaction() as connection:
            return ProductRepository.update_description(connection,producto_id,value)

    def configurar_presentacion_compra(self,producto_id,presentacion_id=None,contenido_por_presentacion=None):
        if contenido_por_presentacion is not None and (not isinstance(contenido_por_presentacion,int) or contenido_por_presentacion<=0):raise ValueError("El contenido habitual debe ser un entero interno positivo")
        with self.database.transaction() as connection:
            if ProductRepository.get(connection,producto_id) is None:raise LookupError("El producto no existe")
            return ProductRepository.update_fields(connection,producto_id,{"presentacion_compra_id":presentacion_id,"contenido_por_presentacion":contenido_por_presentacion})

    def aplicar_cambios(self, cambios: dict[int,dict]):
        normalized={}
        if not cambios:raise ValueError("No hay cambios para guardar")
        for product_id,fields in cambios.items():
            if not isinstance(product_id,int) or product_id<=0:raise ValueError("Producto inválido")
            values={}
            for field,value in fields.items():
                if field=="descripcion":values[field]=(value or "").strip() or None
                elif field in {"precio_catalogo_publico","precio_proveedor","precio_venta"}:
                    values[field]=decimal_a_centavos(value)
                elif field=="porcentaje_ganancia":values[field]=normalizar_porcentaje(value)
                elif field=="tipo_venta":values[field]=_tipo(value)
                elif field=="unidad_granel":
                    if value not in {None,"PESO","VOLUMEN"}:raise ValueError("Unidad de granel inválida")
                    values[field]=value
                elif field in {"activo","controla_inventario","precio_variable"}:values[field]=int(bool(value))
                elif field in {"categoria_id","proveedor_principal_id"}:
                    if value is not None and (not isinstance(value,int) or value<=0):raise ValueError(f"{field} inválido")
                    values[field]=value
                elif field=="categoria":values[field]=_clean(value)
                elif field in {"stock_minimo","stock_minimo_granel_mg"}:
                    if not isinstance(value,int) or value<0:raise ValueError(f"{field} debe ser entero no negativo")
                    values[field]=value
                else:raise ValueError(f"Campo no editable: {field}")
            normalized[product_id]=values
        with self.database.transaction() as connection:
            result=[]
            for product_id,values in normalized.items():
                product=ProductRepository.get(connection,product_id)
                if product is None:raise LookupError(f"Producto {product_id} inexistente")
                final_kind=values.get("tipo_venta",product.tipo_venta)
                _validar_precio_variable(final_kind,values.get("precio_variable",product.precio_variable))
                if final_kind=="UNIDAD":values["unidad_granel"]=None
                else:values["unidad_granel"]=values.get("unidad_granel",product.unidad_granel or "PESO")
                if product.tipo_venta=="GRANEL" and final_kind=="GRANEL" and (product.unidad_granel or "PESO")!=values["unidad_granel"] and product.controla_inventario and product.existencia_granel_mg!=0:raise ValueError("No se puede cambiar entre Peso y Volumen porque el producto controla inventario y su existencia no es cero. Ajuste primero la existencia a cero.")
                result.append(ProductRepository.update_fields(connection,product_id,values))
            return result

    def cambiar_tipo_masivo(self, producto_ids, tipo_venta,unidad_granel=None):
        ids=list(dict.fromkeys(producto_ids));kind=_tipo(tipo_venta)
        if not ids:raise ValueError("Seleccione al menos un producto")
        unit=_unidad(kind,unidad_granel)
        return self.aplicar_cambios({product_id:{"tipo_venta":kind,"unidad_granel":unit} for product_id in ids})


def _clean(value):
    value = (value or "").strip()
    return value or None


def _tipo(value):
    value=(value or "").strip().upper()
    if value not in {"UNIDAD","GRANEL"}:raise ValueError("Tipo de venta inválido")
    return value


def _unidad(tipo_venta,value):
    if tipo_venta=="UNIDAD":return None
    unit=(value or "PESO").strip().upper()
    if unit not in {"PESO","VOLUMEN"}:raise ValueError("Unidad de granel inválida")
    return unit


def _validar_precio_variable(tipo_venta,value):
    if bool(value) and tipo_venta!="UNIDAD":
        raise ValueError("Precio variable actualmente disponible sólo para productos por unidad.")


def _duplicate_message(label, product):
    identity = product.descripcion or product.clave or product.codigo_truper or f"producto {product.id}"
    return f"Este {label} ya está vinculado a: {identity} (ID {product.id})"
