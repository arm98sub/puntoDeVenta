import os
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtWidgets import QApplication,QDialog

from edition import Edition,get_edition_config
from ferreteria_core import Database
from ferreteria_core.services import BusinessConfigService,ProductService,SalesService,ThermalPrintSettings,ThermalPrintSettingsService,ThermalTicketRenderer,drawer_kick_command
from ferreteria_gui.pages import PosPage
from ferreteria_gui.settings_page import SettingsPage
from ferreteria_gui.config import visible_business_name
from ferreteria_gui.thermal_printing import ThermalPrinterService,WindowsPrinterBackend
import ferreteria_gui.config as gui_config
import ferreteria_gui.pages as gui_pages
import ferreteria_gui.settings_page as gui_settings


@pytest.fixture(scope="module")
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"thermal.db");value.migrate();return value


class FakeBackend:
    def __init__(self,names=("ELE-GATE IM.14",),fail_print=False,fail_drawer=False):self.names=list(names);self.fail_print=fail_print;self.fail_drawer=fail_drawer;self.printed=[];self.raw=[]
    def printer_names(self):return self.names
    def printable_columns(self,name,width):
        if not name:raise ValueError("Seleccione una impresora")
        return 16 if width==58 else 32
    def print_text(self,name,text,width):
        if not name:raise ValueError("Seleccione una impresora")
        if self.fail_print:raise OSError("impresora desconectada")
        self.printed.append((name,text,width))
    def send_raw(self,name,payload):
        if self.fail_drawer:raise OSError("cajón desconectado")
        self.raw.append((name,payload))


def _settings(path,**changes):
    values={"printer_name":"ELE-GATE IM.14","paper_width_mm":58,"auto_print":False,"auto_open_drawer":False}
    values.update(changes);return ThermalPrintSettingsService(path).save(ThermalPrintSettings(**values))


def test_guardar_y_cargar_impresora_sin_schema(tmp_path):
    path=tmp_path/"state"/"printing.json";saved=_settings(path,auto_print=True,auto_open_drawer=True)
    assert ThermalPrintSettingsService(path).load()==saved and saved.printer_name=="ELE-GATE IM.14" and saved.paper_width_mm==58


def test_impresora_no_configurada_falla_con_mensaje(db,tmp_path):
    service=ThermalPrinterService(db,tmp_path/"printing.json",FakeBackend())
    with pytest.raises(ValueError,match="Seleccione una impresora"):service.print_test()


def test_impresion_simulada_exitosa(db,tmp_path):
    path=tmp_path/"printing.json";_settings(path);backend=FakeBackend();service=ThermalPrinterService(db,path,backend);service.print_test()
    assert backend.printed and backend.printed[0][0]=="ELE-GATE IM.14" and backend.printed[0][2]==58


def test_ticket_granel_y_precio_variable_usan_snapshot_historico(db):
    products=ProductService(db,get_edition_config(Edition.GENERAL));bulk=products.crear_producto_externo("THERMAL-1","Maíz",Decimal("25"),0,tipo_venta="GRANEL",unidad_granel="PESO",controla_inventario=False);variable=products.crear_producto_externo("","Servicio",None,0,permitir_sin_barcode=True,precio_variable=True,controla_inventario=False)
    sale=SalesService(db).crear_venta([{"producto_id":bulk.id,"cantidad_mg":500_000},{"producto_id":variable.id,"cantidad":2,"precio_unitario_centavos":3750}],"TARJETA");products.actualizar_precio_venta(variable.id,Decimal("99"));business=BusinessConfigService(db).obtener();text=ThermalTicketRenderer().render(sale,business,58)
    assert "0.500 kg x $25.00" in text and "$12.50" in text and "2 x $37.50" in text and "$75.00" in text and "$99.00" not in text


