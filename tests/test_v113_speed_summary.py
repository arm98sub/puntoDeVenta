import os
from datetime import date,timedelta
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import QEvent,Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit

from ferreteria_core import Database
from ferreteria_core.services import Cart,DailySummaryService,ProductService,SalesService
from ferreteria_gui.dialogs import SaleCompletedDialog
from ferreteria_gui.dialogs import BulkSaleDialog
from ferreteria_gui.pages import PosPage
from ferreteria_gui.scanner import ScannerBuffer


@pytest.fixture(scope="module")
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def db(tmp_path):database=Database(tmp_path/"v113.db");database.migrate();return database

def product(db,index=1,price="10",stock=200):return ProductService(db).crear_producto_externo(f"750000113{index:04d}",f"Producto {index}",Decimal(price),stock,clave=f"P-{index}")


def test_buffer_scanner_rapido_y_escritura_humana():
    buffer=ScannerBuffer();now=10.0
    for char in "7501234567890":buffer.character(char,now);now+=0.01
    assert buffer.finish(now)=="7501234567890"
    for char in "martillo":buffer.character(char,now);now+=0.2
    assert buffer.finish(now) is None


def test_f7_f8_repetibles_preservan_seleccion(app,db):
    value=product(db);page=PosPage(db);page.show();app.processEvents();page.cart.agregar_producto(value.id);page.refresh(preserve_id=value.id);page.table.setFocus()
    for _ in range(5):page._change(1)
    assert page.cart.item(value.id).cantidad==6 and page._selected_id()==value.id and page.table.hasFocus()
    for _ in range(5):page._change(-1)
    assert page.cart.item(value.id).cantidad==1 and page._selected_id()==value.id;page.close()


def test_f10_unidad_establece_50_y_doble_clic_25(app,db,monkeypatch):
    value=product(db);page=PosPage(db);page.cart.agregar_producto(value.id);page.refresh(preserve_id=value.id)
    answers=iter([(50,True),(25,True)]);monkeypatch.setattr("ferreteria_gui.pages.QInputDialog.getInt",lambda *args,**kwargs:next(answers))
    page.set_selected_quantity();assert page.cart.item(value.id).cantidad==50 and page._selected_id()==value.id
    page._cell_double_clicked(0,2);assert page.cart.item(value.id).cantidad==25 and page._selected_id()==value.id


@pytest.mark.parametrize(("unit","initial","replacement","shown"),[("PESO",250_000,500_000,"0.25"),("VOLUMEN",500_000,1_000_000,"0.5")])
def test_f10_granel_precarga_dialogo_correcto(app,db,monkeypatch,unit,initial,replacement,shown):
    value=ProductService(db).crear_producto_externo(f"7500001138{1 if unit=='PESO' else 2:03d}","Granel",Decimal("60"),0,tipo_venta="GRANEL",unidad_granel=unit,controla_inventario=False);page=PosPage(db);page.cart.agregar_granel(value.id,initial);page.refresh(preserve_id=value.id);seen=[]
    def accept(dialog):seen.append((dialog.bulk_unit,dialog.quantity.text()));dialog.cantidad_mg=replacement;return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BulkSaleDialog,"exec",accept);page.set_selected_quantity()
    assert seen==[(unit,shown)] and page.cart.item(value.id).cantidad_mg==replacement and page._selected_id()==value.id


@pytest.mark.parametrize("value",[0,-1,Decimal("1.5"),"x"])
def test_cantidad_unidad_invalida(value,db):
    item=product(db);cart=Cart(db);cart.agregar_producto(item.id)
    with pytest.raises(ValueError):cart.establecer_cantidad(item.id,value)
    assert cart.item(item.id).cantidad==1


def test_eliminar_selecciona_siguiente_o_anterior(app,db):
    values=[product(db,index) for index in range(1,4)];page=PosPage(db)
    for value in values:page.cart.agregar_producto(value.id)
    page.refresh(preserve_id=values[1].id);page.remove_selected();assert page._selected_id()==values[2].id
    page.remove_selected();assert page._selected_id()==values[0].id


def test_scroll_no_vuelve_arriba(app,db):
    page=PosPage(db);page.resize(700,300);page.show()
    values=[product(db,index) for index in range(1,31)]
    for value in values:page.cart.agregar_producto(value.id)
    page.refresh(preserve_id=values[-2].id);page.table.scrollToBottom();app.processEvents();before=page.table.verticalScrollBar().value();page._change(1);app.processEvents()
    assert before>0 and page.table.verticalScrollBar().value()==before and page._selected_id()==values[-2].id;page.close()


