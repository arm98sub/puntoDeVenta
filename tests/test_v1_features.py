import csv,os
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from ferreteria_core import Database
from ferreteria_core.services import (BusinessConfigService,Cart,GenericProductImporter,InsufficientStockError,
    InventoryService,ProductQueryService,ProductService,SalesService,TicketService,respaldar_base)


@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"v1.db");value.migrate();return value


def make(db,index,description="Producto",price="10",stock=1,**kwargs):
    return ProductService(db).crear_producto_externo(f"7501000{index:06d}",description,Decimal(price),stock,**kwargs)


def test_editar_descripcion_y_snapshot_historico(db):
    p=make(db,1,description="Anterior",stock=2);sales=SalesService(db);old=sales.crear_venta([{"producto_id":p.id,"cantidad":1}],"TARJETA")
    ProductService(db).actualizar_descripcion_producto(p.id,"Nueva descripción");new=sales.crear_venta([{"producto_id":p.id,"cantidad":1}],"TARJETA")
    assert sales.obtener_por_id(old.id).detalles[0].descripcion_snapshot=="Anterior"
    assert new.detalles[0].descripcion_snapshot=="Nueva descripción"


@pytest.mark.parametrize(("sort","direction","expected"),[("codigo_truper","ASC",["100","200"]),("codigo_truper","DESC",["200","100"]),("descripcion","ASC",["A","B"]),("descripcion","DESC",["B","A"]),("precio_venta","ASC",[1000,2000]),("precio_venta","DESC",[2000,1000]),("existencia","ASC",[1,2]),("existencia","DESC",[2,1])])
def test_orden_sql(db,sort,direction,expected):
    a=make(db,1,description="B",price="20",stock=2);b=make(db,2,description="A",price="10",stock=1)
    with db.connect() as c:c.execute("UPDATE productos SET codigo_truper='200' WHERE id=?",(a.id,));c.execute("UPDATE productos SET codigo_truper='100' WHERE id=?",(b.id,))
    values=ProductQueryService(db).buscar_inteligente(sort_column=sort,sort_direction=direction).products
    actual={"codigo_truper":[p.codigo_truper for p in values],"descripcion":[p.descripcion for p in values],"precio_venta":[p.precio_venta for p in values],"existencia":[p.existencia for p in values]}[sort]
    assert actual==expected


def test_orden_antes_de_paginacion_y_estable(db):
    for i,name in enumerate(["Z","A","M"]):make(db,i,description=name)
    q=ProductQueryService(db);assert q.buscar_inteligente(page=1,page_size=1,sort_column="descripcion").products[0].descripcion=="A"
    ids=[p.id for p in q.buscar_inteligente(page_size=10,sort_column="descripcion").products];assert len(ids)==len(set(ids))


@pytest.mark.parametrize(("filter_name","expected"),[("CON_EXISTENCIA",1),("SIN_EXISTENCIA",2),("CON_PRECIO",2),("SIN_PRECIO",1),("CON_DESCRIPCION",2),("SIN_DESCRIPCION",1),("TRUPER",1),("EXTERNOS",2),("REVISION",1)])
def test_filtros(db,filter_name,expected):
    a=make(db,1,description="Martillo",stock=1);b=make(db,2,description="Pinza",stock=0);c=make(db,3,description="Temporal",stock=0)
    with db.connect() as conn:
        conn.execute("UPDATE productos SET es_truper=1,requiere_revision=1,codigo_truper='100',descripcion=NULL WHERE id=?",(c.id,));conn.execute("UPDATE productos SET precio_venta=NULL WHERE id=?",(b.id,))
    assert ProductQueryService(db).contar_productos(product_filter=filter_name)==expected


def test_filtro_combinado_busqueda(db):
    make(db,1,description="Martillo con stock",stock=2);make(db,2,description="Martillo agotado",stock=0);make(db,3,description="Pinza",stock=2)
    result=ProductQueryService(db).buscar_inteligente("martillo",product_filter="CON_EXISTENCIA")
    assert result.total==1 and result.products[0].descripcion=="Martillo con stock"


