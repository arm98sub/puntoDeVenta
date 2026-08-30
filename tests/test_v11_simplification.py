import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel,Qt
from PySide6.QtWidgets import QApplication,QDialog,QHeaderView,QMessageBox

from ferreteria_core import Database
from ferreteria_core.pricing import normalizar_porcentaje,porcentaje_real,precio_venta_sugerido
from ferreteria_core.services import Cart,InventoryService,ProductService,SalesService
from ferreteria_gui.dialogs import BulkSaleDialog,ProductModifyDialog
from ferreteria_gui.pages import InventoryPage,ProductsPage


@pytest.fixture(scope="module")
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def db(tmp_path):value=Database(tmp_path/"simple.db");value.migrate();return value

def make(db,index=1,*,kind="UNIDAD",control=True,stock=10,cost=None,margin=None,sale="20"):
    return ProductService(db).crear_producto_externo(f"7500000300{index:03d}",f"Producto {index}",Decimal(sale),stock if kind=="UNIDAD" else 0,tipo_venta=kind,existencia_granel_mg=stock if kind=="GRANEL" else 0,precio_proveedor=cost,porcentaje_ganancia=margin,controla_inventario=control)


def test_migracion7_defaults_compatibles(db):
    product=make(db)
    assert product.controla_inventario and product.precio_proveedor is None and product.porcentaje_ganancia is None
    with db.connect() as connection:assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]==10


def test_costo_80_margen_25_precio_100():assert precio_venta_sugerido(8000,"25")==10000

def test_decimal_y_redondeo_precio():
    assert precio_venta_sugerido(101,"12.5")==114
    assert normalizar_porcentaje("25.123456")=="25.1235"


def test_modificar_costo_recalcula_venta(db):
    product=make(db,cost="80",margin="25",sale="100");updated=ProductService(db).actualizar_precio_proveedor(product.id,Decimal("120"))
    assert updated.precio_proveedor==12000 and updated.precio_venta==15000


def test_modificar_ganancia_recalcula_venta(db):
    product=make(db,cost="80",margin="25",sale="100");updated=ProductService(db).actualizar_porcentaje_ganancia(product.id,"50")
    assert updated.porcentaje_ganancia=="50" and updated.precio_venta==12000


def test_modificar_venta_recalcula_ganancia(db):
    product=make(db,cost="80",margin="25",sale="100");updated=ProductService(db).actualizar_precio_venta(product.id,Decimal("120"))
    assert updated.precio_venta==12000 and updated.porcentaje_ganancia=="50"


def test_costo_y_ganancia_null_precio_cero(db):
    product=make(db,sale="0");assert product.precio_venta==0
    updated=ProductService(db).actualizar_precio_proveedor(product.id,None);assert updated.precio_proveedor is None
    updated=ProductService(db).actualizar_porcentaje_ganancia(product.id,None);assert updated.porcentaje_ganancia is None


def test_precio_catalogo_independiente(db):
    product=make(db,cost="80",margin="25",sale="100");updated=ProductService(db).actualizar_precio_catalogo(product.id,Decimal("130"))
    assert (updated.precio_catalogo_publico,updated.precio_proveedor,updated.precio_venta)==(13000,8000,10000)


@pytest.mark.parametrize(("kind","control"),[("UNIDAD",True),("UNIDAD",False),("GRANEL",True),("GRANEL",False)])
def test_combinaciones_tipo_control_inventario(db,kind,control):
    product=make(db,index=10+len(ProductService(db).buscar(limit=100)),kind=kind,control=control,stock=1_000_000 if kind=="GRANEL" else 2)
    assert product.tipo_venta==kind and product.controla_inventario is control


@pytest.mark.parametrize("kind",["UNIDAD","GRANEL"])
def test_sin_inventario_no_bloquea_descuenta_mueve_ni_devuelve(db,kind):
    product=make(db,index=40 if kind=="UNIDAD" else 41,kind=kind,control=False,stock=0,sale="80");items=[{"producto_id":product.id,"cantidad":50}] if kind=="UNIDAD" else [{"producto_id":product.id,"cantidad_mg":5_000_000}]
    sale=SalesService(db).crear_venta(items,"TARJETA");after=ProductService(db).get(product.id)
    assert (after.existencia,after.existencia_granel_mg)==(0,0) and not sale.detalles[0].controla_inventario_snapshot
    with db.connect() as connection:assert connection.execute("SELECT count(*) FROM movimientos_inventario WHERE producto_id=?",(product.id,)).fetchone()[0]==0
    SalesService(db).cancelar_venta(sale.id,"Prueba");final=ProductService(db).get(product.id);assert (final.existencia,final.existencia_granel_mg)==(0,0)