def test_reimpresion_no_crea_venta_ni_modifica_stock(db,tmp_path):
    product=ProductService(db).crear_producto_externo("THERMAL-2","Producto",Decimal("10"),5);sale=SalesService(db).crear_venta([{"producto_id":product.id,"cantidad":2}],"TARJETA");path=tmp_path/"printing.json";_settings(path);backend=FakeBackend();service=ThermalPrinterService(db,path,backend)
    before_stock=ProductService(db).get(product.id).existencia;before_sales=SalesService(db).contar_ventas();service.print_sale_id(sale.id);service.print_sale_id(sale.id)
    assert len(backend.printed)==2 and backend.printed[0][1]==backend.printed[1][1] and SalesService(db).contar_ventas()==before_sales and ProductService(db).get(product.id).existencia==before_stock


def test_general_nunca_usa_ferreteria_como_fallback(monkeypatch):
    monkeypatch.setattr(gui_config,"TRUPER_ENABLED",False);monkeypatch.setattr(gui_config,"APP_NAME","PuntoDeVenta General")
    assert visible_business_name("FERRETERÍA")==visible_business_name("Ferreteria")==visible_business_name("")=="PuntoDeVenta General"


def test_layout_58mm_envuelve_descripcion_y_conserva_importes_grandes():
    detail=SimpleNamespace(descripcion_snapshot="Descripción extremadamente larga que debe ocupar varias líneas sin desplazar el subtotal",clave_snapshot="",codigo_barras_snapshot="",tipo_venta_snapshot="UNIDAD",unidad_granel_snapshot=None,cantidad=123456,precio_unitario_centavos=987654321,subtotal_centavos=123456789,cantidad_mg=None,precio_por_kg_centavos=None)
    sale=SimpleNamespace(folio="V-999999",fecha_hora="2026-08-30T12:00:00Z",detalles=[detail],total_centavos=123456789,metodo_pago="EFECTIVO",efectivo_recibido_centavos=123556789,cambio_centavos=100000)
    business=SimpleNamespace(nombre_negocio="PuntoDeVenta General",direccion="",telefono="",rfc="",mensaje_ticket="Gracias por su compra")
    text=ThermalTicketRenderer().render(sale,business,58,columns=16)
    assert "$1,234,567.89" in text and "$1,000.00" in text and "123456 x" in text and "$9,876,543.21" in text
    assert all(len(line)<=16 for line in text.splitlines())
    assert "Descripción" in text and "subtotal" in text


@pytest.mark.parametrize("unit,suffix",[("PESO","kg"),("VOLUMEN","L")])
def test_layout_granel_58mm_mantiene_cantidad_unidad_e_importe(unit,suffix):
    detail=SimpleNamespace(descripcion_snapshot="Producto a granel con nombre largo",clave_snapshot="",codigo_barras_snapshot="",tipo_venta_snapshot="GRANEL",unidad_granel_snapshot=unit,cantidad=None,precio_unitario_centavos=None,subtotal_centavos=123456789,cantidad_mg=123456789,precio_por_kg_centavos=99999999)
    sale=SimpleNamespace(folio="V-2",fecha_hora="2026-08-30T12:00:00Z",detalles=[detail],total_centavos=123456789,metodo_pago="TARJETA",efectivo_recibido_centavos=None,cambio_centavos=None)
    business=SimpleNamespace(nombre_negocio="General",direccion="",telefono="",rfc="",mensaje_ticket="")
    text=ThermalTicketRenderer().render(sale,business,58,columns=16)
    assert f"123.457 {suffix}" in text and "$1,234,567.89" in text and all(len(line)<=16 for line in text.splitlines())


def test_altura_del_trabajo_no_impone_setenta_mm_y_deja_avance_breve():
    height=WindowsPrinterBackend.job_height_mm(6,Decimal("3.4"))
    assert 25<=height<40 and WindowsPrinterBackend.FINAL_FEED_MM==6.0


def test_rollo_58_solicita_formulario_personalizado_48mm_sin_tocar_driver():
    assert WindowsPrinterBackend.driver_page_dimensions(58,47.5)==(48.0,47.5)


