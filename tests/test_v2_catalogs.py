import sqlite3
from decimal import Decimal

import pytest

from edition import Edition,get_edition_config
from ferreteria_core import Database
from ferreteria_core.database.migrations import MIGRATIONS
from ferreteria_core.services import CategoryService,ProductService,SupplierService,seed_general_categories,GENERAL_CATEGORIES
from updater_core import migrate_database,validate_database


@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"schema9.db");value.migrate();return value


def _schema8(path):
    connection=sqlite3.connect(path);connection.execute("PRAGMA foreign_keys=ON");connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for version,sql in MIGRATIONS[:8]:connection.executescript(sql);connection.execute("INSERT INTO schema_migrations(version) VALUES(?)",(version,))
    return connection


def test_migracion_8_a_9_conserva_datos_y_normaliza_categorias(tmp_path):
    path=tmp_path/"old.db";connection=_schema8(path)
    ids=[]
    for index,category in enumerate(("Herramientas"," herramientas ","HERRAMIENTAS"),1):
        ids.append(connection.execute("INSERT INTO productos(codigo_barras,descripcion,categoria,precio_venta,existencia,es_truper,datos_completos,requiere_revision) VALUES(?,?,?,?,?,0,1,0)",(f"750{index}",f"P{index}",category,1000,index)).lastrowid)
    connection.execute("INSERT INTO ventas(folio,subtotal_centavos,total_centavos,metodo_pago) VALUES('V-1',1000,1000,'EFECTIVO')")
    connection.execute("INSERT INTO detalle_venta(venta_id,producto_id,descripcion_snapshot,cantidad,precio_unitario_centavos,subtotal_centavos) VALUES(1,?,'P1',1,1000,1000)",(ids[0],))
    connection.execute("INSERT INTO movimientos_inventario(producto_id,tipo,cantidad,existencia_anterior,existencia_nueva) VALUES(?,'AJUSTE',1,0,1)",(ids[0],));connection.commit();connection.close()
    Database(path).migrate()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]==9
        assert connection.execute("SELECT count(*) FROM categorias").fetchone()[0]==1
        assert len({row[0] for row in connection.execute("SELECT categoria_id FROM productos")})==1
        assert connection.execute("SELECT group_concat(categoria,'|') FROM productos").fetchone()[0]=="Herramientas| herramientas |HERRAMIENTAS"
        assert connection.execute("SELECT count(*) FROM ventas").fetchone()[0]==1
        assert connection.execute("SELECT count(*) FROM movimientos_inventario").fetchone()[0]==1


def test_actualizador_migra_schema_8_a_9(tmp_path):
    path=tmp_path/"updater.db";connection=_schema8(path);connection.execute("INSERT INTO productos(descripcion,categoria,es_truper,datos_completos,requiere_revision) VALUES('Uno','  Lácteos  ',0,1,0)");connection.commit();connection.close()
    migrate_database(path,8,9)
    assert validate_database(path).schema_version==9
    with sqlite3.connect(path) as connection:assert connection.execute("SELECT c.nombre FROM productos p JOIN categorias c ON c.id=p.categoria_id").fetchone()[0]=="Lácteos"


def test_categorias_crud_duplicados_y_relacion_desactivada(db):
    service=CategoryService(db);category=service.crear("  Bebidas   frías ")
    assert category.nombre=="Bebidas frías"
    for duplicate in ("bebidas frías"," BEBIDAS FRÍAS "):
        with pytest.raises(ValueError,match="existe"):service.crear(duplicate)
    category=service.editar(category.id,"Bebidas preparadas");assert category.nombre=="Bebidas preparadas"
    product=ProductService(db).crear_producto_externo("7500000001001","Agua",Decimal("10"),2,categoria_id=category.id)
    service.desactivar(category.id);assert service.listar_activas()==[] and service.obtener(category.id).activo is False
    assert ProductService(db).get(product.id).categoria_id==category.id
    assert service.reactivar(category.id).activo and len(service.listar_activas())==1


def test_categoria_nombre_obligatorio(db):
    with pytest.raises(ValueError,match="obligatorio"):CategoryService(db).crear("   ")


def test_seed_general_idempotente(db):
    seed_general_categories(db);seed_general_categories(db)
    assert len(CategoryService(db).listar_todas())==len(GENERAL_CATEGORIES)


def test_proveedores_crud_duplicados_y_producto_opcional(db):
    service=SupplierService(db);supplier=service.crear("  Distribuidora   Uno ","555","Ana","Semanal")
    assert supplier.nombre=="Distribuidora Uno" and supplier.telefono=="555"
    for duplicate in ("distribuidora uno"," DISTRIBUIDORA UNO "):
        with pytest.raises(ValueError,match="existe"):service.crear(duplicate)
    supplier=service.editar(supplier.id,"Distribuidora Central",contacto="Luis");assert supplier.contacto=="Luis"
    linked=ProductService(db).crear_producto_externo("7500000001002","Producto",Decimal("20"),0,proveedor_principal_id=supplier.id)
    unlinked=ProductService(db).crear_producto_externo("7500000001003","Otro",Decimal("20"),0)
    assert ProductService(db).get(linked.id).proveedor_principal_id==supplier.id
    assert ProductService(db).get(unlinked.id).proveedor_principal_id is None
    service.desactivar(supplier.id);assert service.listar_activos()==[] and ProductService(db).get(linked.id).proveedor_principal_id==supplier.id
    assert service.reactivar(supplier.id).activo


