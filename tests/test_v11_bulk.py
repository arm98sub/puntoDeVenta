import sqlite3
from decimal import Decimal

import pytest

from ferreteria_core import Database
from ferreteria_core.quantity import (formato_cantidad,gramos_a_mg,importe_a_mg,kg_a_mg,
                                      subtotal_granel_centavos)
from ferreteria_core.repositories import ProductRepository
from ferreteria_core.services import (BackupService,BulkQuantityRequired,Cart,InsufficientStockError,
    InventoryService,ProductEditSession,ProductService,SalesService,TicketService,validar_respaldo)


@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"v11.db");value.migrate();return value


def bulk(db,barcode="7500000001000",price="80",stock=3_450_000):
    return ProductService(db).crear_producto_externo(barcode,'Clavo 2"',Decimal(price),0,clave="CLA-2",tipo_venta="GRANEL",existencia_granel_mg=stock)


def unit(db,barcode="7500000002000",price="185",stock=10):
    return ProductService(db).crear_producto_externo(barcode,"Martillo",Decimal(price),stock)


def test_migracion_v5_preserva_producto_como_unidad(tmp_path):
    database=Database(tmp_path/"old.db")
    from ferreteria_core.database.migrations import MIGRATIONS
    with database.connect() as c:
        c.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        for version,sql in MIGRATIONS[:4]:c.executescript(sql);c.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
        c.execute("INSERT INTO productos(descripcion,existencia) VALUES('Anterior',7)")
    database.migrate();product=ProductService(database).get(1)
    assert product.tipo_venta=="UNIDAD" and product.existencia==7 and product.existencia_granel_mg==0


@pytest.mark.parametrize(("grams","mg"),[("38",38_000),("62.5",62_500),("500",500_000),("1000",1_000_000)])
def test_conversion_gramos_exacta(grams,mg):assert gramos_a_mg(grams)==mg


def test_conversion_kg_y_presentacion():
    assert kg_a_mg("3.450")==3_450_000
    assert formato_cantidad("GRANEL",miligramos=3_450_000)=="3.45 kg"
    assert formato_cantidad("GRANEL",miligramos=62_500)=="0.0625 kg"
    assert formato_cantidad("UNIDAD",unidades=2)=="2 pzas"


@pytest.mark.parametrize(("mg","expected"),[(1_000_000,8000),(500_000,4000),(250_000,2000),(62_500,500),(38_000,304)])
def test_precio_por_kg(mg,expected):assert subtotal_granel_centavos(8000,mg)==expected


def test_importe_a_peso():
    assert importe_a_mg(200,8000)==25_000
    assert subtotal_granel_centavos(8000,importe_a_mg(200,8000))==200


def test_redondeo_half_up():assert subtotal_granel_centavos(3333,150)==0 and subtotal_granel_centavos(3333,151)==1


def test_crear_y_cambiar_tipo(db):
    product=bulk(db);assert product.tipo_venta=="GRANEL" and product.precio_venta==8000
    other=unit(db);updated=ProductService(db).cambiar_tipo_masivo([other.id],"GRANEL")[0]
    assert updated.tipo_venta=="GRANEL" and updated.precio_venta==18500


def test_cambios_masivos_seguros_activo_categoria_preservan_precios(db):
    a=unit(db);b=unit(db,"7500000002001",price="99");service=ProductService(db)
    service.aplicar_cambios({a.id:{"activo":False,"categoria":"Clavos"},b.id:{"activo":False,"categoria":"Clavos"}})
    a2,b2=service.get(a.id),service.get(b.id)
    assert not a2.activo and not b2.activo and a2.categoria==b2.categoria=="Clavos"
    assert (a2.precio_venta,b2.precio_venta)==(18500,9900)


def test_carrito_granel_requiere_peso_y_suma_escaneos(db):
    product=bulk(db);cart=Cart(db)
    with pytest.raises(BulkQuantityRequired):cart.agregar_por_barcode(product.codigo_barras)
    cart.agregar_granel(product.id,38_000);cart.agregar_granel(product.id,62_500)
    assert len(cart.items)==1 and cart.items[0].cantidad_mg==100_500


def test_carrito_mixto(db):
    b=bulk(db);u=unit(db);cart=Cart(db);cart.agregar_granel(b.id,38_000);cart.agregar_producto(u.id,2)
    assert cart.total_centavos==37304 and len(cart.items)==2


def test_stock_granel_insuficiente_y_cero(db):
    product=bulk(db,stock=50_000);cart=Cart(db)
    with pytest.raises(InsufficientStockError) as error:cart.agregar_granel(product.id,75_000)
    assert error.value.available==50_000
    InventoryService(db).ajustar_existencia_granel(product.id,0,"Conteo")
    with pytest.raises(InsufficientStockError):cart.agregar_granel(product.id,1)


def test_entrada_y_ajuste_granel_generan_movimiento(db):
    product=bulk(db,stock=1_250_000);inventory=InventoryService(db)
    inventory.registrar_entrada_granel(product.id,250_000,"Llegada");inventory.ajustar_existencia_granel(product.id,1_800_000,"Conteo")
    with db.connect() as c:rows=c.execute("SELECT tipo,cantidad_mg,existencia_nueva_mg FROM movimientos_inventario WHERE producto_id=? ORDER BY id",(product.id,)).fetchall()
    assert [(r[0],r[1],r[2]) for r in rows][-2:]==[("ENTRADA",250_000,1_500_000),("AJUSTE",300_000,1_800_000)]
    listed=inventory.listar_movimientos(product.id);assert listed[0]["tipo"]=="AJUSTE" and listed[0]["cantidad_mg"]==300_000


