from dataclasses import dataclass
from ferreteria_core.money import centavos_a_decimal
from ferreteria_core.quantity import subtotal_granel_centavos
from ferreteria_core.repositories import ProductRepository

class InsufficientStockError(ValueError):
    def __init__(self,product,requested):
        self.product=product;self.available=product.existencia_granel_mg if product.tipo_venta=="GRANEL" else product.existencia;self.requested=requested
        name=product.descripcion or product.clave or product.codigo_truper or str(product.id)
        super().__init__(f"Existencia insuficiente para {name}: disponible {self.available}, solicitada {requested}")
class BulkQuantityRequired(ValueError):
    def __init__(self,product):self.product=product;super().__init__("Indique la cantidad o importe del producto a granel")
class VariablePriceRequired(ValueError):
    def __init__(self,product):self.product=product;super().__init__("Capture el precio de esta venta")

@dataclass(frozen=True)
class CartItem:
    linea_id:tuple;producto_id:int;cantidad:int;cantidad_mg:int|None;tipo_venta:str;descripcion:str|None;clave:str|None
    precio_unitario_centavos:int;existencia:int;existencia_granel_mg:int;unidad_granel:str|None;precio_variable:bool
    @property
    def subtotal_centavos(self):return self.precio_unitario_centavos*self.cantidad if self.tipo_venta=="UNIDAD" else subtotal_granel_centavos(self.precio_unitario_centavos,self.cantidad_mg)

