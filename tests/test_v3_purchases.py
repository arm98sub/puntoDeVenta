import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest

from edition import Edition,get_edition_config
from ferreteria_core import Database
from ferreteria_core.database.migrations import MIGRATIONS
from ferreteria_core.services import (CategoryService,InventoryService,ProductService,PurchasePresentationService,
    PurchaseService,SupplierService,seed_general_purchase_presentations,GENERAL_PURCHASE_PRESENTATIONS)
from updater_core import migrate_database,validate_database
from ferreteria_core.repositories import ProductRepository
from ferreteria_gui.purchases_page import purchase_presentation_options


@pytest.fixture
def db(tmp_path):value=Database(tmp_path/"v3.db");value.migrate();return value


def _schema9(path):
    connection=sqlite3.connect(path);connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    connection.create_function("NORMALIZE_TEXT",1,lambda value:" ".join((value or "").lower().split()),deterministic=True)
    for version,sql in MIGRATIONS[:9]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    return connection


def _product(db,barcode="7500000100001",**kwargs):return ProductService(db,get_edition_config(Edition.GENERAL)).crear_producto_externo(barcode,"Producto",Decimal("100"),kwargs.pop("existencia",0),precio_proveedor=Decimal("50"),**kwargs)


def test_migracion_9_a_10_conserva_datos_y_relaciones(tmp_path):
    path=tmp_path/"old.db";connection=_schema9(path);category=connection.execute("INSERT INTO categorias(nombre,nombre_normalizado) VALUES('Bebidas','bebidas')").lastrowid;supplier=connection.execute("INSERT INTO proveedores(nombre,nombre_normalizado) VALUES('Proveedor','proveedor')").lastrowid
    product=connection.execute("INSERT INTO productos(descripcion,categoria_id,proveedor_principal_id,existencia,es_truper,datos_completos,requiere_revision) VALUES('Uno',?,?,7,0,1,0)",(category,supplier)).lastrowid
    connection.execute("INSERT INTO ventas(folio,subtotal_centavos,total_centavos,metodo_pago) VALUES('V-1',100,100,'EFECTIVO')");connection.execute("INSERT INTO movimientos_inventario(producto_id,tipo,cantidad,existencia_anterior,existencia_nueva) VALUES(?,'AJUSTE',7,0,7)",(product,));connection.commit();connection.close()
    migrate_database(path,9,10)
    assert validate_database(path).schema_version==10
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT existencia,categoria_id,proveedor_principal_id,presentacion_compra_id,contenido_por_presentacion FROM productos").fetchone()==(7,category,supplier,None,None)
        assert connection.execute("SELECT count(*) FROM ventas").fetchone()[0]==1 and connection.execute("SELECT count(*) FROM movimientos_inventario").fetchone()[0]==1
        assert {"presentaciones_compra","compras","compra_detalles"}<={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_actualizador_encadena_schema_8_a_10(tmp_path):
    path=tmp_path/"schema8.db";connection=sqlite3.connect(path);connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for version,sql in MIGRATIONS[:8]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    connection.execute("INSERT INTO productos(descripcion,categoria,es_truper,datos_completos,requiere_revision) VALUES('Conservado','Abarrotes',0,1,0)");connection.commit();connection.close();migrate_database(path,8,10)
    assert validate_database(path).schema_version==10
    with sqlite3.connect(path) as connection:assert connection.execute("SELECT categoria_id IS NOT NULL,presentacion_compra_id FROM productos").fetchone()==(1,None)


def test_presentaciones_crud_normalizacion_y_seed(db):
    service=PurchasePresentationService(db);item=service.crear("  Cajá   grande ")
    for duplicate in ("caja grande"," CAJÁ GRANDE "):
        with pytest.raises(ValueError,match="existe"):service.crear(duplicate)
    with pytest.raises(ValueError,match="obligatorio"):service.crear(" ")
    item=service.editar(item.id,"Bulto");assert item.nombre=="Bulto"
    assert not service.desactivar(item.id).activo and service.listar_activas()==[]
    assert service.reactivar(item.id).activo
    seed_general_purchase_presentations(db);seed_general_purchase_presentations(db)
    assert {item.nombre for item in service.listar_todas()}>={*GENERAL_PURCHASE_PRESENTATIONS,"Bulto"}


def test_calculo_unidad_caja_y_pieza(db):
    product=_product(db);presentation=PurchasePresentationService(db).crear("Caja");service=PurchaseService(db)
    box=service.crear_linea(product.id,presentation.id,2,24,Decimal("360"));piece=service.crear_linea(product.id,None,1,1,Decimal("15"))
    assert (box.cantidad_base,box.costo_unitario_centavos,box.subtotal_centavos)==(48,1500,72000)
    assert (piece.cantidad_base,piece.costo_unitario_centavos,piece.subtotal_centavos)==(1,1500,1500)


def test_selector_gui_usa_pieza_formal_una_sola_vez(db):
    seed_general_purchase_presentations(db);options=purchase_presentation_options(PurchasePresentationService(db).listar_activas())
    assert [name for _item_id,name in options].count("Pieza")==1
    piece_id=next(item_id for item_id,name in options if name=="Pieza");product=_product(db)
    line=PurchaseService(db).crear_linea(product.id,piece_id,2,1,Decimal("10"))
    assert line.presentacion_id==piece_id and line.presentacion_nombre=="Pieza" and line.cantidad_base==2


@pytest.mark.parametrize("unit,count,content,expected",[("PESO",2,"20",40_000_000),("VOLUMEN",3,"20",60_000_000)])
def test_calculo_granel_exacto(db,unit,count,content,expected):
    product=_product(db,f"75000001000{len(unit)}",tipo_venta="GRANEL",unidad_granel=unit,existencia_granel_mg=0)
    line=PurchaseService(db).crear_linea(product.id,None,count,content,Decimal("400"))
    assert line.cantidad_base==expected and isinstance(line.cantidad_base,int)


def test_confirmar_multilinea_proveedor_snapshots_movimientos_y_costo(db):
    supplier=SupplierService(db).crear("Distribuidor");presentation=PurchasePresentationService(db).crear("Caja");one=_product(db,"7500000100101",existencia=3);two=_product(db,"7500000100102")
    service=PurchaseService(db);lines=[service.crear_linea(one.id,presentation.id,2,24,Decimal("360")),service.crear_linea(two.id,None,5,1,Decimal("20"))]
    purchase=service.confirmar(lines,supplier.id,"FAC-1",notas="Entrega")
    assert purchase.folio=="C-000001" and purchase.proveedor_nombre_snapshot=="Distribuidor" and purchase.total_centavos==82000 and len(purchase.detalles)==2
    assert ProductService(db).get(one.id).existencia==51 and ProductService(db).get(one.id).precio_proveedor==1500 and ProductService(db).get(one.id).precio_venta==10000
    with db.connect() as connection:assert connection.execute("SELECT count(*) FROM movimientos_inventario WHERE tipo='COMPRA' AND referencia=?",(purchase.folio,)).fetchone()[0]==2


def test_folio_unico_y_proveedor_opcional(db):
    product=_product(db);service=PurchaseService(db);line=service.crear_linea(product.id,None,1,1,Decimal("10"));a=service.confirmar([line]);b=service.confirmar([line])
    assert (a.folio,b.folio)==("C-000001","C-000002") and a.proveedor_id is None


def test_lineas_repetidas_mismo_producto_acumulan_y_cancelan(db):
    product=_product(db);service=PurchaseService(db);one=service.crear_linea(product.id,None,2,1,Decimal("10"));two=service.crear_linea(product.id,None,3,1,Decimal("10"));purchase=service.confirmar([one,two])
    assert ProductService(db).get(product.id).existencia==5
    service.cancelar(purchase.id);assert ProductService(db).get(product.id).existencia==0


def test_producto_sin_control_registra_compra_y_costo_sin_stock(db):
    product=_product(db,controla_inventario=False);service=PurchaseService(db);purchase=service.confirmar([service.crear_linea(product.id,None,3,1,Decimal("12"))])
    updated=ProductService(db).get(product.id);assert updated.existencia==0 and updated.precio_proveedor==1200 and purchase.detalles[0].controla_inventario_snapshot is False
    with db.connect() as connection:assert connection.execute("SELECT count(*) FROM movimientos_inventario WHERE referencia=?",(purchase.folio,)).fetchone()[0]==0


def test_fallo_en_linea_revierte_toda_transaccion(db):
    one=_product(db,"7500000100201");two=_product(db,"7500000100202");service=PurchaseService(db);lines=[service.crear_linea(one.id,None,1,1,Decimal("10")),service.crear_linea(two.id,None,1,1,Decimal("20"))]
    def fail(stage):
        if stage=="line_0":raise RuntimeError("fallo")
    with pytest.raises(RuntimeError):service.confirmar(lines,failure_hook=fail)
    assert service.listar()==[] and ProductService(db).get(one.id).existencia==0 and ProductService(db).get(two.id).existencia==0


def _assert_purchase_rejected_without_changes(db,product,line,match):
    before=ProductService(db).get(product.id)
    with db.connect() as connection:
        counts_before=tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("compras","compra_detalles","movimientos_inventario"))
    with pytest.raises((ValueError,LookupError),match=match):PurchaseService(db).confirmar([line])
    after=ProductService(db).get(product.id)
    with db.connect() as connection:
        counts_after=tuple(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("compras","compra_detalles","movimientos_inventario"))
    assert counts_after==counts_before
    assert (after.existencia,after.existencia_granel_mg,after.precio_proveedor)==(before.existencia,before.existencia_granel_mg,before.precio_proveedor)


