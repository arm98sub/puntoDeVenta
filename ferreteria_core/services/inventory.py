from ferreteria_core.repositories import InventoryRepository, ProductRepository


class InventoryService:
    def __init__(self, database):
        self.database = database

    def registrar_entrada(self, producto_id: int, cantidad: int, nota=None):
        if not isinstance(cantidad, int) or cantidad <= 0:
            raise ValueError("La entrada debe ser un entero positivo")
        with self.database.transaction() as connection:
            product = ProductRepository.get(connection, producto_id)
            if product is None:
                raise LookupError("Producto inexistente")
            if not product.controla_inventario:raise ValueError("El producto no controla inventario")
            return InventoryRepository.update(connection, producto_id, product.existencia + cantidad, "ENTRADA", cantidad, note=nota)

    def ajustar_existencia(self, producto_id: int, nueva_existencia: int, motivo: str):
        if not isinstance(nueva_existencia, int) or nueva_existencia < 0:
            raise ValueError("La nueva existencia debe ser un entero no negativo")
        if not (motivo or "").strip():
            raise ValueError("El motivo es obligatorio")
        with self.database.transaction() as connection:
            product = ProductRepository.get(connection, producto_id)
            if product is None:
                raise LookupError("Producto inexistente")
            if not product.controla_inventario:raise ValueError("El producto no controla inventario")
            delta = nueva_existencia - product.existencia
            return InventoryRepository.update(connection, producto_id, nueva_existencia, "AJUSTE", delta, note=motivo.strip())

    def registrar_existencia_inicial(self, producto_id: int, existencia: int):
        return self.ajustar_existencia(producto_id, existencia, "INVENTARIO_INICIAL")

    def registrar_entrada_granel(self,producto_id:int,cantidad_mg:int,nota=None):
        if not isinstance(cantidad_mg,int) or cantidad_mg<=0:raise ValueError("La entrada en miligramos debe ser positiva")
        with self.database.transaction() as connection:
            product=ProductRepository.get(connection,producto_id)
            if product is None:raise LookupError("Producto inexistente")
            if not product.controla_inventario:raise ValueError("El producto no controla inventario")
            return InventoryRepository.update_bulk(connection,producto_id,product.existencia_granel_mg+cantidad_mg,"ENTRADA",cantidad_mg,note=nota)

    def ajustar_existencia_granel(self,producto_id:int,nueva_existencia_mg:int,motivo:str):
        if not isinstance(nueva_existencia_mg,int) or nueva_existencia_mg<0:raise ValueError("La existencia en miligramos debe ser no negativa")
        if not (motivo or "").strip():raise ValueError("El motivo es obligatorio")
        with self.database.transaction() as connection:
            product=ProductRepository.get(connection,producto_id)
            if product is None:raise LookupError("Producto inexistente")
            if not product.controla_inventario:raise ValueError("El producto no controla inventario")
            delta=nueva_existencia_mg-product.existencia_granel_mg
            return InventoryRepository.update_bulk(connection,producto_id,nueva_existencia_mg,"AJUSTE",delta,note=motivo.strip())

    def listar_movimientos(self,producto_id:int,limit=100):
        if not isinstance(limit,int) or limit<=0:raise ValueError("El límite debe ser positivo")
        with self.database.connect() as connection:return [dict(row) for row in InventoryRepository.list(connection,producto_id,limit)]
