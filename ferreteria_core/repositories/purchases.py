from ferreteria_core.models import Purchase,PurchaseDetail,PurchasePresentation


class PurchasePresentationRepository:
    @staticmethod
    def list(connection,active_only=True):
        sql="SELECT * FROM presentaciones_compra"+(" WHERE activo=1" if active_only else "")+" ORDER BY nombre COLLATE NOCASE,id"
        return [PurchasePresentation.from_row(row) for row in connection.execute(sql)]
    @staticmethod
    def get(connection,item_id):
        row=connection.execute("SELECT * FROM presentaciones_compra WHERE id=?",(item_id,)).fetchone();return PurchasePresentation.from_row(row) if row else None
    @staticmethod
    def insert(connection,name,normalized):
        cursor=connection.execute("INSERT INTO presentaciones_compra(nombre,nombre_normalizado) VALUES(?,?)",(name,normalized));return PurchasePresentationRepository.get(connection,cursor.lastrowid)
    @staticmethod
    def update(connection,item_id,name,normalized):
        cursor=connection.execute("UPDATE presentaciones_compra SET nombre=?,nombre_normalizado=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(name,normalized,item_id))
        if cursor.rowcount!=1:raise LookupError("La presentación no existe")
        return PurchasePresentationRepository.get(connection,item_id)
    @staticmethod
    def set_active(connection,item_id,active):
        cursor=connection.execute("UPDATE presentaciones_compra SET activo=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(int(active),item_id))
        if cursor.rowcount!=1:raise LookupError("La presentación no existe")
        return PurchasePresentationRepository.get(connection,item_id)


class PurchaseRepository:
    @staticmethod
    def insert_header(connection,values):
        cursor=connection.execute("""INSERT INTO compras(folio,proveedor_id,proveedor_nombre_snapshot,folio_proveedor,fecha,total_centavos,notas)
            VALUES(:folio,:proveedor_id,:proveedor_nombre_snapshot,:folio_proveedor,:fecha,:total_centavos,:notas)""",values)
        purchase_id=cursor.lastrowid;folio=f"C-{purchase_id:06d}";connection.execute("UPDATE compras SET folio=? WHERE id=?",(folio,purchase_id));return purchase_id,folio
    @staticmethod
    def insert_detail(connection,values):
        cursor=connection.execute("""INSERT INTO compra_detalles(compra_id,producto_id,descripcion_snapshot,tipo_venta_snapshot,unidad_granel_snapshot,presentacion_id,presentacion_snapshot,cantidad_presentaciones,contenido_por_presentacion,cantidad_base,costo_presentacion_centavos,costo_unitario_centavos,subtotal_centavos,controla_inventario_snapshot)
            VALUES(:compra_id,:producto_id,:descripcion_snapshot,:tipo_venta_snapshot,:unidad_granel_snapshot,:presentacion_id,:presentacion_snapshot,:cantidad_presentaciones,:contenido_por_presentacion,:cantidad_base,:costo_presentacion_centavos,:costo_unitario_centavos,:subtotal_centavos,:controla_inventario_snapshot)""",values)
        return cursor.lastrowid
    @staticmethod
    def get(connection,purchase_id):
        row=connection.execute("SELECT * FROM compras WHERE id=?",(purchase_id,)).fetchone()
        if not row:return None
        details=tuple(PurchaseDetail(**{name:(bool(item[name]) if name=="controla_inventario_snapshot" else item[name]) for name in PurchaseDetail.__dataclass_fields__}) for item in connection.execute("SELECT * FROM compra_detalles WHERE compra_id=? ORDER BY id",(purchase_id,)))
        return Purchase(row["id"],row["folio"],row["proveedor_id"],row["proveedor_nombre_snapshot"],row["folio_proveedor"],row["fecha"],row["estado"],row["total_centavos"],row["notas"],details)
    @staticmethod
    def list(connection,state=None,limit=100,offset=0):
        where=" WHERE estado=?" if state else "";params=(state,limit,offset) if state else (limit,offset)
        rows=connection.execute(f"SELECT *,(SELECT count(*) FROM compra_detalles d WHERE d.compra_id=compras.id) lineas FROM compras{where} ORDER BY fecha DESC,id DESC LIMIT ? OFFSET ?",params)
        return [dict(row) for row in rows]
    @staticmethod
    def count(connection,state=None):
        return connection.execute("SELECT count(*) FROM compras"+(" WHERE estado=?" if state else ""),((state,) if state else ())).fetchone()[0]
    @staticmethod
    def cancel(connection,purchase_id):
        cursor=connection.execute("UPDATE compras SET estado='CANCELADA',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND estado='CONFIRMADA'",(purchase_id,))
        if cursor.rowcount!=1:raise ValueError("La compra no está confirmada o ya fue cancelada")
