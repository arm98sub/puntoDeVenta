import json
from decimal import Decimal

import pytest

from edition import Edition,get_edition_config
from ferreteria_core import Database
from ferreteria_core.services import (BackupService,BusinessConfigService,ProductService,PurchasePresentationService,
    PurchaseService,SalesService,seed_general_categories,seed_general_purchase_presentations)
from updater_core import load_package


def test_versiones_independientes_por_edicion():
    assert get_edition_config(Edition.FERRETERIA).version=="1.1.4"
    assert get_edition_config(Edition.GENERAL).version=="0.9.0"


def test_general_arranca_limpio_en_schema_10_y_crea_seeds(tmp_path):
    database=Database(tmp_path/"clean"/"data"/"punto_venta.db");database.migrate();seed_general_categories(database);seed_general_purchase_presentations(database)
    with database.connect() as connection:
        assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]==10
        assert connection.execute("SELECT count(*) FROM categorias").fetchone()[0]>0
        assert {row[0] for row in connection.execute("SELECT nombre FROM presentaciones_compra")}=={"Pieza","Caja","Paquete","Display"}


def test_backup_restore_general_recupera_operacion_completa(tmp_path):
    database=Database(tmp_path/"punto_venta.db");database.migrate();seed_general_categories(database);seed_general_purchase_presentations(database);config=get_edition_config(Edition.GENERAL)
    product=ProductService(database,config).crear_producto_externo("7500000400001","Piloto",Decimal("25"),10,precio_proveedor=Decimal("10"));piece=next(item for item in PurchasePresentationService(database).listar_activas() if item.nombre=="Pieza")
    purchase=PurchaseService(database).confirmar([PurchaseService(database).crear_linea(product.id,piece.id,5,1,Decimal("10"))]);sale=SalesService(database).crear_venta([{"producto_id":product.id,"cantidad":2}],"TARJETA");BusinessConfigService(database).guardar(nombre_negocio="Tienda piloto")
    backup_service=BackupService(database,tmp_path/"backups");backup=backup_service.crear_manual()
    ProductService(database,config).modificar_producto(product.id,descripcion="Alterado",tipo_venta="UNIDAD",precio_venta=Decimal("99"));SalesService(database).cancelar_venta(sale.id,"alteración")
    backup_service.restaurar(backup);restored=ProductService(database,config).get(product.id)
    assert restored.descripcion=="Piloto" and restored.precio_venta==2500 and restored.existencia==13
    assert PurchaseService(database).obtener(purchase.id).estado=="CONFIRMADA" and SalesService(database).obtener_por_id(sale.id).estado=="COMPLETADA"
    assert BusinessConfigService(database).obtener().nombre_negocio=="Tienda piloto"


@pytest.mark.parametrize("name",["datos.sqlite","datos.SQLITE","datos.sqlite3","datos.SQLITE3"])
def test_updater_rechaza_todas_las_extensiones_sqlite(tmp_path,name):
    root=tmp_path/"package";payload=root/"payload";internal=payload/"_internal";internal.mkdir(parents=True);(payload/"PuntoDeVenta.exe").write_bytes(b"exe");(payload/name).write_bytes(b"db")
    (root/"version.json").write_text(json.dumps({"version":"0.9.0","edition":"GENERAL","required_schema_min":10,"target_schema":10}),encoding="utf-8")
    with pytest.raises(ValueError,match="base de datos"):load_package(root)
