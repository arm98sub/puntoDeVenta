from ferreteria_core.models import Category,Supplier


class CategoryRepository:
    @staticmethod
    def list(connection,active_only=True):
        sql="SELECT * FROM categorias"+(" WHERE activo=1" if active_only else "")+" ORDER BY nombre COLLATE NOCASE,id"
        return [Category.from_row(row) for row in connection.execute(sql)]
    @staticmethod
    def get(connection,item_id):
        row=connection.execute("SELECT * FROM categorias WHERE id=?",(item_id,)).fetchone();return Category.from_row(row) if row else None
    @staticmethod
    def insert(connection,name,normalized):
        cursor=connection.execute("INSERT INTO categorias(nombre,nombre_normalizado) VALUES(?,?)",(name,normalized));return CategoryRepository.get(connection,cursor.lastrowid)
    @staticmethod
    def update(connection,item_id,name,normalized):
        cursor=connection.execute("UPDATE categorias SET nombre=?,nombre_normalizado=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(name,normalized,item_id))
        if cursor.rowcount!=1:raise LookupError("La categoría no existe")
        return CategoryRepository.get(connection,item_id)
    @staticmethod
    def set_active(connection,item_id,active):
        cursor=connection.execute("UPDATE categorias SET activo=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(int(active),item_id))
        if cursor.rowcount!=1:raise LookupError("La categoría no existe")
        return CategoryRepository.get(connection,item_id)


class SupplierRepository:
    @staticmethod
    def list(connection,active_only=True):
        sql="SELECT * FROM proveedores"+(" WHERE activo=1" if active_only else "")+" ORDER BY nombre COLLATE NOCASE,id"
        return [Supplier.from_row(row) for row in connection.execute(sql)]
    @staticmethod
    def get(connection,item_id):
        row=connection.execute("SELECT * FROM proveedores WHERE id=?",(item_id,)).fetchone();return Supplier.from_row(row) if row else None
    @staticmethod
    def insert(connection,values):
        cursor=connection.execute("INSERT INTO proveedores(nombre,nombre_normalizado,telefono,contacto,notas) VALUES(:nombre,:nombre_normalizado,:telefono,:contacto,:notas)",values);return SupplierRepository.get(connection,cursor.lastrowid)
    @staticmethod
    def update(connection,item_id,values):
        cursor=connection.execute("UPDATE proveedores SET nombre=:nombre,nombre_normalizado=:nombre_normalizado,telefono=:telefono,contacto=:contacto,notas=:notas,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=:id",{**values,"id":item_id})
        if cursor.rowcount!=1:raise LookupError("El proveedor no existe")
        return SupplierRepository.get(connection,item_id)
    @staticmethod
    def set_active(connection,item_id,active):
        cursor=connection.execute("UPDATE proveedores SET activo=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(int(active),item_id))
        if cursor.rowcount!=1:raise LookupError("El proveedor no existe")
        return SupplierRepository.get(connection,item_id)
