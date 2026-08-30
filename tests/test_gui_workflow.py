import os
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QDialog, QLabel

from ferreteria_core import Database
from edition import Edition,get_edition_config
from ferreteria_core.services import ProductQueryService,ProductService,SalesService
from ferreteria_gui.pages import HistoryPage, InventoryPage, PosPage, ProductsPage
from ferreteria_gui.purchases_page import PurchasesPage
from ferreteria_gui.dialogs import PaymentDialog,ProductModifyDialog,QuickProductDialog
from ferreteria_gui.dialogs import QuickStockDialog
from ferreteria_gui.app import KeyboardActivationFilter
from ferreteria_gui.main_window import MainWindow
from ferreteria_gui.settings_page import SettingsPage
from ferreteria_gui.widgets import STYLE
import ferreteria_gui.config as gui_config
import ferreteria_gui.dialogs as gui_dialogs
import ferreteria_gui.pages as gui_pages
import ferreteria_gui.settings_page as gui_settings


@pytest.fixture(scope="session")
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"gui.db");value.migrate();return value


def product(db,barcode="7501206683729"):
    return ProductService(db).crear_producto_externo(barcode,"Silicón",Decimal("51"),10,clave="SIL-85T")


def _visible_labels(widget):
    widget.show();QApplication.processEvents();return [label.text() for label in widget.findChildren(QLabel) if not label.isHidden()]


def test_general_oculta_truper_en_alta_y_modificacion(app,db,monkeypatch):
    monkeypatch.setattr(gui_dialogs,"TRUPER_ENABLED",False);monkeypatch.setattr(gui_pages,"TRUPER_ENABLED",False)
    quick=QuickProductDialog(db);quick_labels=_visible_labels(quick)
    assert not any("Truper" in text for text in quick_labels) and "Código interno:" in quick_labels and quick.key.isVisible()
    assert quick.form.labelForField(quick.bulk_unit).isHidden() and quick.bulk_unit.isHidden() and quick.variable.isEnabled()
    assert quick.form.labelForField(quick.price).text()=="Precio de venta: $"
    quick.kind.setCurrentText("GRANEL");app.processEvents();assert not quick.form.labelForField(quick.bulk_unit).isHidden() and not quick.bulk_unit.isHidden() and not quick.variable.isEnabled()
    assert "sólo para productos por unidad" in quick.variable.text() and quick.form.labelForField(quick.price).text()=="Precio por kg: $"
    quick.bulk_unit.setCurrentIndex(quick.bulk_unit.findData("VOLUMEN"));app.processEvents();assert quick.form.labelForField(quick.price).text()=="Precio por L: $"
    quick.kind.setCurrentText("UNIDAD");app.processEvents();assert quick.form.labelForField(quick.bulk_unit).isHidden() and quick.bulk_unit.isHidden() and quick.variable.isEnabled() and quick.variable.text()=="Precio variable en cada venta"
    quick.barcode.setText("7501206683730");quick.key.setText("INT-001");quick.description.setText("Producto general");quick.price.setText("25");quick._save()
    item=ProductService(db).buscar_exacto("codigo_barras","7501206683730");assert item.clave=="INT-001"
    page=ProductsPage(db);page.reload();assert page.table.item(0,0).text()=="INT-001"
    service=ProductService(db,get_edition_config(Edition.GENERAL));modify=ProductModifyDialog(item,service);modify_labels=_visible_labels(modify)
    assert not any("Truper" in text for text in modify_labels) and "Código interno:" in modify_labels and "Barcode:" in modify_labels
    assert modify.form.labelForField(modify.bulk_unit).isHidden() and modify.bulk_unit.isHidden() and modify.variable.isEnabled()
    assert modify.form.labelForField(modify.sale).text()=="Precio de venta: $"
    modify.kind.setCurrentText("GRANEL");app.processEvents();assert not modify.form.labelForField(modify.bulk_unit).isHidden() and not modify.bulk_unit.isHidden() and not modify.variable.isEnabled()
    assert modify.form.labelForField(modify.sale).text()=="Precio por kg: $"
    modify.bulk_unit.setCurrentIndex(modify.bulk_unit.findData("VOLUMEN"));app.processEvents();assert modify.form.labelForField(modify.sale).text()=="Precio por L: $"
    modify.kind.setCurrentText("UNIDAD");app.processEvents();assert modify.form.labelForField(modify.bulk_unit).isHidden() and modify.bulk_unit.isHidden() and modify.variable.isEnabled()