def test_scanner_global_con_tabla_agrega_una_sola_vez(app,db,monkeypatch):
    value=product(db);page=PosPage(db);page.show();app.processEvents();page.table.setFocus();now=10.0
    for char in value.codigo_barras:page.scanner_buffer.character(char,now);now+=0.01
    clock=__import__("time").monotonic();page.scanner_buffer._times=[clock-0.12+index*0.01 for index in range(len(value.codigo_barras))];calls=[];original=page._process_term;monkeypatch.setattr(page,"_process_term",calls.append)
    assert page.eventFilter(page.table,QKeyEvent(QEvent.KeyPress,Qt.Key_Return,Qt.NoModifier)) and calls==[value.codigo_barras]
    monkeypatch.setattr(page,"_process_term",original);page._process_term(value.codigo_barras);assert page.cart.item(value.id).cantidad==1
    page.barcode.setFocus();page.barcode.setText(value.codigo_barras);page._scan();app.processEvents()
    assert page.cart.item(value.id).cantidad==2;page.close()


def test_scanner_global_no_intercepta_lineedit(app,db):
    value=product(db);page=PosPage(db);page.show();app.processEvents();editor=QLineEdit(page);editor.show();editor.setFocus();QTest.keyClicks(editor,value.codigo_barras,Qt.NoModifier,1);QTest.keyClick(editor,Qt.Key_Return);app.processEvents()
    assert not page.cart.items and editor.text()==value.codigo_barras;page.close()


def _set_date(db,sale,day):
    with db.transaction() as connection:connection.execute("UPDATE ventas SET fecha_hora=? WHERE id=?",(f"{day.isoformat()}T18:00:00.000Z",sale.id))


def test_resumen_fecha_metodos_cancelaciones_descuentos(db):
    service=SalesService(db);day=date.today();p100=product(db,1,"100");p200=product(db,2,"200");p300=product(db,3,"300");p150=product(db,4,"150")
    sales=[service.crear_venta([{"producto_id":p100.id,"cantidad":1}],"EFECTIVO",Decimal("100")),service.crear_venta([{"producto_id":p200.id,"cantidad":1}],"EFECTIVO",Decimal("200")),service.crear_venta([{"producto_id":p300.id,"cantidad":1}],"TARJETA"),service.crear_venta([{"producto_id":p150.id,"cantidad":1}],"TRANSFERENCIA")]
    for sale in sales:_set_date(db,sale,day)
    service.cancelar_venta(sales[-1].id,"Prueba");summary=DailySummaryService(db).obtener(day)
    assert summary.ventas_completadas==3 and summary.venta_neta_centavos==60000
    assert summary.metodos_pago=={"EFECTIVO":30000,"TARJETA":30000}
    assert summary.ventas_canceladas==1 and summary.importe_cancelado_centavos==15000 and all(p.producto_id!=p150.id for p in summary.productos)


def test_resumen_filtra_fecha(db):
    service=SalesService(db);value=product(db);yesterday=date.today()-timedelta(days=1);today=date.today()
    old=service.crear_venta([{"producto_id":value.id,"cantidad":1}],"TARJETA");new=service.crear_venta([{"producto_id":value.id,"cantidad":2}],"TARJETA");_set_date(db,old,yesterday);_set_date(db,new,today)
    assert DailySummaryService(db).obtener(yesterday).venta_neta_centavos==1000
    assert DailySummaryService(db).obtener(today).venta_neta_centavos==2000


def test_resumen_productos_unidad_peso_volumen(db):
    products=ProductService(db);unit=product(db,1,"10");weight=products.crear_producto_externo("7500001139001","Clavo",Decimal("80"),0,tipo_venta="GRANEL",unidad_granel="PESO",controla_inventario=False);volume=products.crear_producto_externo("7500001139002","Thinner",Decimal("60"),0,tipo_venta="GRANEL",unidad_granel="VOLUMEN",controla_inventario=False)
    sale=SalesService(db).crear_venta([{"producto_id":unit.id,"cantidad":3},{"producto_id":weight.id,"cantidad_mg":2_450_000},{"producto_id":volume.id,"cantidad_mg":4_500_000}],"TARJETA");_set_date(db,sale,date.today());rows={p.producto_id:p for p in DailySummaryService(db).obtener().productos}
    assert rows[unit.id].cantidad==3 and rows[unit.id].tipo_venta=="UNIDAD"
    assert rows[weight.id].cantidad==2_450_000 and rows[weight.id].unidad_granel=="PESO"
    assert rows[volume.id].cantidad==4_500_000 and rows[volume.id].unidad_granel=="VOLUMEN"


def test_dialogo_postventa_prioriza_nueva_e_imprimir(app,db,tmp_path):
    value=product(db);sale=SalesService(db).crear_venta([{"producto_id":value.id,"cantidad":1}],"TARJETA");ticket=tmp_path/"ticket.pdf";ticket.write_bytes(b"pdf");dialog=SaleCompletedDialog(sale,ticket)
    assert dialog.fresh.isDefault() and dialog.fresh.objectName()=="primary" and dialog.print_button.text()=="IMPRIMIR TICKET"
