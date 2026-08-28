from ferreteria_core.models import Sale, SaleDetail


class SaleRepository:
    @staticmethod
    def next_identity(connection):
        sale_id = connection.execute("SELECT coalesce(max(id),0)+1 FROM ventas").fetchone()[0]
        return sale_id, f"V-{sale_id:06d}"

    @staticmethod
    def insert(connection, sale_id, folio, subtotal, discount, total, method, received, change, note):
        connection.execute(
            """INSERT INTO ventas
               (id,folio,subtotal_centavos,descuento_centavos,total_centavos,metodo_pago,
                efectivo_recibido_centavos,cambio_centavos,estado,nota)
               VALUES (?,?,?,?,?,?,?,?, 'COMPLETADA',?)""",
            (sale_id, folio, subtotal, discount, total, method, received, change, note),
        )

    @staticmethod
    def insert_detail(connection, sale_id, product, quantity=None, cantidad_mg=None, subtotal=None,unit_price=None):
        unit = product.precio_venta if unit_price is None else unit_price
        bulk=product.tipo_venta=="GRANEL"
        stored_quantity=1 if bulk else quantity
        line_subtotal=subtotal if bulk else unit*quantity
        connection.execute(
            """INSERT INTO detalle_venta
               (venta_id,producto_id,codigo_barras_snapshot,codigo_truper_snapshot,clave_snapshot,
                descripcion_snapshot,cantidad,precio_unitario_centavos,subtotal_centavos,
                tipo_venta_snapshot,cantidad_mg,unidad_snapshot,precio_por_kg_centavos,controla_inventario_snapshot,
                unidad_granel_snapshot)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sale_id, product.id, product.codigo_barras, product.codigo_truper, product.clave,
             product.descripcion, stored_quantity, unit, line_subtotal,product.tipo_venta,
             cantidad_mg,"MG" if bulk else "PZA",unit if bulk else None,int(product.controla_inventario),
             (product.unidad_granel or "PESO") if bulk else None),
        )

    @staticmethod
    def get(connection, *, sale_id=None, folio=None):
        if (sale_id is None) == (folio is None):
            raise ValueError("Indique id o folio")
        field, value = ("id", sale_id) if sale_id is not None else ("folio", folio)
        row = connection.execute(f"SELECT * FROM ventas WHERE {field}=?", (value,)).fetchone()
        return SaleRepository._assemble(connection, row) if row else None

    @staticmethod
    def list(connection, limit=20, date_from=None, date_to=None):
        clauses, params = [], []
        if date_from is not None:
            clauses.append("fecha_hora >= ?"); params.append(date_from)
        if date_to is not None:
            clauses.append("fecha_hora <= ?"); params.append(date_to)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        rows = connection.execute(f"SELECT * FROM ventas{where} ORDER BY fecha_hora DESC, id DESC LIMIT ?", params)
        return [SaleRepository._assemble(connection, row) for row in rows]

    @staticmethod
    def daily_summary(connection,start_utc,end_utc):
        totals=connection.execute("""SELECT
            sum(CASE WHEN estado='COMPLETADA' THEN 1 ELSE 0 END) completadas,
            coalesce(sum(CASE WHEN estado='COMPLETADA' THEN total_centavos ELSE 0 END),0) venta_neta,
            sum(CASE WHEN estado='CANCELADA' THEN 1 ELSE 0 END) canceladas,
            coalesce(sum(CASE WHEN estado='CANCELADA' THEN total_centavos ELSE 0 END),0) importe_cancelado,
            coalesce(sum(CASE WHEN estado='COMPLETADA' THEN descuento_centavos ELSE 0 END),0) descuentos
            FROM ventas WHERE fecha_hora>=? AND fecha_hora<?""",(start_utc,end_utc)).fetchone()
        methods=connection.execute("""SELECT metodo_pago,sum(total_centavos) total
            FROM ventas WHERE estado='COMPLETADA' AND fecha_hora>=? AND fecha_hora<?
            GROUP BY metodo_pago ORDER BY metodo_pago""",(start_utc,end_utc)).fetchall()
        products=connection.execute("""SELECT d.producto_id,d.descripcion_snapshot,d.clave_snapshot,
            d.codigo_truper_snapshot,d.codigo_barras_snapshot,d.tipo_venta_snapshot,
            coalesce(d.unidad_granel_snapshot,CASE WHEN d.tipo_venta_snapshot='GRANEL' THEN 'PESO' END) unidad_granel_snapshot,
            sum(CASE WHEN d.tipo_venta_snapshot='UNIDAD' THEN d.cantidad ELSE 0 END) cantidad,
            sum(CASE WHEN d.tipo_venta_snapshot='GRANEL' THEN d.cantidad_mg ELSE 0 END) cantidad_granel,
            sum(d.subtotal_centavos) importe
            FROM ventas v JOIN detalle_venta d ON d.venta_id=v.id
            WHERE v.estado='COMPLETADA' AND v.fecha_hora>=? AND v.fecha_hora<?
            GROUP BY d.producto_id,d.descripcion_snapshot,d.clave_snapshot,d.codigo_truper_snapshot,
                     d.codigo_barras_snapshot,d.tipo_venta_snapshot,unidad_granel_snapshot
            ORDER BY coalesce(d.descripcion_snapshot,d.clave_snapshot,d.codigo_truper_snapshot,d.codigo_barras_snapshot,'Producto')""",(start_utc,end_utc)).fetchall()
        return totals,methods,products

    @staticmethod
    def details(connection, sale_id):
        rows = connection.execute("SELECT * FROM detalle_venta WHERE venta_id=? ORDER BY id", (sale_id,))
        return [SaleDetail(**{name: row[name] for name in SaleDetail.__dataclass_fields__}) for row in rows]

    @staticmethod
    def cancel(connection, sale_id, reason):
        connection.execute(
            """UPDATE ventas SET estado='CANCELADA',
               nota=CASE WHEN nota IS NULL OR nota='' THEN 'CANCELACIÓN: ' || ?
                         ELSE nota || char(10) || 'CANCELACIÓN: ' || ? END WHERE id=?""",
            (reason, reason, sale_id),
        )

    @staticmethod
    def _assemble(connection, row):
        values = {name: row[name] for name in Sale.__dataclass_fields__ if name != "detalles"}
        values["detalles"] = SaleRepository.details(connection, row["id"])
        return Sale(**values)