@pytest.mark.parametrize("kind,barcode,key,stock",[("UNIDAD","COCACOLA","123","5"),("GRANEL","AZUCARGRANEL","GR-123","2.500")])
def test_general_alta_desde_pos_selecciona_externo_por_dato_y_persiste(app,db,monkeypatch,kind,barcode,key,stock):
    monkeypatch.setattr(gui_dialogs,"TRUPER_ENABLED",False);monkeypatch.setattr(gui_pages,"TRUPER_ENABLED",False)
    monkeypatch.setattr(gui_pages.UnknownBarcodeDialog,"exec",lambda self:self.EXTERNAL)
    selected=[]
    class AutomaticQuickProductDialog(QuickProductDialog):
        def exec(self):
            selected.append(self.mode.currentData());self.key.setText(key);self.description.setText("Coca 1.l" if kind=="UNIDAD" else "Azúcar a granel");self.kind.setCurrentText(kind);self.price.setText("29" if kind=="UNIDAD" else "28");self.stock.setText(stock);self.minimum.setText("5" if kind=="UNIDAD" else "0.500")
            piece=self.purchase_presentation.findText("Pieza")
            if piece>=0:self.purchase_presentation.setCurrentIndex(piece);self.purchase_content.setText("1")
            self._save();return self.result()
    class AcceptedBulkDialog:
        def __init__(self,*_):self.cantidad_mg=500_000
        def exec(self):return QDialog.DialogCode.Accepted
    monkeypatch.setattr(gui_pages,"QuickProductDialog",AutomaticQuickProductDialog);monkeypatch.setattr(gui_pages,"BulkSaleDialog",AcceptedBulkDialog)
    page=PosPage(db);page._process_term(barcode)
    saved=ProductService(db,get_edition_config(Edition.GENERAL)).buscar_exacto("codigo_barras",barcode)
    assert selected==["EXTERNAL"] and saved is not None and saved.clave==key and saved.codigo_truper is None and saved.tipo_venta==kind
    assert ProductQueryService(db).buscar_inteligente(key).products[0].id==saved.id and page.cart.items[0].producto_id==saved.id
    products=ProductsPage(db);products.reload();assert any(products.table.item(row,0).text()==key for row in range(products.table.rowCount()))
    before=saved.existencia if kind=="UNIDAD" else saved.existencia_granel_mg
    sale_line={"producto_id":saved.id,"cantidad":1} if kind=="UNIDAD" else {"producto_id":saved.id,"cantidad_mg":500_000}
    SalesService(db).crear_venta([sale_line],"TARJETA")
    after=ProductService(db).get(saved.id);assert (after.existencia if kind=="UNIDAD" else after.existencia_granel_mg)<before


def test_general_no_muestra_branding_ferreteria(app,db,monkeypatch):
    monkeypatch.setattr(gui_config,"TRUPER_ENABLED",False);monkeypatch.setattr(gui_config,"APP_NAME","PuntoDeVenta General")
    window=MainWindow(db);assert window.business_name.text()=="PuntoDeVenta General" and "FERRETERÍA" not in window.business_name.text().upper()


def test_general_acerca_de_muestra_identidad_version_y_autor(app,db,monkeypatch):
    config=get_edition_config(Edition.GENERAL);monkeypatch.setattr(gui_settings,"EDITION",config);monkeypatch.setattr(gui_settings,"__version__",config.version)
    page=SettingsPage(db);assert page.about_title.text()=="ACERCA DE"
    assert page.about_details.text()=="PuntoDeVenta General\nVersión 0.9.0 — Piloto\nDesarrollado por: Alan Ramírez\n© 2026"


def test_controles_deshabilitados_conservan_contraste_legible():
    assert "QLineEdit:disabled" in STYLE and "color: #4b5563" in STYLE and "QCheckBox::indicator:disabled" in STYLE


