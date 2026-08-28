from decimal import Decimal

import pytest
from pypdf import PdfReader

from ferreteria_core import Database
from ferreteria_core.services import ProductService, SalesService, TicketService


@pytest.fixture
def sale_data(tmp_path):
    db=Database(tmp_path/"ticket.db"); db.migrate(); products=ProductService(db)
    a=products.crear_producto_externo("7500000000001","Silicón transparente",Decimal("51"),10,clave="SIL-85T")
    b=products.crear_producto_externo("7500000000002","Martillo",Decimal("185"),10)
    sale=SalesService(db).crear_venta([{"producto_id":a.id,"cantidad":2},{"producto_id":b.id,"cantidad":1}],"EFECTIVO",Decimal("300"),Decimal("0"))
    return db,sale,a,b,tmp_path/"tickets"


def text(path):return "\n".join((page.extract_text() or "") for page in PdfReader(path).pages)


def test_generar_pdf_folio_fecha_productos_totales(sale_data):
    db,sale,_,_,root=sale_data; path=TicketService(db,root).generar_para_venta(sale); content=text(path)
    assert path.exists() and path.suffix==".pdf" and sale.folio in content
    assert "Silicón transparente" in content and "Martillo" in content
    assert "$287.00" in content and "$300.00" in content and "$13.00" in content
    assert sale.fecha_hora[:4] in str(path)


def test_ticket_usa_snapshots_y_precio_historico(sale_data):
    db,sale,a,_,root=sale_data
    with db.connect() as c:c.execute("UPDATE productos SET descripcion='CAMBIADO',precio_venta=99999 WHERE id=?",(a.id,))
    content=text(TicketService(db,root).generar_para_venta(sale))
    assert "Silicón transparente" in content and "CAMBIADO" not in content and "$51.00" in content


def test_ticket_transferencia_sin_cambio(tmp_path):
    db=Database(tmp_path/"t.db");db.migrate();p=ProductService(db).crear_producto_externo("7500000000001","Uno",Decimal("10"),1)
    sale=SalesService(db).crear_venta([{"producto_id":p.id,"cantidad":1}],"TRANSFERENCIA"); content=text(TicketService(db,tmp_path/"tickets").generar_para_venta(sale))
    assert "TRANSFERENCIA" in content and "Cambio" not in content and "Recibido" not in content


def test_producto_sin_descripcion_en_ticket(tmp_path):
    db=Database(tmp_path/"t.db");db.migrate();p=ProductService(db).crear_producto_externo("7500000000001","Temporal",Decimal("10"),1,clave="CLAVE-X")
    with db.connect() as c:c.execute("UPDATE productos SET descripcion=NULL WHERE id=?",(p.id,))
    sale=SalesService(db).crear_venta([{"producto_id":p.id,"cantidad":1}],"TARJETA")
    assert "CLAVE-X" in text(TicketService(db,tmp_path/"tickets").generar_para_venta(sale))


def test_ticket_cancelado_y_regeneracion(sale_data):
    db,sale,_,_,root=sale_data; tickets=TicketService(db,root); original=tickets.generar_para_venta(sale)
    SalesService(db).cancelar_venta(sale.id,"Prueba"); regenerated=tickets.regenerar(sale.id)
    assert regenerated==original and "VENTA CANCELADA" in text(regenerated)


def test_existente_no_se_sobrescribe_silenciosamente(sale_data):
    db,sale,_,_,root=sale_data; tickets=TicketService(db,root); first=tickets.generar_para_venta(sale)
    assert tickets.generar_para_venta(sale)==first and tickets.obtener_o_generar(sale.id)==first


def test_fallo_pdf_no_revierte_venta(sale_data,monkeypatch):
    db,sale,_,_,root=sale_data; tickets=TicketService(db,root)
    monkeypatch.setattr(tickets,"_write",lambda *a,**k:(_ for _ in ()).throw(OSError("disco lleno")))
    with pytest.raises(OSError):tickets.generar_para_venta(sale)
    assert SalesService(db).obtener_por_id(sale.id).estado=="COMPLETADA"
