MIGRATION_9 = """
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    nombre_normalizado TEXT NOT NULL UNIQUE,
    activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    nombre_normalizado TEXT NOT NULL UNIQUE,
    telefono TEXT,
    contacto TEXT,
    notas TEXT,
    activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
ALTER TABLE productos ADD COLUMN categoria_id INTEGER REFERENCES categorias(id);
ALTER TABLE productos ADD COLUMN proveedor_principal_id INTEGER REFERENCES proveedores(id);
INSERT OR IGNORE INTO categorias(nombre,nombre_normalizado)
SELECT trim(categoria),NORMALIZE_TEXT(trim(categoria)) FROM productos
WHERE categoria IS NOT NULL AND trim(categoria)<>'' GROUP BY NORMALIZE_TEXT(trim(categoria));
UPDATE productos SET categoria_id=(SELECT id FROM categorias WHERE nombre_normalizado=NORMALIZE_TEXT(trim(productos.categoria)))
WHERE categoria IS NOT NULL AND trim(categoria)<>'';
CREATE INDEX IF NOT EXISTS ix_productos_categoria_id ON productos(categoria_id);
CREATE INDEX IF NOT EXISTS ix_productos_proveedor_principal_id ON productos(proveedor_principal_id);
"""


MIGRATIONS = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_truper TEXT,
            codigo_barras TEXT,
            clave TEXT,
            descripcion TEXT,
            descripcion_familia TEXT,
            presentacion TEXT,
            marca TEXT,
            categoria TEXT,
            precio_catalogo_publico INTEGER CHECK(precio_catalogo_publico IS NULL OR precio_catalogo_publico >= 0),
            precio_venta INTEGER CHECK(precio_venta IS NULL OR precio_venta >= 0),
            existencia INTEGER NOT NULL DEFAULT 0 CHECK(existencia >= 0),
            stock_minimo INTEGER NOT NULL DEFAULT 0 CHECK(stock_minimo >= 0),
            es_truper INTEGER NOT NULL DEFAULT 0 CHECK(es_truper IN (0,1)),
            datos_completos INTEGER NOT NULL DEFAULT 0 CHECK(datos_completos IN (0,1)),
            confianza_extraccion TEXT,
            requiere_revision INTEGER NOT NULL DEFAULT 1 CHECK(requiere_revision IN (0,1)),
            activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_productos_codigo_truper
          ON productos(codigo_truper) WHERE codigo_truper IS NOT NULL AND codigo_truper <> '';
        CREATE UNIQUE INDEX IF NOT EXISTS ux_productos_codigo_barras
          ON productos(codigo_barras) WHERE codigo_barras IS NOT NULL AND codigo_barras <> '';
        CREATE INDEX IF NOT EXISTS ix_productos_clave ON productos(clave);
        CREATE INDEX IF NOT EXISTS ix_productos_marca ON productos(marca);
        CREATE TABLE IF NOT EXISTS movimientos_inventario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL REFERENCES productos(id),
            tipo TEXT NOT NULL CHECK(tipo IN ('ENTRADA','VENTA','AJUSTE','DEVOLUCION')),
            cantidad INTEGER NOT NULL,
            existencia_anterior INTEGER NOT NULL CHECK(existencia_anterior >= 0),
            existencia_nueva INTEGER NOT NULL CHECK(existencia_nueva >= 0),
            referencia TEXT,
            nota TEXT,
            fecha_hora TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS ix_movimientos_producto ON movimientos_inventario(producto_id, fecha_hora);
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT NOT NULL UNIQUE,
            fecha_hora TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            subtotal_centavos INTEGER NOT NULL CHECK(subtotal_centavos >= 0),
            descuento_centavos INTEGER NOT NULL DEFAULT 0 CHECK(descuento_centavos >= 0),
            total_centavos INTEGER NOT NULL CHECK(total_centavos >= 0),
            metodo_pago TEXT NOT NULL CHECK(metodo_pago IN ('EFECTIVO','TRANSFERENCIA','TARJETA','OTRO')),
            efectivo_recibido_centavos INTEGER CHECK(efectivo_recibido_centavos IS NULL OR efectivo_recibido_centavos >= 0),
            cambio_centavos INTEGER CHECK(cambio_centavos IS NULL OR cambio_centavos >= 0),
            estado TEXT NOT NULL DEFAULT 'COMPLETADA' CHECK(estado IN ('COMPLETADA','CANCELADA')),
            nota TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS ix_ventas_fecha ON ventas(fecha_hora DESC);
        CREATE TABLE IF NOT EXISTS detalle_venta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL REFERENCES ventas(id),
            producto_id INTEGER NOT NULL REFERENCES productos(id),
            codigo_barras_snapshot TEXT,
            codigo_truper_snapshot TEXT,
            clave_snapshot TEXT,
            descripcion_snapshot TEXT,
            cantidad INTEGER NOT NULL CHECK(cantidad > 0),
            precio_unitario_centavos INTEGER NOT NULL CHECK(precio_unitario_centavos >= 0),
            subtotal_centavos INTEGER NOT NULL CHECK(subtotal_centavos >= 0)
        );
        CREATE INDEX IF NOT EXISTS ix_detalle_venta ON detalle_venta(venta_id);
        """,
    ),
    (
        3,
        """
        DROP INDEX IF EXISTS ux_productos_codigo_barras;
        DROP INDEX IF EXISTS ux_productos_codigo_truper;
        CREATE UNIQUE INDEX ux_productos_codigo_barras ON productos(codigo_barras);
        CREATE UNIQUE INDEX ux_productos_codigo_truper ON productos(codigo_truper);
        """,
    ),
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS configuracion_negocio (
            id INTEGER PRIMARY KEY CHECK(id=1),
            nombre_negocio TEXT NOT NULL DEFAULT 'FERRETERÍA',
            direccion TEXT,
            telefono TEXT,
            rfc TEXT,
            logo_path TEXT,
            mensaje_ticket TEXT,
            moneda TEXT NOT NULL DEFAULT 'MXN',
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        INSERT OR IGNORE INTO configuracion_negocio
            (id,nombre_negocio,direccion,telefono,mensaje_ticket,moneda)
        VALUES (1,'FERRETERÍA','','','Gracias por su compra','MXN');
        """,
    ),
    (
        5,
        """
        ALTER TABLE productos ADD COLUMN tipo_venta TEXT NOT NULL DEFAULT 'UNIDAD'
            CHECK(tipo_venta IN ('UNIDAD','GRANEL'));
        ALTER TABLE productos ADD COLUMN existencia_granel_mg INTEGER NOT NULL DEFAULT 0
            CHECK(existencia_granel_mg >= 0);
        ALTER TABLE productos ADD COLUMN stock_minimo_granel_mg INTEGER NOT NULL DEFAULT 0
            CHECK(stock_minimo_granel_mg >= 0);

        ALTER TABLE movimientos_inventario ADD COLUMN tipo_venta_snapshot TEXT NOT NULL DEFAULT 'UNIDAD'
            CHECK(tipo_venta_snapshot IN ('UNIDAD','GRANEL'));
        ALTER TABLE movimientos_inventario ADD COLUMN cantidad_mg INTEGER;
        ALTER TABLE movimientos_inventario ADD COLUMN existencia_anterior_mg INTEGER;
        ALTER TABLE movimientos_inventario ADD COLUMN existencia_nueva_mg INTEGER;

        ALTER TABLE detalle_venta ADD COLUMN tipo_venta_snapshot TEXT NOT NULL DEFAULT 'UNIDAD'
            CHECK(tipo_venta_snapshot IN ('UNIDAD','GRANEL'));
        ALTER TABLE detalle_venta ADD COLUMN cantidad_mg INTEGER CHECK(cantidad_mg IS NULL OR cantidad_mg > 0);
        ALTER TABLE detalle_venta ADD COLUMN unidad_snapshot TEXT NOT NULL DEFAULT 'PZA'
            CHECK(unidad_snapshot IN ('PZA','MG'));
        ALTER TABLE detalle_venta ADD COLUMN precio_por_kg_centavos INTEGER
            CHECK(precio_por_kg_centavos IS NULL OR precio_por_kg_centavos >= 0);
        CREATE INDEX IF NOT EXISTS ix_productos_tipo_venta ON productos(tipo_venta);
        """,
    ),
    (
        6,
        """
        ALTER TABLE productos ADD COLUMN precio_proveedor INTEGER
            CHECK(precio_proveedor IS NULL OR precio_proveedor >= 0);
        ALTER TABLE productos ADD COLUMN porcentaje_ganancia TEXT;
        ALTER TABLE productos ADD COLUMN controla_inventario INTEGER NOT NULL DEFAULT 1
            CHECK(controla_inventario IN (0,1));
        ALTER TABLE detalle_venta ADD COLUMN controla_inventario_snapshot INTEGER NOT NULL DEFAULT 1
            CHECK(controla_inventario_snapshot IN (0,1));
        CREATE INDEX IF NOT EXISTS ix_productos_controla_inventario ON productos(controla_inventario);
        """,
    ),
    (
        7,
        """
        ALTER TABLE productos ADD COLUMN unidad_granel TEXT
            CHECK(unidad_granel IS NULL OR unidad_granel IN ('PESO','VOLUMEN'));
        UPDATE productos SET unidad_granel='PESO' WHERE tipo_venta='GRANEL';

        ALTER TABLE detalle_venta ADD COLUMN unidad_granel_snapshot TEXT
            CHECK(unidad_granel_snapshot IS NULL OR unidad_granel_snapshot IN ('PESO','VOLUMEN'));
        UPDATE detalle_venta SET unidad_granel_snapshot='PESO'
            WHERE tipo_venta_snapshot='GRANEL';
        """,
    ),
    (
        8,
        """
        ALTER TABLE productos ADD COLUMN precio_variable INTEGER NOT NULL DEFAULT 0
            CHECK(precio_variable IN (0,1));
        """,
    ),
    (9, MIGRATION_9),
]