def test_proveedor_nombre_obligatorio(db):
    with pytest.raises(ValueError,match="obligatorio"):SupplierService(db).crear("")


@pytest.mark.parametrize("kind,unit,minimum",[("UNIDAD",None,5),("GRANEL","PESO",1_000_000),("GRANEL","VOLUMEN",1_000_000)])
def test_stock_minimo_persiste_y_detecta_stock_bajo(db,kind,unit,minimum):
    kwargs={"tipo_venta":kind,"unidad_granel":unit,"stock_minimo":minimum if kind=="UNIDAD" else 0,"stock_minimo_granel_mg":minimum if kind=="GRANEL" else 0,"existencia_granel_mg":800_000 if kind=="GRANEL" else 0}
    product=ProductService(db).crear_producto_externo(f"7500000002{minimum}{len(unit or '')}","Mínimo",Decimal("10"),4 if kind=="UNIDAD" else 0,**kwargs)
    assert product.stock_bajo
    assert (product.stock_minimo if kind=="UNIDAD" else product.stock_minimo_granel_mg)==minimum


def test_sin_control_inventario_no_es_stock_bajo(db):
    product=ProductService(db).crear_producto_externo("7500000001004","Servicio",Decimal("10"),0,stock_minimo=10,controla_inventario=False)
    assert not product.stock_bajo


def test_precio_variable_y_politica_costo_por_edicion(db):
    general=ProductService(db,get_edition_config(Edition.GENERAL));product=general.crear_producto_externo("7500000001005","Variable",Decimal("100"),0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100",precio_variable=True)
    updated=general.actualizar_precio_proveedor(product.id,Decimal("60"));assert updated.precio_venta==10000 and updated.precio_variable
    ferreteria=ProductService(db,get_edition_config(Edition.FERRETERIA));updated=ferreteria.actualizar_precio_proveedor(product.id,Decimal("70"));assert updated.precio_venta==14000


def _modify(service,product,**changes):
    values={"descripcion":product.descripcion,"tipo_venta":product.tipo_venta,"unidad_granel":product.unidad_granel,"precio_catalogo_publico":None,"precio_proveedor":Decimal("50"),"porcentaje_ganancia":"100","precio_venta":None,"controla_inventario":product.controla_inventario,"activo":product.activo,"precio_variable":product.precio_variable}
    values.update(changes);return service.modificar_producto(product.id,**values)


def test_general_modificar_costo_sin_precio_conserva_venta(db):
    service=ProductService(db,get_edition_config(Edition.GENERAL));product=service.crear_producto_externo("7500000003001","General",Decimal("100"),0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100")
    assert _modify(service,product,precio_proveedor=Decimal("60")).precio_venta==10000


def test_general_cambiar_margen_no_cambia_precio(db):
    service=ProductService(db,get_edition_config(Edition.GENERAL));product=service.crear_producto_externo("7500000003002","General",Decimal("100"),0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100")
    updated=service.actualizar_porcentaje_ganancia(product.id,"150")
    assert updated.precio_venta==10000 and updated.porcentaje_ganancia=="150"


def test_general_modificar_margen_sin_precio_conserva_venta(db):
    service=ProductService(db,get_edition_config(Edition.GENERAL));product=service.crear_producto_externo("7500000003008","General",Decimal("100"),0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100")
    updated=_modify(service,product,porcentaje_ganancia="150")
    assert updated.precio_venta==10000 and updated.porcentaje_ganancia=="150"


def test_general_precio_explicito_si_cambia_venta(db):
    service=ProductService(db,get_edition_config(Edition.GENERAL));product=service.crear_producto_externo("7500000003003","General",Decimal("100"),0,precio_proveedor=Decimal("50"))
    assert _modify(service,product,precio_proveedor=Decimal("60"),precio_venta=Decimal("120")).precio_venta==12000


def test_general_alta_fija_exige_precio_explicito(db):
    service=ProductService(db,get_edition_config(Edition.GENERAL))
    with pytest.raises(ValueError,match="precio de venta es obligatorio"):
        service.crear_producto_externo("7500000003004","Sin precio",None,0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100")


def test_general_alta_variable_permite_precio_vacio(db):
    service=ProductService(db,get_edition_config(Edition.GENERAL));product=service.crear_producto_externo("7500000003005","Variable",None,0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100",precio_variable=True)
    assert product.precio_variable and product.precio_venta is None


def test_ferreteria_modificar_conserva_sugerencia_costo_margen(db):
    service=ProductService(db,get_edition_config(Edition.FERRETERIA));product=service.crear_producto_externo("7500000003006","Ferretería",Decimal("100"),0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100")
    assert _modify(service,product,precio_proveedor=Decimal("60"),porcentaje_ganancia="100").precio_venta==12000


def test_ferreteria_alta_conserva_precio_sugerido(db):
    service=ProductService(db,get_edition_config(Edition.FERRETERIA));product=service.crear_producto_externo("7500000003007","Sugerido",None,0,precio_proveedor=Decimal("50"),porcentaje_ganancia="100")
    assert product.precio_venta==10000
