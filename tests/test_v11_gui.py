import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QAbstractItemView,QDialog

from ferreteria_core import Database
from ferreteria_core.services import ProductService
from ferreteria_gui.dialogs import BulkSaleDialog
from ferreteria_gui.pages import InventoryPage,PosPage,ProductsPage


@pytest.fixture(scope="module")
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def db(tmp_path):value=Database(tmp_path/"gui11.db");value.migrate();return value

def products(db):
    service=ProductService(db)
    a=service.crear_producto_externo("7500000010001","Clavo uno",Decimal("80"),0,tipo_venta="GRANEL",existencia_granel_mg=1_000_000)
    b=service.crear_producto_externo("7500000010002","Clavo dos",Decimal("85"),5)
    c=service.crear_producto_externo("7500000010003","Otro",Decimal("10"),2)
    return a,b,c


def test_productos_seleccion_multiple_y_bloqueo_default(app,db):
    products(db);page=ProductsPage(db);page.show();app.processEvents();page.reload();app.processEvents()
    assert page.table.selectionMode()==QAbstractItemView.SelectionMode.ExtendedSelection
    selection=page.table.selectionModel();selection.select(page.table.model().index(0,0),QItemSelectionModel.Select|QItemSelectionModel.Rows);selection.select(page.table.model().index(1,0),QItemSelectionModel.Select|QItemSelectionModel.Rows);app.processEvents();assert len(page.selected_products())==2
    assert bool(page.table.item(0,3).flags()&Qt.ItemIsEditable)
    assert not bool(page.table.item(0,0).flags()&Qt.ItemIsEditable)
    page.close()


def test_ctrl_y_shift_seleccionan_productos(app,db):
    products(db);page=ProductsPage(db);page.show();app.processEvents();page.reload();app.processEvents()
    viewport=page.table.viewport()
    QTest.mouseClick(viewport,Qt.LeftButton,Qt.NoModifier,page.table.visualItemRect(page.table.item(0,0)).center())
    QTest.mouseClick(viewport,Qt.LeftButton,Qt.ControlModifier,page.table.visualItemRect(page.table.item(1,0)).center())
    assert len(page.selected_products())==2
    QTest.mouseClick(viewport,Qt.LeftButton,Qt.ShiftModifier,page.table.visualItemRect(page.table.item(2,0)).center())
    assert len(page.selected_products())==3
    page.close()


def test_edicion_directa_columnas_seguras(app,db):
    products(db);page=ProductsPage(db);page.show();app.processEvents();page.reload();app.processEvents()
    assert all(bool(page.table.item(0,col).flags()&Qt.ItemIsEditable) for col in (3,5,6,7))
    assert all(not bool(page.table.item(0,col).flags()&Qt.ItemIsEditable) for col in (0,1,2,4,8,9))
    page.close()


def test_dialogo_granel_peso_e_importe(app,db):
    product=products(db)[0];dialog=BulkSaleDialog(product);dialog.quantity.setText("0.0625");dialog._source="cantidad";dialog._accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and dialog.cantidad_mg==62_500
    dialog=BulkSaleDialog(product);dialog.amount.setText("2.00");dialog._source="importe";dialog._accept()
    assert dialog.cantidad_mg==25_000


def test_carrito_gui_mixto_presenta_kg_y_pzas(app,db):
    bulk,unit,_=products(db);page=PosPage(db);page.cart.agregar_granel(bulk.id,750_000);page.cart.agregar_producto(unit.id,2);page.refresh()
    values=[page.table.item(row,2).text() for row in range(page.table.rowCount())]
    assert "0.75 kg" in values and "2 pzas" in values


def test_inventario_presenta_unidad_y_granel(app,db):
    products(db);page=InventoryPage(db);page.show();app.processEvents();page.reload();app.processEvents()
    stocks={page.table.item(row,4).text() for row in range(page.table.rowCount())};controls={page.table.item(row,5).text() for row in range(page.table.rowCount())}
    assert "1 kg" in stocks and controls=={"Sí"}