def test_apertura_manual_envia_pulso_escpos_configurable(db,tmp_path):
    path=tmp_path/"printing.json";settings=_settings(path);backend=FakeBackend();command=ThermalPrinterService(db,path,backend).open_drawer()
    assert command==drawer_kick_command(settings)==b"\x1bp\x00\x19\xfa" and backend.raw==[("ELE-GATE IM.14",command)]


class CashPayment:
    def __init__(self,*_):self.payment=type("Payment",(),{"recibido_centavos":10000})();self.method=type("Method",(),{"currentText":lambda _self:"EFECTIVO"})()
    def exec(self):return QDialog.DialogCode.Accepted

class CardPayment(CashPayment):
    def __init__(self,*_):super().__init__();self.payment=type("Payment",(),{"recibido_centavos":None})();self.method=type("Method",(),{"currentText":lambda _self:"TARJETA"})()

class NoPdf:
    def __init__(self,*_):pass
    def generar_para_venta(self,_sale):return None

class Complete:
    seen=[]
    def __init__(self,*args):self.args=args;Complete.seen.append(args)
    def exec(self):return QDialog.DialogCode.Accepted

class AutoThermal:
    def __init__(self,db,fail_print=False,fail_drawer=False):self.db=db;self.fail_print=fail_print;self.fail_drawer=fail_drawer;self.calls=[];self.settings=type("Settings",(),{"load":lambda _self:ThermalPrintSettings("Impresora",58,True,True)})()
    def open_drawer(self):
        assert SalesService(self.db).contar_ventas()==1;self.calls.append("drawer")
        if self.fail_drawer:raise OSError("drawer")
    def print_sale(self,_sale):
        assert SalesService(self.db).contar_ventas()==1;self.calls.append("print")
        if self.fail_print:raise OSError("print")


@pytest.mark.parametrize("fail_print,fail_drawer",[(True,False),(False,True),(True,True)])
def test_fallo_postventa_no_revierte_venta_ni_inventario(app,db,monkeypatch,fail_print,fail_drawer):
    product=ProductService(db).crear_producto_externo("THERMAL-3","Producto",Decimal("10"),3);page=PosPage(db);page.cart.agregar_producto(product.id);thermal=AutoThermal(db,fail_print,fail_drawer);page.thermal=thermal;Complete.seen.clear();monkeypatch.setattr(gui_pages,"PaymentDialog",CashPayment);monkeypatch.setattr(gui_pages,"TicketService",NoPdf);monkeypatch.setattr(gui_pages,"SaleCompletedDialog",Complete);page.checkout()
    assert SalesService(db).contar_ventas()==1 and ProductService(db).get(product.id).existencia==2 and thermal.calls==["drawer","print"] and Complete.seen


def test_cajon_automatico_solo_efectivo_y_despues_de_venta(app,db,monkeypatch):
    product=ProductService(db).crear_producto_externo("THERMAL-4","Producto",Decimal("10"),3);page=PosPage(db);page.cart.agregar_producto(product.id);thermal=AutoThermal(db);page.thermal=thermal;monkeypatch.setattr(gui_pages,"PaymentDialog",CardPayment);monkeypatch.setattr(gui_pages,"TicketService",NoPdf);monkeypatch.setattr(gui_pages,"SaleCompletedDialog",Complete);page.checkout()
    assert thermal.calls==["print"] and SalesService(db).contar_ventas()==1 and ProductService(db).get(product.id).existencia==2


def test_configuracion_impresora_solo_general(app,db,tmp_path,monkeypatch):
    general=get_edition_config(Edition.GENERAL);monkeypatch.setattr(gui_settings,"EDITION",general);monkeypatch.setattr(gui_settings,"PRINTING_CONFIG_PATH",tmp_path/"general.json");general_page=SettingsPage(db)
    assert general_page.thermal is not None and general_page.paper.currentData()==58 and general_page.auto_print.text().startswith("Imprimir ticket") and general_page.auto_drawer.text().endswith("efectivo")
    monkeypatch.setattr(gui_settings,"EDITION",get_edition_config(Edition.FERRETERIA));ferreteria_page=SettingsPage(db)
    assert ferreteria_page.thermal is None
