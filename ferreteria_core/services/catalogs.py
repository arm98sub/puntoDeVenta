import sqlite3
import unicodedata

from ferreteria_core.repositories import CategoryRepository,SupplierRepository


GENERAL_CATEGORIES=("Refrescos","Agua y bebidas","Botanas","Dulces","Galletas","Panadería","Lácteos","Huevos","Enlatados","Abarrotes secos","Cereales","Limpieza","Higiene personal","Congelados","Frutas y verduras","Carnes y embutidos","Varios")


def normalize_catalog_name(value):
    normalized=unicodedata.normalize("NFKD"," ".join((value or "").split()).casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))
def display_catalog_name(value):return " ".join((value or "").split())


class CategoryService:
    def __init__(self,database):self.database=database
    def listar_activas(self):
        with self.database.connect() as connection:return CategoryRepository.list(connection,True)
    def listar_todas(self):
        with self.database.connect() as connection:return CategoryRepository.list(connection,False)
    def obtener(self,item_id):
        with self.database.connect() as connection:return CategoryRepository.get(connection,item_id)
    def crear(self,nombre):
        name=display_catalog_name(nombre);normalized=normalize_catalog_name(name)
        if not normalized:raise ValueError("El nombre de la categoría es obligatorio")
        try:
            with self.database.transaction() as connection:return CategoryRepository.insert(connection,name,normalized)
        except sqlite3.IntegrityError as exc:raise ValueError("La categoría ya existe") from exc
    def editar(self,item_id,nombre):
        name=display_catalog_name(nombre);normalized=normalize_catalog_name(name)
        if not normalized:raise ValueError("El nombre de la categoría es obligatorio")
        try:
            with self.database.transaction() as connection:return CategoryRepository.update(connection,item_id,name,normalized)
        except sqlite3.IntegrityError as exc:raise ValueError("La categoría ya existe") from exc
    def desactivar(self,item_id):return self._active(item_id,False)
    def reactivar(self,item_id):return self._active(item_id,True)
    def _active(self,item_id,active):
        with self.database.transaction() as connection:return CategoryRepository.set_active(connection,item_id,active)


class SupplierService:
    def __init__(self,database):self.database=database
    def listar_activos(self):
        with self.database.connect() as connection:return SupplierRepository.list(connection,True)
    def listar_todos(self):
        with self.database.connect() as connection:return SupplierRepository.list(connection,False)
    def obtener(self,item_id):
        with self.database.connect() as connection:return SupplierRepository.get(connection,item_id)
    def crear(self,nombre,telefono=None,contacto=None,notas=None):return self._save(None,nombre,telefono,contacto,notas)
    def editar(self,item_id,nombre,telefono=None,contacto=None,notas=None):return self._save(item_id,nombre,telefono,contacto,notas)
    def _save(self,item_id,nombre,telefono,contacto,notas):
        name=display_catalog_name(nombre);normalized=normalize_catalog_name(name)
        if not normalized:raise ValueError("El nombre del proveedor es obligatorio")
        values={"nombre":name,"nombre_normalizado":normalized,"telefono":_optional(telefono),"contacto":_optional(contacto),"notas":_optional(notas)}
        try:
            with self.database.transaction() as connection:
                return SupplierRepository.insert(connection,values) if item_id is None else SupplierRepository.update(connection,item_id,values)
        except sqlite3.IntegrityError as exc:raise ValueError("El proveedor ya existe") from exc
    def desactivar(self,item_id):return self._active(item_id,False)
    def reactivar(self,item_id):return self._active(item_id,True)
    def _active(self,item_id,active):
        with self.database.transaction() as connection:return SupplierRepository.set_active(connection,item_id,active)


def seed_general_categories(database):
    service=CategoryService(database);existing={normalize_catalog_name(item.nombre) for item in service.listar_todas()}
    for name in GENERAL_CATEGORIES:
        if normalize_catalog_name(name) not in existing:service.crear(name)
    return service.listar_todas()


def _optional(value):return (value or "").strip() or None