def test_confirmar_revalida_presentacion_y_producto_activos(db):
    presentation=PurchasePresentationService(db).crear("Caja");product=_product(db);service=PurchaseService(db);line=service.crear_linea(product.id,presentation.id,1,12,Decimal("120"))
    PurchasePresentationService(db).desactivar(presentation.id);_assert_purchase_rejected_without_changes(db,product,line,"inactiva")
    PurchasePresentationService(db).reactivar(presentation.id)
    with db.transaction() as connection:ProductRepository.update_fields(connection,product.id,{"activo":False})
    _assert_purchase_rejected_without_changes(db,product,line,"inactivo")


@pytest.mark.parametrize("initial_type,initial_unit,new_type,new_unit",[("UNIDAD",None,"GRANEL","PESO"),("GRANEL","PESO","UNIDAD",None),("GRANEL","PESO","GRANEL","VOLUMEN")])
def test_confirmar_rechaza_cambio_tipo_o_unidad(db,initial_type,initial_unit,new_type,new_unit):
    product=_product(db,tipo_venta=initial_type,unidad_granel=initial_unit,existencia_granel_mg=0);service=PurchaseService(db);line=service.crear_linea(product.id,None,1,1,Decimal("10"))
    with db.transaction() as connection:ProductRepository.update_fields(connection,product.id,{"tipo_venta":new_type,"unidad_granel":new_unit})
    _assert_purchase_rejected_without_changes(db,product,line,"cambió")


