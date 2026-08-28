import sqlite3
from decimal import Decimal

import pytest
from pypdf import PdfReader
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ferreteria_core import Database
from ferreteria_core.database.migrations import MIGRATIONS
from ferreteria_core.quantity import (auxiliar_granel,formato_granel,importe_a_cantidad,
                                      litros_a_ul,subtotal_granel_centavos)
from ferreteria_core.services import Cart,InventoryService,ProductService,SalesService,TicketService
from ferreteria_gui.dialogs import ProductModifyDialog,QuickProductDialog


@pytest.fixture(scope="module")
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    database=Database(tmp_path/"v112.db");database.migrate();return database


def volume(db,*,stock=0,control=False):
    return ProductService(db).crear_producto_externo("7500001120001","Thinner",Decimal("60"),0,
        tipo_venta="GRANEL",unidad_granel="VOLUMEN",existencia_granel_mg=stock,controla_inventario=control)


def weight(db,*,stock=0,control=False):
    return ProductService(db).crear_producto_externo("7500001120002","Clavos",Decimal("80"),0,
        tipo_venta="GRANEL",unidad_granel="PESO",existencia_granel_mg=stock,controla_inventario=control)


def schema6(path):
    connection=sqlite3.connect(path);connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for version,sql in MIGRATIONS[:6]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    connection.commit();return connection


def test_migracion_6_a_7_unidad_intacta_granel_peso_e_historico(tmp_path):
    path=tmp_path/"old.db";connection=schema6(path)
    unit=connection.execute("INSERT INTO productos(descripcion,tipo_venta,existencia) VALUES('Martillo','UNIDAD',2)").lastrowid
    bulk=connection.execute("INSERT INTO productos(descripcion,tipo_venta,existencia_granel_mg) VALUES('Clavo','GRANEL',500000)").lastrowid
    connection.execute("INSERT INTO ventas(id,folio,fecha_hora,subtotal_centavos,descuento_centavos,total_centavos,metodo_pago,estado) VALUES(1,'V-000001',CURRENT_TIMESTAMP,4000,0,4000,'TARJETA','COMPLETADA')")
    connection.execute("INSERT INTO detalle_venta(venta_id,producto_id,descripcion_snapshot,cantidad,precio_unitario_centavos,subtotal_centavos,tipo_venta_snapshot,cantidad_mg,unidad_snapshot,precio_por_kg_centavos) VALUES(1,?,'Clavo',1,4000,4000,'GRANEL',500000,'MG',8000)",(bulk,));connection.commit();connection.close()
    Database(path).migrate()
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT unidad_granel FROM productos WHERE id=?",(unit,)).fetchone()[0] is None
        assert c.execute("SELECT unidad_granel FROM productos WHERE id=?",(bulk,)).fetchone()[0]=="PESO"
        assert c.execute("SELECT unidad_granel_snapshot FROM detalle_venta").fetchone()[0]=="PESO"
        assert c.execute("SELECT count(*) FROM ventas").fetchone()[0]==1 and c.execute("PRAGMA integrity_check").fetchone()[0]=="ok"


@pytest.mark.parametrize(("liters","microliters","price"),[("1",1_000_000,6000),("0.5",500_000,3000),("0.25",250_000,1500),("0.1",100_000,600)])
def test_volumen_precision_y_precio(liters,microliters,price):
    assert litros_a_ul(liters)==microliters
    assert subtotal_granel_centavos(6000,microliters)==price


def test_volumen_importe_inverso_y_presentacion():
    assert importe_a_cantidad(2000,6000,"VOLUMEN")==333_333
    assert formato_granel(500_000,"VOLUMEN")=="0.5 L"
    assert auxiliar_granel(250_000,"VOLUMEN")=="250 ml"
    assert "kg" not in formato_granel(125_000,"VOLUMEN") and "g" not in auxiliar_granel(125_000,"VOLUMEN")


@pytest.mark.parametrize("quantity",[1_000_000,500_000,250_000,62_500])
def test_peso_precio_y_presentacion(quantity):
    assert subtotal_granel_centavos(8000,quantity)=={1_000_000:8000,500_000:4000,250_000:2000,62_500:500}[quantity]
    assert formato_granel(quantity,"PESO").endswith(" kg")


def test_carrito_mixto_snapshots_ticket_y_cancelacion(db,tmp_path):
    hammer=ProductService(db).crear_producto_externo("7500001120003","Martillo",Decimal("185"),2)
    nails=weight(db,stock=1_000_000,control=True);thinner=volume(db,stock=2_000_000,control=True)
    cart=Cart(db);cart.agregar_producto(hammer.id);cart.agregar_granel(nails.id,51_000);cart.agregar_granel(thinner.id,500_000)
    assert cart.total_centavos==18500+408+3000
    sale=SalesService(db).crear_venta(cart.como_items_venta(),"TARJETA")
    units={detail.producto_id:detail.unidad_granel_snapshot for detail in sale.detalles}
    assert units[nails.id]=="PESO" and units[thinner.id]=="VOLUMEN" and units[hammer.id] is None
    assert ProductService(db).get(thinner.id).existencia_granel_mg==1_500_000
    path=TicketService(db,tmp_path/"tickets").generar_para_venta(sale);text="\n".join(p.extract_text() for p in PdfReader(path).pages)
    assert "0.051 kg x $80.00/kg" in text and "0.5 L x $60.00/L" in text
    SalesService(db).cancelar_venta(sale.id,"Prueba");assert ProductService(db).get(thinner.id).existencia_granel_mg==2_000_000


