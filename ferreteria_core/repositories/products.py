from ferreteria_core.models import Product


class ProductRepository:
    MAX_PAGE_SIZE = 200
    FILTERS = {
        "TODOS": "", "CON_EXISTENCIA": " AND ((tipo_venta='UNIDAD' AND existencia>0) OR (tipo_venta='GRANEL' AND existencia_granel_mg>0))", "SIN_EXISTENCIA": " AND ((tipo_venta='UNIDAD' AND existencia=0) OR (tipo_venta='GRANEL' AND existencia_granel_mg=0))",
        "CON_PRECIO": " AND precio_venta IS NOT NULL", "SIN_PRECIO": " AND precio_venta IS NULL",
        "CON_DESCRIPCION": " AND descripcion IS NOT NULL AND trim(descripcion)<>''",
        "SIN_DESCRIPCION": " AND (descripcion IS NULL OR trim(descripcion)='')",
        "TRUPER": " AND es_truper=1", "EXTERNOS": " AND es_truper=0",
        "REVISION": " AND requiere_revision=1",
        "UNIDAD": " AND tipo_venta='UNIDAD'", "GRANEL": " AND tipo_venta='GRANEL'",
        "CON_CONTROL": " AND controla_inventario=1", "SIN_CONTROL": " AND controla_inventario=0",
        "INACTIVOS": "",
    }
    SORTS = {
        "codigo_truper": "codigo_truper", "codigo_barras": "codigo_barras", "clave": "clave",
        "descripcion": "COALESCE(NULLIF(trim(descripcion),''),NULLIF(trim(clave),''),NULLIF(trim(codigo_truper),''),'')",
        "marca": "marca", "categoria": "categoria", "categoria_id":"COALESCE((SELECT nombre FROM categorias WHERE id=productos.categoria_id),'')", "tipo_venta": "tipo_venta", "unidad_granel":"unidad_granel", "precio_proveedor":"precio_proveedor", "porcentaje_ganancia":"CAST(porcentaje_ganancia AS REAL)", "precio_venta": "precio_venta", "existencia": "CASE WHEN tipo_venta='GRANEL' THEN existencia_granel_mg ELSE existencia END", "stock_minimo":"CASE WHEN tipo_venta='GRANEL' THEN stock_minimo_granel_mg ELSE stock_minimo END", "controla_inventario":"controla_inventario", "activo": "activo",
    }
    @staticmethod
    def get(connection, product_id: int) -> Product | None:
        row = connection.execute("SELECT * FROM productos WHERE id = ?", (product_id,)).fetchone()
        return Product.from_row(row) if row else None

    @staticmethod
    def exact(connection, field: str, value: str) -> Product | None:
        allowed = {"codigo_barras", "codigo_truper", "clave"}
        if field not in allowed:
            raise ValueError("Campo de búsqueda no permitido")
        row = connection.execute(f"SELECT * FROM productos WHERE {field} = ? AND activo = 1 ORDER BY id LIMIT 1", (value,)).fetchone()
        return Product.from_row(row) if row else None

    @staticmethod
    def exact_any(connection, field: str, value: str, exclude_id: int | None = None) -> Product | None:
        allowed = {"codigo_barras", "codigo_truper", "clave"}
        if field not in allowed:
            raise ValueError("Campo de búsqueda no permitido")
        sql = f"SELECT * FROM productos WHERE {field} = ?"
        params = [value]
        if exclude_id is not None:
            sql += " AND id <> ?"
            params.append(exclude_id)
        row = connection.execute(sql + " ORDER BY id LIMIT 1", params).fetchone()
        return Product.from_row(row) if row else None

    @staticmethod
    def search(connection, *, descripcion=None, marca=None, requiere_revision=None, limit=100):
        clauses = ["activo = 1"]
        params = []
        if descripcion:
            clauses.append("descripcion LIKE ? COLLATE NOCASE")
            params.append(f"%{descripcion}%")
        if marca:
            clauses.append("marca = ? COLLATE NOCASE")
            params.append(marca)
        if requiere_revision is not None:
            clauses.append("requiere_revision = ?")
            params.append(int(requiere_revision))
        params.append(limit)
        rows = connection.execute(f"SELECT * FROM productos WHERE {' AND '.join(clauses)} ORDER BY descripcion, id LIMIT ?", params)
        return [Product.from_row(row) for row in rows]

    @staticmethod
    def count_page(connection, term=None, product_filter="TODOS"):
        where, params = ProductRepository._page_filter(term, product_filter)
        active = "activo=0" if product_filter == "INACTIVOS" else "activo=1"
        return connection.execute(f"SELECT count(*) FROM productos WHERE {active}{where}", params).fetchone()[0]

    @staticmethod
    def list_page(connection, *, term=None, product_filter="TODOS", sort_column="descripcion", sort_direction="ASC", limit=50, offset=0):
        if not isinstance(limit, int) or limit <= 0 or limit > ProductRepository.MAX_PAGE_SIZE:
            raise ValueError(f"page_size debe estar entre 1 y {ProductRepository.MAX_PAGE_SIZE}")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset no puede ser negativo")
        where, params = ProductRepository._page_filter(term, product_filter)
        order = ProductRepository._order(sort_column, sort_direction)
        active = "activo=0" if product_filter == "INACTIVOS" else "activo=1"
        rows = connection.execute(
            f"""SELECT * FROM productos WHERE {active}{where}
                ORDER BY {order}, id
                LIMIT ? OFFSET ?""", (*params, limit, offset))
        return [Product.from_row(row) for row in rows]

    @staticmethod
    def _page_filter(term, product_filter="TODOS"):
        if product_filter not in ProductRepository.FILTERS:
            raise ValueError("Filtro de productos no permitido")
        filter_sql = ProductRepository.FILTERS[product_filter]
        term = (term or "").strip()
        if not term:
            return filter_sql, ()
        pattern = f"%{term}%"
        return (filter_sql + " AND NORMALIZE_TEXT(coalesce(descripcion,'') || ' ' || coalesce(clave,'') || ' ' || "
                "coalesce(codigo_truper,'') || ' ' || coalesce(codigo_barras,'')) LIKE NORMALIZE_TEXT(?)", (pattern,))

    @staticmethod
    def _order(column, direction):
        if column not in ProductRepository.SORTS or direction not in {"ASC","DESC"}:
            raise ValueError("Orden de productos no permitido")
        return f"{ProductRepository.SORTS[column]} COLLATE NOCASE {direction}"

    @staticmethod
    def matches_filter(connection, product_id, product_filter):
        where, params = ProductRepository._page_filter(None, product_filter)
        active = "activo=0" if product_filter == "INACTIVOS" else "activo=1"
        return connection.execute(f"SELECT 1 FROM productos WHERE id=? AND {active}{where}",(product_id,*params)).fetchone() is not None

    @staticmethod
    def update_sale_price(connection, product_id, cents):
        cursor = connection.execute(
            "UPDATE productos SET precio_venta=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (cents, product_id))
        if cursor.rowcount != 1:
            raise LookupError("El producto no existe")
        return ProductRepository.get(connection, product_id)

    @staticmethod
    def update_description(connection, product_id, description):
        cursor=connection.execute("UPDATE productos SET descripcion=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(description,product_id))
        if cursor.rowcount!=1:raise LookupError("El producto no existe")
        return ProductRepository.get(connection,product_id)

    @staticmethod
    def update_fields(connection, product_id, values):
        allowed={"descripcion","precio_catalogo_publico","precio_proveedor","porcentaje_ganancia","precio_venta","tipo_venta","unidad_granel","controla_inventario","activo","categoria","categoria_id","proveedor_principal_id","stock_minimo","stock_minimo_granel_mg","precio_variable"}
        if not values or not set(values)<=allowed:raise ValueError("Campos de producto no permitidos")
        assignments=",".join(f"{field}=?" for field in values)
        cursor=connection.execute(f"UPDATE productos SET {assignments},updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(*values.values(),product_id))
        if cursor.rowcount!=1:raise LookupError(f"Producto {product_id} inexistente")
        return ProductRepository.get(connection,product_id)

    @staticmethod
    def insert_external(connection, values: dict) -> Product:
        values={"tipo_venta":"UNIDAD","unidad_granel":None,"existencia_granel_mg":0,"stock_minimo_granel_mg":0,"precio_proveedor":None,"porcentaje_ganancia":None,"controla_inventario":1,"precio_variable":0,"categoria_id":None,"proveedor_principal_id":None,**values}
        cursor = connection.execute(
            """INSERT INTO productos
               (codigo_barras, clave, descripcion, marca, categoria, precio_venta,
                existencia, stock_minimo, es_truper, datos_completos, requiere_revision, tipo_venta,
                existencia_granel_mg,stock_minimo_granel_mg,precio_proveedor,porcentaje_ganancia,controla_inventario,unidad_granel,precio_variable,categoria_id,proveedor_principal_id)
               VALUES (:codigo_barras,:clave,:descripcion,:marca,:categoria,:precio_venta,
                       :existencia,:stock_minimo,0,1,0,:tipo_venta,:existencia_granel_mg,:stock_minimo_granel_mg,
                       :precio_proveedor,:porcentaje_ganancia,:controla_inventario,:unidad_granel,:precio_variable,:categoria_id,:proveedor_principal_id)""",
            values,
        )
        return ProductRepository.get(connection, cursor.lastrowid)

    @staticmethod
    def insert_truper_minimal(connection, values: dict) -> Product:
        cursor = connection.execute(
            """INSERT INTO productos
               (codigo_truper,codigo_barras,clave,descripcion,precio_venta,existencia,
                es_truper,datos_completos,requiere_revision,activo,tipo_venta,
                existencia_granel_mg,controla_inventario,unidad_granel,precio_variable)
               VALUES (:codigo_truper,:codigo_barras,:clave,:descripcion,:precio_venta,0,
                       1,0,1,1,:tipo_venta,0,:controla_inventario,:unidad_granel,:precio_variable)""", values)
        return ProductRepository.get(connection, cursor.lastrowid)

    @staticmethod
    def link_barcode(connection, product_id: int, barcode: str) -> Product:
        connection.execute(
            "UPDATE productos SET codigo_barras=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (barcode, product_id),
        )
        return ProductRepository.get(connection, product_id)

    @staticmethod
    def update_identity(connection, product_id: int, field: str, value: str | None) -> Product:
        if field not in {"codigo_barras", "codigo_truper"}:
            raise ValueError("Identificador no permitido")
        cursor = connection.execute(
            f"UPDATE productos SET {field}=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (value, product_id))
        if cursor.rowcount != 1:
            raise LookupError("El producto no existe")
        return ProductRepository.get(connection, product_id)

    @staticmethod
    def history_counts(connection, product_id: int) -> dict:
        return {
            "ventas": connection.execute("SELECT count(*) FROM detalle_venta WHERE producto_id=?", (product_id,)).fetchone()[0],
            "movimientos": connection.execute("SELECT count(*) FROM movimientos_inventario WHERE producto_id=?", (product_id,)).fetchone()[0],
        }

    @staticmethod
    def delete(connection, product_id: int) -> None:
        cursor = connection.execute("DELETE FROM productos WHERE id=?", (product_id,))
        if cursor.rowcount != 1:
            raise LookupError("El producto no existe")
