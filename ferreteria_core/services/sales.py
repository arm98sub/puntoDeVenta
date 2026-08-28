from ferreteria_core.money import decimal_a_centavos
from ferreteria_core.quantity import subtotal_granel_centavos
from ferreteria_core.repositories import InventoryRepository, ProductRepository, SaleRepository


PAYMENT_METHODS = {"EFECTIVO", "TRANSFERENCIA", "TARJETA", "OTRO"}


class SalesService:
    def __init__(self, database):
        self.database = database

    def crear_venta(self, items, metodo_pago, efectivo_recibido=None, descuento=0, nota=None):
        quantities = _normalize_items(items)
        method = (metodo_pago or "").strip().upper()
        if method not in PAYMENT_METHODS:
            raise ValueError(f"Método de pago inválido: {metodo_pago}")
        discount = decimal_a_centavos(descuento)
        received_input = decimal_a_centavos(efectivo_recibido)
        with self.database.transaction() as connection:
            products = []
            subtotal = 0
            inventory_requested={}
            for spec in quantities:
                product_id=spec["producto_id"]
                product = ProductRepository.get(connection, product_id)
                if product is None:
                    raise LookupError(f"Producto {product_id} inexistente")
                if not product.activo:
                    raise ValueError(f"El producto {product_id} está inactivo")
                if product.precio_venta is None and not product.precio_variable:
                    raise ValueError(f"El producto {product_id} no tiene precio de venta configurado.")
                if product.tipo_venta=="UNIDAD":
                    quantity=spec["cantidad"]
                    if "cantidad_mg" in spec:raise ValueError(f"El producto {product_id} se vende por unidad")
                    supplied=spec.get("precio_unitario_centavos")
                    if product.precio_variable:
                        if not isinstance(supplied,int) or isinstance(supplied,bool) or supplied<=0:raise ValueError(f"El producto {product_id} requiere un precio de venta mayor que cero")
                        unit_price=supplied
                    else:
                        if supplied is not None:raise ValueError(f"El producto {product_id} no admite precio variable")
                        unit_price=product.precio_venta
                    available=product.existencia;line_subtotal=unit_price*quantity
                else:
                    if product.precio_variable:raise ValueError("Precio variable actualmente disponible sólo para productos por unidad.")
                    if "cantidad" in spec:raise ValueError(f"El producto {product_id} se vende a granel")
                    quantity=spec["cantidad_mg"];available=product.existencia_granel_mg
                    line_subtotal=subtotal_granel_centavos(product.precio_venta,quantity)
                    unit_price=product.precio_venta
                inventory_requested[product.id]=inventory_requested.get(product.id,0)+quantity
                if product.controla_inventario and available < inventory_requested[product.id]:
                    name = product.descripcion or product.clave or product.codigo_truper or str(product.id)
                    raise ValueError(f"Stock insuficiente para {name}: disponible {available}, solicitado {quantity}")
                products.append((product,spec,line_subtotal,unit_price));subtotal+=line_subtotal
            if discount > subtotal:
                raise ValueError("El descuento no puede superar el subtotal")
            total = subtotal - discount
            if method == "EFECTIVO":
                if received_input is None:
                    raise ValueError("El efectivo recibido es obligatorio")
                if received_input < total:
                    raise ValueError(f"Efectivo insuficiente: total {total} centavos, recibido {received_input}")
                received, change = received_input, received_input - total
            else:
                received = change = None
            sale_id, folio = SaleRepository.next_identity(connection)
            SaleRepository.insert(connection, sale_id, folio, subtotal, discount, total, method, received, change, _clean(nota))
            inventory_remaining={}
            for product,spec,line_subtotal,unit_price in products:
                if product.tipo_venta=="UNIDAD":
                    quantity=spec["cantidad"];SaleRepository.insert_detail(connection,sale_id,product,quantity=quantity,unit_price=unit_price)
                    if product.controla_inventario:
                        before=inventory_remaining.get(product.id,product.existencia);after=before-quantity;InventoryRepository.update(connection,product.id,after,"VENTA",-quantity,f"VENTA:{folio}","Salida por venta");inventory_remaining[product.id]=after
                else:
                    mg=spec["cantidad_mg"];SaleRepository.insert_detail(connection,sale_id,product,cantidad_mg=mg,subtotal=line_subtotal)
                    if product.controla_inventario:InventoryRepository.update_bulk(connection,product.id,product.existencia_granel_mg-mg,"VENTA",-mg,f"VENTA:{folio}","Salida por venta")
            return SaleRepository.get(connection, sale_id=sale_id)

    def obtener_por_id(self, sale_id):
        with self.database.connect() as connection:
            return SaleRepository.get(connection, sale_id=sale_id)

    def obtener_por_folio(self, folio):
        with self.database.connect() as connection:
            return SaleRepository.get(connection, folio=folio.strip().upper())

    def ultimas_ventas(self, limit=20):
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("El límite debe ser positivo")
        with self.database.connect() as connection:
            return SaleRepository.list(connection, limit=limit)

    def ventas_por_rango(self, desde, hasta, limit=1000):
        with self.database.connect() as connection:
            return SaleRepository.list(connection, limit=limit, date_from=desde, date_to=hasta)

    def cancelar_venta(self, venta_id: int, motivo: str):
        reason = _clean(motivo)
        if not reason:
            raise ValueError("El motivo de cancelación es obligatorio")
        with self.database.transaction() as connection:
            sale = SaleRepository.get(connection, sale_id=venta_id)
            if sale is None:
                raise LookupError("La venta no existe")
            if sale.estado != "COMPLETADA":
                raise ValueError("Sólo una venta COMPLETADA puede cancelarse")
            for detail in sale.detalles:
                product = ProductRepository.get(connection, detail.producto_id)
                if product is None:
                    raise LookupError(f"Producto histórico {detail.producto_id} inexistente")
                if not detail.controla_inventario_snapshot:continue
                if detail.tipo_venta_snapshot=="GRANEL":
                    InventoryRepository.update_bulk(connection,product.id,product.existencia_granel_mg+detail.cantidad_mg,
                        "DEVOLUCION",detail.cantidad_mg,f"CANCELACION:{sale.folio}",reason,require_active=False)
                else:
                    InventoryRepository.update(connection, product.id, product.existencia + detail.cantidad,
                                               "DEVOLUCION", detail.cantidad, f"CANCELACION:{sale.folio}", reason,
                                               require_active=False)
            SaleRepository.cancel(connection, venta_id, reason)
            return SaleRepository.get(connection, sale_id=venta_id)