def test_paginas_diferidas_refrescan_en_cada_visita_sin_consultar_al_arrancar(app,db,monkeypatch):
    calls={"products":0,"inventory":0,"purchases":0,"history":0}
    def track(name):
        def refresh(page,*_args,**_kwargs):
            calls[name]+=1;page._loaded=True
        return refresh
    monkeypatch.setattr(ProductsPage,"reload",track("products"))
    monkeypatch.setattr(InventoryPage,"reload",track("inventory"))
    monkeypatch.setattr(PurchasesPage,"refresh",track("purchases"))
    monkeypatch.setattr(HistoryPage,"refresh",track("history"))
    window=MainWindow(db)
    assert calls=={"products":0,"inventory":0,"purchases":0,"history":0}
    pages=[("products",window.products),("inventory",window.inventory),("history",window.history)]
    if window.purchases is not None:pages.insert(2,("purchases",window.purchases))
    for name,page in pages:
        index=window.stack.indexOf(page)
        window.nav.setCurrentRow(index);app.processEvents();assert calls[name]==1
        window.nav.setCurrentRow(0);app.processEvents()
        window.nav.setCurrentRow(index);app.processEvents();assert calls[name]==2
    window.close()


def test_ferreteria_conserva_controles_truper(app,db,monkeypatch):
    monkeypatch.setattr(gui_dialogs,"TRUPER_ENABLED",True)
    quick=QuickProductDialog(db);labels=_visible_labels(quick)
    assert "Código Truper:" in labels and quick.find.text()=="BUSCAR CÓDIGO TRUPER"
    assert quick.form.labelForField(quick.price).text()=="Precio de venta / sugerido: $"
    assert quick.form.labelForField(quick.bulk_unit).isHidden();quick.kind.setCurrentText("GRANEL");app.processEvents();assert not quick.form.labelForField(quick.bulk_unit).isHidden() and quick.variable.text()=="Precio variable en cada venta"
    item=product(db,"7501206683731");modify=ProductModifyDialog(item,ProductService(db));assert any("Precio catálogo Truper" in text for text in _visible_labels(modify))
    assert modify.form.labelForField(modify.sale).text()=="Precio venta / sugerido"


def test_payment_dialog_accepted(app):
    dialog=PaymentDialog(5100);dialog.received.setText("100");dialog._accept()
    assert dialog.result()==QDialog.DialogCode.Accepted and dialog.payment.cambio_centavos==4900


def test_payment_dialog_rejected(app):
    dialog=PaymentDialog(5100);dialog.reject()
    assert dialog.result()==QDialog.DialogCode.Rejected


class FakePayment:
    def __init__(self,*_):
        self.payment=SimpleNamespace(recibido_centavos=10000);self.method=SimpleNamespace(currentText=lambda:"EFECTIVO")
    def exec(self):return QDialog.DialogCode.Accepted


class RejectedPayment(FakePayment):
    def exec(self):return QDialog.DialogCode.Rejected


class FakeComplete:
    def __init__(self,*_):pass
    def exec(self):return QDialog.DialogCode.Accepted


class FakeTickets:
    def __init__(self,*_):pass
    def generar_para_venta(self,sale):return None


def test_checkout_accepted_registra_una_vez_y_limpia(app,db,monkeypatch):
    import ferreteria_gui.pages as pages
    p=product(db);page=PosPage(db);page.cart.agregar_producto(p.id);page.refresh()
    monkeypatch.setattr(pages,"PaymentDialog",FakePayment);monkeypatch.setattr(pages,"SaleCompletedDialog",FakeComplete);monkeypatch.setattr(pages,"TicketService",FakeTickets)
    page.checkout()
    with db.connect() as c:assert c.execute("SELECT count(*) FROM ventas").fetchone()[0]==1
    assert page.cart.cantidad_articulos==0 and page.barcode.text()==""


def test_checkout_rejected_no_registra(app,db,monkeypatch):
    import ferreteria_gui.pages as pages
    p=product(db);page=PosPage(db);page.cart.agregar_producto(p.id)
    monkeypatch.setattr(pages,"PaymentDialog",RejectedPayment)
    page.checkout()
    with db.connect() as c:assert c.execute("SELECT count(*) FROM ventas").fetchone()[0]==0
    assert page.cart.cantidad_articulos==1


