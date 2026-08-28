import sqlite3

from ferreteria_core.repositories import InventoryRepository, ProductRepository
from .products import validar_codigo_barras


class InitialInventoryService:
    """Operaciones atómicas para el futuro flujo de escaneo inicial."""

    def __init__(self, database):
        self.database = database

    def resolver_escaneo(self, codigo_barras):
        barcode = validar_codigo_barras(codigo_barras)
        with self.database.connect() as connection:
            return ProductRepository.exact(connection, "codigo_barras", barcode)

    def vincular_y_capturar(self, producto_id: int, codigo_barras: str, existencia: int):
        barcode = validar_codigo_barras(codigo_barras)
        if not isinstance(existencia, int) or existencia < 0:
            raise ValueError("La existencia inicial debe ser un entero no negativo")
        try:
            with self.database.transaction() as connection:
                product = ProductRepository.get(connection, producto_id)
                if product is None or not product.activo:
                    raise LookupError("Producto inexistente o inactivo")
                if product.codigo_barras and product.codigo_barras != barcode:
                    raise ValueError("El producto ya tiene otro código de barras")
                if not product.codigo_barras:
                    ProductRepository.link_barcode(connection, producto_id, barcode)
                InventoryRepository.update(connection, producto_id, existencia, "AJUSTE", existencia - product.existencia,
                                           "INVENTARIO_INICIAL", "Captura inicial por escaneo")
                return ProductRepository.get(connection, producto_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError("El código de barras pertenece a otro producto") from exc
