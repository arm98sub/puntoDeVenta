import sqlite3
from decimal import Decimal
import pytest
from PySide6.QtWidgets import QApplication,QDialog
from ferreteria_core import Database
from ferreteria_core.database.migrations import MIGRATIONS
from ferreteria_core.services import Cart,DailySummaryService,ProductService,SalesService,TicketService,VariablePriceRequired
from pypdf import PdfReader
from updater_core import migrate_database,validate_database
from ferreteria_gui.dialogs import ProductModifyDialog,QuickProductDialog,VariablePriceDialog

@pytest.fixture(scope="module")
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"v114.db");value.migrate();return value

def variable(db,**kwargs):
    return ProductService(db).crear_producto_externo("","Juguetes general",kwargs.pop("price",None),kwargs.pop("stock",0),clave="JUGUETE",permitir_sin_barcode=True,precio_variable=True,controla_inventario=False,**kwargs)

def test_migracion_8_default_false_preserva_datos(tmp_path):
    path=tmp_path/"schema7.db";connection=sqlite3.connect(path);connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for version,sql in MIGRATIONS[:7]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    connection.execute("INSERT INTO productos(descripcion,precio_venta,es_truper,datos_completos,requiere_revision) VALUES('Existente',5100,0,1,0)");connection.commit();connection.close();migrate_database(path,7,8)
    with sqlite3.connect(path) as connection:assert connection.execute("SELECT (SELECT max(version) FROM schema_migrations),precio_variable,precio_venta FROM productos").fetchone()==(8,0,5100)
    assert validate_database(path).valid

def test_crear_variable_sin_barcode_precio_inventario(db):
    product=variable(db);assert product.precio_variable and product.codigo_barras is None and product.precio_venta is None and not product.controla_inventario

def test_variable_restringido_a_unidad(db):
    with pytest.raises(ValueError,match="sólo para productos por unidad"):variable(db,tipo_venta="GRANEL",unidad_granel="PESO")

def test_carrito_variable_exige_precio_y_valida_cero(db):
    product=variable(db);cart=Cart(db)
    with pytest.raises(VariablePriceRequired):cart.agregar_producto(product.id)
    with pytest.raises(ValueError,match="mayor que cero"):cart.agregar_producto(product.id,precio_unitario_centavos=0)

def test_precios_distintos_separados_e_iguales_agrupados(db):
    product=variable(db);cart=Cart(db);cart.agregar_producto(product.id,1,3500);cart.agregar_producto(product.id,1,8000);cart.agregar_producto(product.id,2,3500)
    assert [(i.precio_unitario_centavos,i.cantidad) for i in cart.items]==[(3500,3),(8000,1)] and cart.total_centavos==18500

def test_producto_normal_conserva_agrupacion(db):
    product=ProductService(db).crear_producto_externo("7500001140001","Normal",Decimal("10"),0,controla_inventario=False);cart=Cart(db);cart.agregar_producto(product.id);cart.agregar_producto(product.id,2)
    assert len(cart.items)==1 and cart.items[0].cantidad==3

def test_cambio_precio_afecta_solo_linea_y_no_catalogo(db):
    product=variable(db,price=Decimal("20"));cart=Cart(db);a=cart.agregar_producto(product.id,1,3500);cart.agregar_producto(product.id,1,8000);cart.cambiar_precio_linea(a.linea_id,4000)
    assert sorted(i.precio_unitario_centavos for i in cart.items)==[4000,8000] and ProductService(db).get(product.id).precio_venta==2000

def test_venta_variable_snapshots_y_sin_movimiento(db):
    product=variable(db);sale=SalesService(db).crear_venta([{"producto_id":product.id,"cantidad":2,"precio_unitario_centavos":3500},{"producto_id":product.id,"cantidad":1,"precio_unitario_centavos":8000}],"TARJETA")
    assert sale.total_centavos==15000 and [(d.cantidad,d.precio_unitario_centavos,d.subtotal_centavos) for d in sale.detalles]==[(2,3500,7000),(1,8000,8000)]
    with db.connect() as connection:assert connection.execute("SELECT count(*) FROM movimientos_inventario").fetchone()[0]==0

def test_venta_fija_rechaza_override(db):
    product=ProductService(db).crear_producto_externo("7500001140002","Normal",Decimal("10"),0,controla_inventario=False)
    with pytest.raises(ValueError,match="no admite precio variable"):SalesService(db).crear_venta([{"producto_id":product.id,"cantidad":1,"precio_unitario_centavos":999}],"TARJETA")

def test_variable_con_inventario_descuenta_y_cancela(db):
    service=ProductService(db);product=service.crear_producto_externo("","Variable stock",None,3,permitir_sin_barcode=True,precio_variable=True,controla_inventario=True);sales=SalesService(db)
    sale=sales.crear_venta([{"producto_id":product.id,"cantidad":2,"precio_unitario_centavos":2500}],"TARJETA");assert service.get(product.id).existencia==1
    sales.cancelar_venta(sale.id,"prueba");assert service.get(product.id).existencia==3

def test_dialogo_precio_decimal_cantidad_y_foco(app,db):
    dialog=VariablePriceDialog(variable(db));dialog.price.setText("35.25");dialog.quantity.setValue(3);dialog._accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and dialog.precio_unitario_centavos==3525 and dialog.cantidad==3

def test_formulario_nuevo_permite_variable_sin_barcode(app,db):
    dialog=QuickProductDialog(db);dialog.mode.setCurrentIndex(1);dialog.description.setText("Juguetes general");dialog.variable.setChecked(True);dialog.price.clear();dialog.control.setChecked(False);dialog._save()
    assert dialog.product.precio_variable and dialog.product.codigo_barras is None and dialog.product.precio_venta is None

def test_formulario_modificar_carga_y_persiste_variable(app,db):
    product=variable(db,price=Decimal("20"));dialog=ProductModifyDialog(product,ProductService(db));assert dialog.variable.isChecked();dialog.sale.setText("25");dialog._save()
    updated=ProductService(db).get(product.id);assert updated.precio_variable and updated.precio_venta==2500

def test_ticket_separa_precios_y_resumen_los_agrupa(db,tmp_path):
    product=variable(db);sale=SalesService(db).crear_venta([{"producto_id":product.id,"cantidad":1,"precio_unitario_centavos":3500},{"producto_id":product.id,"cantidad":1,"precio_unitario_centavos":8000}],"TARJETA")
    path=TicketService(db,tmp_path/"tickets").generar_para_venta(sale);content="\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    assert "$35.00" in content and "$80.00" in content
    summary=DailySummaryService(db).obtener();sold=next(item for item in summary.productos if item.producto_id==product.id)
    assert sold.cantidad==2 and sold.importe_centavos==11500
