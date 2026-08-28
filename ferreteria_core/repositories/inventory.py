class InventoryRepository:
    @staticmethod
    def list(connection,product_id,limit=100):
        return connection.execute("SELECT * FROM movimientos_inventario WHERE producto_id=? ORDER BY fecha_hora DESC,id DESC LIMIT ?",(product_id,limit)).fetchall()
    @staticmethod
    def update(connection, product_id, new_stock, movement_type, quantity, reference=None, note=None, require_active=True):
        sql = "SELECT existencia FROM productos WHERE id=?" + (" AND activo=1" if require_active else "")
        row = connection.execute(sql, (product_id,)).fetchone()
        if row is None:
            raise LookupError("Producto inexistente o inactivo")
        old_stock = row[0]
        if new_stock < 0:
            raise ValueError("La existencia no puede ser negativa")
        connection.execute(
            "UPDATE productos SET existencia=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (new_stock, product_id),
        )
        cursor = connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id,tipo,cantidad,existencia_anterior,existencia_nueva,referencia,nota)
               VALUES (?,?,?,?,?,?,?)""",
            (product_id, movement_type, quantity, old_stock, new_stock, reference, note),
        )
        return cursor.lastrowid

    @staticmethod
    def update_bulk(connection, product_id, new_stock_mg, movement_type, quantity_mg, reference=None, note=None, require_active=True):
        sql="SELECT existencia_granel_mg,tipo_venta FROM productos WHERE id=?"+(" AND activo=1" if require_active else "")
        row=connection.execute(sql,(product_id,)).fetchone()
        if row is None:raise LookupError("Producto inexistente o inactivo")
        if row["tipo_venta"]!="GRANEL" and require_active:raise ValueError("El producto no se vende a granel")
        old=row["existencia_granel_mg"]
        if not isinstance(new_stock_mg,int) or new_stock_mg<0:raise ValueError("La existencia a granel no puede ser negativa")
        connection.execute("UPDATE productos SET existencia_granel_mg=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(new_stock_mg,product_id))
        cursor=connection.execute("""INSERT INTO movimientos_inventario
            (producto_id,tipo,cantidad,existencia_anterior,existencia_nueva,referencia,nota,
             tipo_venta_snapshot,cantidad_mg,existencia_anterior_mg,existencia_nueva_mg)
            VALUES (?,?,?,?,?,?,?,'GRANEL',?,?,?)""",
            (product_id,movement_type,0,0,0,reference,note,quantity_mg,old,new_stock_mg))
        return cursor.lastrowid