@pytest.mark.parametrize("kind",["UNIDAD","GRANEL"])
def test_con_inventario_valida_y_genera_movimiento(db,kind):
    stock=2 if kind=="UNIDAD" else 100_000;product=make(db,index=50 if kind=="UNIDAD" else 51,kind=kind,control=True,stock=stock,sale="80");items=[{"producto_id":product.id,"cantidad":1}] if kind=="UNIDAD" else [{"producto_id":product.id,"cantidad_mg":50_000}]
    SalesService(db).crear_venta(items,"TARJETA")
    with db.connect() as connection:assert connection.execute("SELECT count(*) FROM movimientos_inventario WHERE producto_id=? AND tipo='VENTA'",(product.id,)).fetchone()[0]==1


def test_dialogo_granel_campos_vinculados_sin_bucles(app,db):
    product=make(db,index=60,kind="GRANEL",control=False,stock=0,sale="106.80");dialog=BulkSaleDialog(product)
    dialog.quantity.setText("0.051");dialog._from_quantity();assert dialog.amount.text()=="5.45"
    dialog.amount.setText("5.50");dialog._from_amount();assert dialog.quantity.text()=="0.0515"
    dialog._source="importe";dialog._accept();assert dialog.result()==QDialog.DialogCode.Accepted and dialog.cantidad_mg==51_498


def test_seleccion_multiple_cambio_tipo_persiste_solo_seleccionados(app,db,monkeypatch):
    products=[make(db,index=70+i,sale=str(10+i)) for i in range(3)];page=ProductsPage(db);page.show();app.processEvents();page.reload();selection=page.table.selectionModel()
    rows={page.table.item(row,0).data(Qt.UserRole):row for row in range(page.table.rowCount())}
    for product in products[:2]:selection.select(page.table.model().index(rows[product.id],0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
    monkeypatch.setattr("ferreteria_gui.pages.QInputDialog.getItem",lambda *args,**kwargs:("GRANEL",True));monkeypatch.setattr("ferreteria_gui.pages.QMessageBox.question",lambda *args,**kwargs:QMessageBox.Yes)
    old_prices=[p.precio_venta for p in products];page._change_type();app.processEvents();updated=[ProductService(db).get(p.id) for p in products]
    assert [p.tipo_venta for p in updated]==["GRANEL","GRANEL","UNIDAD"] and [p.precio_venta for p in updated]==old_prices


def test_tablas_redimensionables_tooltip_y_columnas(app,db):
    make(db,index=80);page=ProductsPage(db);page.show();app.processEvents();page.reload();header=page.table.horizontalHeader()
    assert header.sectionResizeMode(3)==QHeaderView.Interactive and page.table.columnWidth(3)>=300
    assert page.table.item(0,3).toolTip()==page.table.item(0,3).text()
    assert [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]==["Código","Barcode","Clave","Descripción","Tipo de venta","Precio proveedor","Ganancia %","Precio venta","Control inventario","Activo"]


def test_existencias_simplificada_precio_y_filtro(app,db):
    make(db,index=81);make(db,index=82,control=False);page=InventoryPage(db);page.show();app.processEvents();page.reload()
    assert page.filter.currentData()=="CON_CONTROL" and [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]==["Producto","Clave","Barcode","Precio venta","Existencia","Control inventario"]
    assert page.entry.text()=="AGREGAR EXISTENCIA" and page.adjust.text()=="AJUSTAR EXISTENCIA" and page.movements.text()=="VER MOVIMIENTOS"


def test_formulario_modificar_sin_campos_tecnicos(app,db):
    product=make(db,index=90,cost="80",margin="25",sale="100");dialog=ProductModifyDialog(product,ProductService(db));dialog.cost.setText("120");dialog.margin.setText("25");from ferreteria_gui.dialogs import _sync_price_fields;_sync_price_fields(dialog.cost,dialog.margin,dialog.sale,"cost")
    assert dialog.sale.text()=="150.00" and dialog.control.isChecked()