@pytest.mark.parametrize("page_class",[ProductsPage,InventoryPage])
def test_tablas_seleccion_fila_unica_y_acciones(page_class,app,db):
    product(db);page=page_class(db);page.show();app.processEvents();page.reload();app.processEvents()
    assert page.table.selectionBehavior()==QAbstractItemView.SelectionBehavior.SelectRows
    expected=QAbstractItemView.SelectionMode.ExtendedSelection if page_class is ProductsPage else QAbstractItemView.SelectionMode.SingleSelection
    assert page.table.selectionMode()==expected
    assert all(not button.isEnabled() for button in page.selection_buttons)
    page.table.selectRow(0);app.processEvents();assert all(button.isEnabled() for button in page.selection_buttons)
    page.close()


def test_busqueda_enter_scanner_selecciona_exacto(app,db):
    p=product(db);page=ProductsPage(db);page.show();app.processEvents();page.query.setText(p.codigo_barras);QTest.keyClick(page.query,Qt.Key_Return);app.processEvents()
    assert page.table.rowCount()==1 and page.selected_product().id==p.id
    page.close()


def test_cambiar_resultados_limpia_seleccion(app,db):
    product(db);page=InventoryPage(db);page.show();app.processEvents();page.reload();page.table.selectRow(0);page.query.setText("NO EXISTE");page.start_search();app.processEvents()
    assert page.table.rowCount()==0 and page.selected_product() is None and all(not b.isEnabled() for b in page.selection_buttons)
    page.close()


def test_refresco_conserva_seleccion_y_refleja_precio(app,db):
    p=product(db);page=ProductsPage(db);page.show();app.processEvents();page.reload();page.table.selectRow(0)
    ProductService(db).actualizar_precio_venta(p.id,Decimal("55"));page.refresh_preserve(p.id);app.processEvents()
    assert page.selected_product().id==p.id and "$55.00" in [page.table.item(0,c).text() for c in range(page.table.columnCount())]
    page.close()


def test_inventario_refleja_actualizacion(app,db):
    p=product(db);page=InventoryPage(db);page.show();app.processEvents();page.reload();page.table.selectRow(0)
    from ferreteria_core.services import InventoryService
    InventoryService(db).registrar_entrada(p.id,3);page.refresh_preserve(p.id);app.processEvents()
    assert page.selected_product().existencia==13 and page.table.item(0,4).text()=="13 pzas"
    page.close()


def test_filtro_limpia_seleccion(app,db):
    product(db);page=ProductsPage(db);page.show();app.processEvents();page.reload();page.table.selectRow(0);page.filter.setCurrentIndex(page.filter.findData("SIN_EXISTENCIA"));app.processEvents()
    assert page.table.currentRow()==-1 and all(not button.isEnabled() for button in page.selection_buttons);page.close()


def test_orden_tab_y_foco_visual(app,db):
    page=PosPage(db);page.show();app.processEvents()
    assert page.barcode.nextInFocusChain() is page.table and "QPushButton:focus" in STYLE and "QLineEdit:focus" in STYLE
    page.close()


def test_boton_enter_una_sola_accion(app):
    from PySide6.QtWidgets import QPushButton
    button=QPushButton("Guardar");count=[];button.clicked.connect(lambda:count.append(1));filter_=KeyboardActivationFilter();app.installEventFilter(filter_);button.show();button.setFocus();QTest.keyClick(button,Qt.Key_Return);app.processEvents();app.removeEventFilter(filter_)
    assert count==[1]


@pytest.mark.parametrize("entry",[False,True])
def test_actualizacion_rapida_stock(app,db,entry):
    p=product(db);dialog=QuickStockDialog(db,p,12);dialog.physical.setValue(15)
    if entry:dialog.entry.setChecked(True)
    dialog._save();updated=ProductService(db).get(p.id)
    with db.connect() as c:movement=c.execute("SELECT tipo FROM movimientos_inventario WHERE producto_id=? ORDER BY id DESC",(p.id,)).fetchone()[0]
    assert updated.existencia==15 and movement==("ENTRADA" if entry else "AJUSTE")