def test_configuracion_persistencia_y_logo_copiado(db,tmp_path):
    source=tmp_path/"externo.png";Image.new("RGB",(300,100),"navy").save(source);branding=tmp_path/"branding";service=BusinessConfigService(db,branding)
    saved=service.guardar(nombre_negocio="Tienda Uno",direccion="Calle 1",telefono="555",rfc="ABC010101AA1",mensaje_ticket="Vuelva pronto",logo_origen=source)
    source.unlink();loaded=service.obtener()
    assert loaded==saved and Path(saved.logo_path).exists() and Path(saved.logo_path).parent==branding.resolve()


def test_backup_incluye_configuracion(db,tmp_path):
    BusinessConfigService(db,tmp_path/"branding").guardar(nombre_negocio="Respaldado")
    backup=respaldar_base(db,tmp_path/"backups")
    import sqlite3
    with sqlite3.connect(backup) as connection:assert connection.execute("SELECT nombre_negocio FROM configuracion_negocio WHERE id=1").fetchone()[0]=="Respaldado"


def _csv(path,rows):
    fields=["codigo_barras","descripcion","precio","existencia","clave","marca","categoria","stock_minimo"]
    with path.open("w",encoding="utf-8",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def test_importacion_csv_resumen_decimal_duplicado_error(db,tmp_path):
    make(db,9);path=tmp_path/"productos.csv";_csv(path,[{"codigo_barras":"7500000000001","descripcion":"Nuevo","precio":"25.50","existencia":"3"},{"codigo_barras":"7501000000009","descripcion":"Duplicado","precio":"10","existencia":"1"},{"codigo_barras":"bad space","descripcion":"Inválido","precio":"x","existencia":"-1"}])
    importer=GenericProductImporter(db);summary=importer.importar(path)
    assert (summary.encontrados,summary.importados,summary.duplicados,summary.errores)==(3,1,1,1)
    product=ProductService(db).buscar_exacto("codigo_barras","7500000000001");assert not product.es_truper and product.precio_venta==2550 and product.existencia==3


def test_importacion_xlsx(db,tmp_path):
    from openpyxl import Workbook
    path=tmp_path/"productos.xlsx";book=Workbook();sheet=book.active;sheet.append(["codigo_barras","descripcion","precio","existencia"]);sheet.append(["7500000000001","Desde Excel",8.5,2]);book.save(path)
    summary=GenericProductImporter(db).importar(path);assert summary.importados==1 and ProductService(db).buscar_exacto("codigo_barras","7500000000001").precio_venta==850


def test_stock_bloqueo_segundo_escaneo_y_consistencia(db):
    p=make(db,1,stock=1);cart=Cart(db);cart.agregar_por_barcode(p.codigo_barras)
    with pytest.raises(InsufficientStockError) as error:cart.agregar_por_barcode(p.codigo_barras)
    assert error.value.requested==2 and cart.cantidad_articulos==1


def test_stock_cero_bloqueado(db):
    p=make(db,1,stock=0)
    with pytest.raises(InsufficientStockError):Cart(db).agregar_producto(p.id)


def test_ajuste_y_entrada_permiten_continuar_carrito(db):
    p=make(db,1,stock=1);cart=Cart(db);cart.agregar_producto(p.id)
    InventoryService(db).ajustar_existencia(p.id,5,"Conteo");cart.establecer_cantidad(p.id,2);assert cart.cantidad_articulos==2
    InventoryService(db).registrar_entrada(p.id,2,"Llegada");assert ProductService(db).get(p.id).existencia==7


def test_validacion_final_venta_permanece(db):
    p=make(db,1,stock=2);cart=Cart(db);cart.agregar_producto(p.id,2);InventoryService(db).ajustar_existencia(p.id,1,"Otro proceso")
    with pytest.raises(ValueError,match="Stock insuficiente"):SalesService(db).crear_venta(cart.como_items_venta(),"TARJETA")


def test_ticket_usa_configuracion_actual(db,tmp_path):
    BusinessConfigService(db,tmp_path/"branding").guardar(nombre_negocio="Mi Negocio",direccion="Dirección",telefono="123",rfc="RFC123",mensaje_ticket="Gracias")
    p=make(db,1);sale=SalesService(db).crear_venta([{"producto_id":p.id,"cantidad":1}],"TARJETA");path=TicketService(db,tmp_path/"tickets").generar_para_venta(sale)
    from pypdf import PdfReader
    text=PdfReader(path).pages[0].extract_text();assert all(value in text for value in ("Mi Negocio","Dirección","123","RFC123","Gracias"))