def _normalize_items(items):
    if not items:
        raise ValueError("El carrito está vacío")
    result = []
    for item in items:
        try:product_id=item["producto_id"]
        except (KeyError,TypeError) as exc:raise ValueError("Cada item requiere producto_id") from exc
        if not isinstance(product_id,int) or product_id<=0:raise ValueError("Producto inválido")
        has_units="cantidad" in item;has_bulk="cantidad_mg" in item
        if has_units==has_bulk:raise ValueError("Cada item requiere cantidad o cantidad_mg, pero no ambas")
        field="cantidad" if has_units else "cantidad_mg";value=item[field]
        if not isinstance(value,int) or value<=0:raise ValueError("Producto y cantidad deben ser enteros positivos")
        price=item.get("precio_unitario_centavos")
        if price is not None and (not isinstance(price,int) or isinstance(price,bool) or price<=0):raise ValueError("El precio unitario debe ser un entero positivo en centavos")
        key=(product_id,field,price)
        found=next((row for row in result if row["_key"]==key),None)
        if found:found[field]+=value
        else:result.append({"_key":key,"producto_id":product_id,field:value,**({"precio_unitario_centavos":price} if price is not None else {})})
    for row in result:row.pop("_key")
    return result


def _clean(value):
    value = (value or "").strip()
    return value or None
