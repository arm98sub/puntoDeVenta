"""Benchmark reproducible de GENERAL; crea y elimina exclusivamente una DB temporal."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ["PUNTO_VENTA_EDITION"]="GENERAL"
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from ferreteria_core import Database
from ferreteria_core.repositories import ProductRepository,PurchaseRepository,SaleRepository
from ferreteria_core.services import Cart,ProductQueryService,ProductService,SalesService,seed_general_categories,seed_general_purchase_presentations
from ferreteria_gui.main_window import MainWindow


PRODUCTS=5_000
MOVEMENTS=20_000
SALES=5_000
PURCHASES=2_000


def timed(call):
    started=time.perf_counter();value=call();return round((time.perf_counter()-started)*1000,3),value


def populate(database):
    with database.transaction() as connection:
        category=connection.execute("SELECT id FROM categorias ORDER BY id LIMIT 1").fetchone()[0]
        supplier=connection.execute("INSERT INTO proveedores(nombre,nombre_normalizado) VALUES('Proveedor benchmark','proveedor benchmark')").lastrowid
        piece=connection.execute("SELECT id FROM presentaciones_compra WHERE nombre_normalizado='pieza'").fetchone()[0]
        products=[]
        for index in range(1,PRODUCTS+1):
            bulk=index%10==0
            products.append((f"75{index:011d}",f"INT-{index:05d}",f"Producto benchmark {index:05d}",1000+index%500,1000,category,"GRANEL" if bulk else "UNIDAD","PESO" if bulk else None,1_000_000 if bulk else 0))
        connection.executemany("""INSERT INTO productos(codigo_barras,clave,descripcion,precio_venta,existencia,categoria_id,tipo_venta,unidad_granel,existencia_granel_mg,es_truper,datos_completos,requiere_revision)
            VALUES(?,?,?,?,?,?,?,?,?,0,1,0)""",products)
        connection.executemany("""INSERT INTO movimientos_inventario(producto_id,tipo,cantidad,existencia_anterior,existencia_nueva,referencia,tipo_venta_snapshot)
            VALUES(?,'AJUSTE',0,1000,1000,?,'UNIDAD')""",((index%PRODUCTS+1,f"BENCH-{index}") for index in range(MOVEMENTS)))
        connection.executemany("""INSERT INTO ventas(id,folio,subtotal_centavos,total_centavos,metodo_pago,estado)
            VALUES(?,?,1000,1000,'EFECTIVO','COMPLETADA')""",((index,f"V-{index:06d}") for index in range(1,SALES+1)))
        connection.executemany("""INSERT INTO detalle_venta(venta_id,producto_id,descripcion_snapshot,cantidad,precio_unitario_centavos,subtotal_centavos)
            VALUES(?,?,?,1,1000,1000)""",((index,index%PRODUCTS+1,f"Producto benchmark {index%PRODUCTS+1:05d}") for index in range(1,SALES+1)))
        connection.executemany("""INSERT INTO compras(id,folio,proveedor_id,proveedor_nombre_snapshot,fecha,total_centavos)
            VALUES(?,?,?,?,?,24000)""",((index,f"C-{index:06d}",supplier,"Proveedor benchmark",date.today().isoformat()) for index in range(1,PURCHASES+1)))
        connection.executemany("""INSERT INTO compra_detalles(compra_id,producto_id,descripcion_snapshot,tipo_venta_snapshot,presentacion_id,presentacion_snapshot,cantidad_presentaciones,contenido_por_presentacion,cantidad_base,costo_presentacion_centavos,costo_unitario_centavos,subtotal_centavos,controla_inventario_snapshot)
            VALUES(?,?,?,'UNIDAD',?,'Pieza','1',1,1,800,800,800,1)""",((index,index%PRODUCTS+1,f"Producto benchmark {index%PRODUCTS+1:05d}",piece) for index in range(1,PURCHASES+1)))


def run():
    with tempfile.TemporaryDirectory(prefix="pdv_general_benchmark_") as directory:
        path=Path(directory)/"benchmark.sqlite3";database=Database(path)
        backend_ms,_=timed(database.migrate);seed_general_categories(database);seed_general_purchase_presentations(database)
        populate_ms,_=timed(lambda:populate(database));query=ProductQueryService(database);products=ProductService(database)
        exact_barcode_ms,_=timed(lambda:query.buscar_inteligente("7500000000001",page_size=50))
        exact_code_ms,_=timed(lambda:query.buscar_inteligente("INT-02500",page_size=50))
        description_ms,description=timed(lambda:query.buscar_inteligente("benchmark 025",page_size=50))
        cart=Cart(database);cart_ms,_=timed(lambda:cart.agregar_producto(1))
        sale_ms,_=timed(lambda:SalesService(database).crear_venta([{"producto_id":1,"cantidad":1}],"EFECTIVO",efectivo_recibido=Decimal("20")))
        products_page_ms,product_page=timed(lambda:query.buscar_inteligente(page=1,page_size=50))
        inventory_page_ms,inventory_page=timed(lambda:query.buscar_inteligente(page=1,page_size=50,product_filter="CON_CONTROL",sort_column="existencia"))
        with database.connect() as connection:
            purchases_page_ms,purchases=timed(lambda:PurchaseRepository.list(connection,limit=50,offset=0))
            history_page_ms,history=timed(lambda:SaleRepository.list(connection,limit=50,offset=0,include_details=False))
            stock_ms,stock=timed(lambda:ProductRepository.get(connection,1))
        tracemalloc.start();app=QApplication.instance() or QApplication([])
        window_ms,window=timed(lambda:MainWindow(database));_current,_peak=tracemalloc.get_traced_memory();tracemalloc.stop();window.close();window.deleteLater();app.processEvents()
        result={"database_bytes":path.stat().st_size,"rows":{"products":PRODUCTS,"movements":MOVEMENTS,"sales":SALES,"sale_details":SALES,"purchases":PURCHASES,"purchase_details":PURCHASES},"milliseconds":{"backend_initialization":backend_ms,"fixture_population":populate_ms,"app_window_construction":window_ms,"exact_barcode":exact_barcode_ms,"exact_code":exact_code_ms,"description":description_ms,"cart_add":cart_ms,"register_sale":sale_ms,"products_first_page":products_page_ms,"inventory_first_page":inventory_page_ms,"purchases_first_page":purchases_page_ms,"history_first_page":history_page_ms,"stock_lookup":stock_ms},"result_sizes":{"description":len(description.products),"products_page":len(product_page.products),"inventory_page":len(inventory_page.products),"purchases_page":len(purchases),"history_page":len(history),"stock":stock.existencia},"python_tracemalloc_peak_bytes_during_window":_peak}
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":run()