def test_granel_sin_inventario_no_mueve_stock(db):
    product=volume(db);sale=SalesService(db).crear_venta([{"producto_id":product.id,"cantidad_mg":250_000}],"TARJETA")
    SalesService(db).cancelar_venta(sale.id,"Prueba")
    with db.connect() as connection:assert connection.execute("SELECT count(*) FROM movimientos_inventario WHERE producto_id=?",(product.id,)).fetchone()[0]==0


def test_cambio_peso_volumen_requiere_stock_cero(db):
    product=weight(db,stock=1000,control=True);service=ProductService(db)
    with pytest.raises(ValueError,match="existencia a cero"):service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="VOLUMEN",precio_venta=Decimal("80"))
    InventoryService(db).ajustar_existencia_granel(product.id,0,"Cambio de unidad")
    changed=service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="VOLUMEN",precio_venta=Decimal("60"))
    assert changed.unidad_granel=="VOLUMEN"


def test_cambio_masivo_granel_default_peso(db):
    product=ProductService(db).crear_producto_externo("7500001120004","Arena",Decimal("20"),0,controla_inventario=False)
    assert ProductService(db).cambiar_tipo_masivo([product.id],"GRANEL")[0].unidad_granel=="PESO"


def test_formulario_nuevo_unidad_granel_y_cambio_repetido(app,db):
    dialog=QuickProductDialog(db);assert dialog.kind.isEnabled() and dialog.kind.currentText()=="UNIDAD" and not dialog.bulk_unit.isEnabled()
    for kind,enabled in (("GRANEL",True),("UNIDAD",False),("GRANEL",True)):
        dialog.kind.setCurrentText(kind);app.processEvents();assert dialog.bulk_unit.isEnabled() is enabled
    dialog.bulk_unit.setCurrentIndex(dialog.bulk_unit.findData("VOLUMEN"));assert dialog.bulk_unit.currentData()=="VOLUMEN"
    dialog.close()


def test_formulario_modificar_carga_volumen_y_transiciones(app,db):
    product=volume(db);dialog=ProductModifyDialog(product,ProductService(db));assert dialog.kind.isEnabled() and dialog.kind.currentText()=="GRANEL" and dialog.bulk_unit.isEnabled() and dialog.bulk_unit.currentData()=="VOLUMEN"
    dialog.kind.setCurrentText("UNIDAD");assert not dialog.bulk_unit.isEnabled()
    dialog.kind.setCurrentText("GRANEL");assert dialog.bulk_unit.isEnabled() and dialog.bulk_unit.currentData()=="VOLUMEN"
    dialog.bulk_unit.setCurrentIndex(dialog.bulk_unit.findData("PESO"));assert dialog.bulk_unit.currentData()=="PESO";dialog.close()


def test_servicio_unidad_granel_unidad_y_peso_volumen(db):
    service=ProductService(db);product=service.crear_producto_externo("7500001120090","Cambio",Decimal("10"),0,controla_inventario=False)
    product=service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="PESO",precio_venta=Decimal("10"));assert product.unidad_granel=="PESO"
    product=service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="VOLUMEN",precio_venta=Decimal("10"));assert product.unidad_granel=="VOLUMEN"
    product=service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="PESO",precio_venta=Decimal("10"));assert product.unidad_granel=="PESO"
    product=service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="UNIDAD",precio_venta=Decimal("10"));assert product.tipo_venta=="UNIDAD" and product.unidad_granel is None


def test_bloqueo_unidad_es_explicito_y_solo_con_stock_controlado(db):
    service=ProductService(db);product=weight(db,stock=1000,control=True)
    with pytest.raises(ValueError,match="controla inventario.*existencia no es cero"):
        service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="VOLUMEN",precio_venta=Decimal("80"))
    product=service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="PESO",precio_venta=Decimal("80"),controla_inventario=False)
    changed=service.modificar_producto(product.id,descripcion=product.descripcion,tipo_venta="GRANEL",unidad_granel="VOLUMEN",precio_venta=Decimal("60"),controla_inventario=False)
    assert changed.unidad_granel=="VOLUMEN"


def test_checkbox_inventario_visible_contraste_y_teclado(app,db):
    dialog=QuickProductDialog(db);checkbox=dialog.control;dialog.show();checkbox.setFocus();before=checkbox.isChecked();QTest.keyClick(checkbox,Qt.Key_Space);app.processEvents()
    assert checkbox.isVisible() and checkbox.hasFocus() and checkbox.isChecked() is not before
    assert "DESACTIVADO" in checkbox.text() and "indicator{width:22px;height:22px" in checkbox.styleSheet()
    QTest.keyClick(checkbox,Qt.Key_Space);assert checkbox.isChecked() is before and "ACTIVADO" in checkbox.text();dialog.close()