def test_venta_mixta_snapshot_stock_cancelacion(db):
    b=bulk(db);u=unit(db);sale=SalesService(db).crear_venta([{"producto_id":b.id,"cantidad_mg":38_000},{"producto_id":u.id,"cantidad":2}],"EFECTIVO",Decimal("400"))
    assert sale.subtotal_centavos==37304 and sale.cambio_centavos==2696
    detail=next(d for d in sale.detalles if d.producto_id==b.id)
    assert (detail.tipo_venta_snapshot,detail.cantidad_mg,detail.unidad_snapshot,detail.precio_por_kg_centavos,detail.subtotal_centavos)==("GRANEL",38_000,"MG",8000,304)
    assert ProductService(db).get(b.id).existencia_granel_mg==3_412_000
    SalesService(db).cancelar_venta(sale.id,"Prueba");assert ProductService(db).get(b.id).existencia_granel_mg==3_450_000


def test_venta_granel_rollback_stock(db):
    a=bulk(db,stock=100_000);b=bulk(db,"7500000001001",stock=10_000)
    with pytest.raises(ValueError):SalesService(db).crear_venta([{"producto_id":a.id,"cantidad_mg":50_000},{"producto_id":b.id,"cantidad_mg":20_000}],"TARJETA")
    assert ProductService(db).get(a.id).existencia_granel_mg==100_000
    with db.connect() as c:assert c.execute("SELECT count(*) FROM ventas").fetchone()[0]==0


def test_ticket_granel_y_compatibilidad_unidad(db,tmp_path):
    b=bulk(db);u=unit(db);service=SalesService(db)
    sale=service.crear_venta([{"producto_id":b.id,"cantidad_mg":38_000},{"producto_id":u.id,"cantidad":1}],"TARJETA")
    path=TicketService(db,tmp_path/"tickets").generar_para_venta(sale)
    from pypdf import PdfReader
    text="\n".join(page.extract_text() for page in PdfReader(path).pages)
    assert "0.038 kg x $80.00/kg" in text and "1 x $185.00" in text


def test_edicion_lote_guardar_descartar_y_protegidos(db):
    a=unit(db);session=ProductEditSession(db);session.set(a.id,"precio_venta","55.25");session.set(a.id,"descripcion","Nuevo");session.set(a.id,"tipo_venta","GRANEL")
    assert session.count==3 and ProductService(db).get(a.id).precio_venta==18500
    session.save();updated=ProductService(db).get(a.id);assert (updated.precio_venta,updated.descripcion,updated.tipo_venta)==(5525,"Nuevo","GRANEL")
    session.set(a.id,"descripcion","Temporal");session.discard();assert ProductService(db).get(a.id).descripcion=="Nuevo"
    with pytest.raises(ValueError,match="protegido"):session.set(a.id,"codigo_barras","x")


def test_lote_invalido_no_guarda_y_rollback(db,monkeypatch):
    a=unit(db);b=unit(db,"7500000002001");service=ProductService(db)
    with pytest.raises(ValueError):service.aplicar_cambios({a.id:{"descripcion":"Cambio"},b.id:{"precio_venta":Decimal("-1")}})
    assert ProductService(db).get(a.id).descripcion=="Martillo"
    original=ProductRepository.update_fields;calls=[]
    def fail(connection,pid,values):
        calls.append(pid)
        if len(calls)==2:raise RuntimeError("simulado")
        return original(connection,pid,values)
    monkeypatch.setattr(ProductRepository,"update_fields",fail)
    with pytest.raises(RuntimeError):service.aplicar_cambios({a.id:{"descripcion":"A"},b.id:{"descripcion":"B"}})
    assert ProductService(db).get(a.id).descripcion=="Martillo"


def test_backup_restore_con_granel(db,tmp_path):
    product=bulk(db);service=BackupService(db,tmp_path/"backups");path=service.crear_manual();validar_respaldo(path)
    InventoryService(db).ajustar_existencia_granel(product.id,1,"Cambio");service.restaurar(path)
    assert ProductService(db).get(product.id).existencia_granel_mg==3_450_000
    with sqlite3.connect(db.path) as c:assert c.execute("PRAGMA integrity_check").fetchone()[0]=="ok"


def test_restaurar_backup_v1_migra_incrementalmente(tmp_path):
    from ferreteria_core.database.migrations import MIGRATIONS
    old=tmp_path/"v1.db";connection=sqlite3.connect(old)
    connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for version,sql in MIGRATIONS[:4]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    connection.execute("INSERT INTO productos(descripcion,existencia) VALUES('Legado',3)");connection.commit();connection.close()
    target=Database(tmp_path/"target.db");target.migrate();BackupService(target,tmp_path/"backups").restaurar(old)
    product=ProductService(target).get(1);assert product.tipo_venta=="UNIDAD" and product.existencia==3
    assert validar_respaldo(target.path).schema_version==8