def test_confirmar_rechaza_linea_manipulada_sin_efectos(db):
    product=_product(db,existencia=4);line=PurchaseService(db).crear_linea(product.id,None,2,1,Decimal("10"));tampered=replace(line,cantidad_base=200,subtotal_centavos=1,costo_unitario_centavos=1)
    _assert_purchase_rejected_without_changes(db,product,tampered,"inconsistente")


def test_cancelar_compra_revierte_inventario_con_movimiento_inverso(db):
    product=_product(db,existencia=5);service=PurchaseService(db);purchase=service.confirmar([service.crear_linea(product.id,None,24,1,Decimal("10"))]);cancelled=service.cancelar(purchase.id)
    assert cancelled.estado=="CANCELADA" and len(cancelled.detalles)==1 and ProductService(db).get(product.id).existencia==5
    with db.connect() as connection:assert connection.execute("SELECT count(*) FROM movimientos_inventario WHERE referencia=?",(purchase.folio,)).fetchone()[0]==2
    with pytest.raises(ValueError,match="cancelada"):service.cancelar(purchase.id)


def test_cancelacion_negativa_se_bloquea_completa(db):
    product=_product(db);service=PurchaseService(db);purchase=service.confirmar([service.crear_linea(product.id,None,24,1,Decimal("10"))]);InventoryService(db).ajustar_existencia(product.id,4,"ventas posteriores")
    with pytest.raises(ValueError,match="negativa"):service.cancelar(purchase.id)
    assert service.obtener(purchase.id).estado=="CONFIRMADA" and ProductService(db).get(product.id).existencia==4


def test_presentacion_habitual_es_opcional_y_persiste(db):
    product=_product(db);presentation=PurchasePresentationService(db).crear("Caja");service=ProductService(db);assert product.presentacion_compra_id is None
    updated=service.configurar_presentacion_compra(product.id,presentation.id,24);assert (updated.presentacion_compra_id,updated.contenido_por_presentacion)==(presentation.id,24)