class Cart:
    def __init__(self,database):self.database=database;self._lines={}
    def agregar_producto(self,producto_id:int,cantidad=1,precio_unitario_centavos=None):
        _positive(cantidad);product=self._load(producto_id,True)
        if product.tipo_venta=="GRANEL":raise BulkQuantityRequired(product)
        if product.precio_variable:
            if precio_unitario_centavos is None:raise VariablePriceRequired(product)
            _positive_price(precio_unitario_centavos);price=precio_unitario_centavos
        else:
            if product.precio_venta is None:raise ValueError("El producto no tiene precio de venta configurado.")
            price=product.precio_venta
        key=(product.id,price if product.precio_variable else None);current=self._lines.get(key,{}).get("cantidad",0);requested=self._current_units(product.id)+cantidad
        if product.controla_inventario and requested>product.existencia:raise InsufficientStockError(product,requested)
        self._lines[key]={"tipo":"UNIDAD","cantidad":current+cantidad,"precio":price};return self.item(key)
    def agregar_granel(self,producto_id:int,cantidad_mg:int):
        if not isinstance(cantidad_mg,int) or cantidad_mg<=0:raise ValueError("La cantidad de granel debe ser positiva")
        product=self._load(producto_id);key=(product.id,None)
        if product.tipo_venta!="GRANEL":raise ValueError("El producto no se vende a granel")
        requested=self._current_mg(product.id)+cantidad_mg
        if product.controla_inventario and requested>product.existencia_granel_mg:raise InsufficientStockError(product,requested)
        self._lines[key]={"tipo":"GRANEL","cantidad_mg":requested,"precio":product.precio_venta};return self.item(key)
    def agregar_por_barcode(self,barcode,cantidad=1):
        with self.database.connect() as connection:product=ProductRepository.exact(connection,"codigo_barras",barcode.strip())
        if product is None:raise LookupError("No existe un producto activo con ese código de barras")
        return self.agregar_producto(product.id,cantidad)
    def incrementar_linea(self,key,cantidad=1):
        item=self.item(key);return self.agregar_producto(item.producto_id,cantidad,item.precio_unitario_centavos)
    def decrementar_linea(self,key,cantidad=1):
        _positive(cantidad);item=self.item(key);return self.establecer_cantidad_linea(key,item.cantidad-cantidad)
    def establecer_cantidad_linea(self,key,cantidad):
        _positive(cantidad);item=self.item(key);product=self._load(item.producto_id,True);requested=self._current_units(product.id)-item.cantidad+cantidad
        if product.controla_inventario and requested>product.existencia:raise InsufficientStockError(product,requested)
        self._lines[key]["cantidad"]=cantidad;return self.item(key)
    def cambiar_precio_linea(self,key,nuevo_precio_centavos):
        _positive_price(nuevo_precio_centavos);item=self.item(key);product=self._load(item.producto_id,True)
        if not product.precio_variable:raise ValueError("Sólo puede cambiar el precio de productos con precio variable.")
        new_key=(product.id,nuevo_precio_centavos);spec=self._lines.pop(key)
        if new_key in self._lines:self._lines[new_key]["cantidad"]+=spec["cantidad"]
        else:spec["precio"]=nuevo_precio_centavos;self._lines[new_key]=spec
        return self.item(new_key)
    def incrementar(self,product_id,cantidad=1):return self.incrementar_linea(self._unique_key(product_id),cantidad)
    def decrementar(self,product_id,cantidad=1):return self.decrementar_linea(self._unique_key(product_id),cantidad)
    def establecer_cantidad(self,product_id,cantidad):return self.establecer_cantidad_linea(self._unique_key(product_id),cantidad)
    def establecer_peso(self,product_id,cantidad_mg):
        if not isinstance(cantidad_mg,int) or cantidad_mg<0:raise ValueError("La cantidad de granel debe ser no negativa")
        key=self._unique_key(product_id)
        if cantidad_mg==0:self.eliminar_linea(key);return None
        product=self._load(product_id)
        if product.tipo_venta!="GRANEL":raise ValueError("El producto no se vende a granel")
        if product.controla_inventario and cantidad_mg>product.existencia_granel_mg:raise InsufficientStockError(product,cantidad_mg)
        self._lines[key]["cantidad_mg"]=cantidad_mg;return self.item(key)
    def eliminar_linea(self,key):
        if self._lines.pop(key,None) is None:raise LookupError("La línea no está en el carrito")
    def eliminar(self,product_id):self.eliminar_linea(self._unique_key(product_id))
    def vaciar(self):self._lines.clear()
    def item(self,key):
        if isinstance(key,int):key=self._unique_key(key)
        spec=self._lines.get(key)
        if spec is None:raise LookupError("La línea no está en el carrito")
        product=self._load(key[0],True);bulk=spec["tipo"]=="GRANEL"
        return CartItem(key,product.id,0 if bulk else spec["cantidad"],spec.get("cantidad_mg"),spec["tipo"],product.descripcion,product.clave,spec["precio"],product.existencia,product.existencia_granel_mg,product.unidad_granel,product.precio_variable)
    @property
    def items(self):return [self.item(key) for key in self._lines]
    @property
    def total_centavos(self):return sum(i.subtotal_centavos for i in self.items)
    @property
    def total(self):return centavos_a_decimal(self.total_centavos)
    @property
    def cantidad_articulos(self):return sum(i.cantidad if i.tipo_venta=="UNIDAD" else 1 for i in self.items)
    def excede_stock(self):
        result=[]
        for item in self.items:
            product=self._load(item.producto_id,True);used=self._current_units(product.id) if item.tipo_venta=="UNIDAD" else self._current_mg(product.id);available=product.existencia if item.tipo_venta=="UNIDAD" else product.existencia_granel_mg
            if product.controla_inventario and used>available:result.append(item)
        return result
    def como_items_venta(self):return [{"producto_id":i.producto_id,"cantidad":i.cantidad,**({"precio_unitario_centavos":i.precio_unitario_centavos} if i.precio_variable else {})} if i.tipo_venta=="UNIDAD" else {"producto_id":i.producto_id,"cantidad_mg":i.cantidad_mg} for i in self.items]
    def _current_units(self,pid):return sum(s.get("cantidad",0) for k,s in self._lines.items() if k[0]==pid)
    def _current_mg(self,pid):return sum(s.get("cantidad_mg",0) for k,s in self._lines.items() if k[0]==pid)
    def _unique_key(self,pid):
        keys=[k for k in self._lines if k[0]==pid]
        if len(keys)!=1:raise LookupError("El producto no tiene una única línea en el carrito")
        return keys[0]
    def _load(self,pid,allow_variable=False):
        with self.database.connect() as connection:product=ProductRepository.get(connection,pid)
        if product is None or not product.activo:raise LookupError("El producto no existe o está inactivo")
        if product.precio_variable and product.tipo_venta!="UNIDAD":raise ValueError("Precio variable actualmente disponible sólo para productos por unidad.")
        if product.precio_venta is None and not (allow_variable and product.precio_variable):raise ValueError("El producto no tiene precio de venta configurado.")
        return product
def _positive(v):
    if not isinstance(v,int) or isinstance(v,bool) or v<=0:raise ValueError("La cantidad debe ser un entero positivo")
def _positive_price(v):
    if not isinstance(v,int) or isinstance(v,bool) or v<=0:raise ValueError("El precio de esta venta debe ser mayor que cero.")
