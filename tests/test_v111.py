import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QDialog, QHeaderView, QMessageBox

from ferreteria_core import Database
from ferreteria_core.services import Cart, ProductQueryService, ProductService, SalesService
from ferreteria_gui.dialogs import ProductSearchDialog, QuickProductDialog
from ferreteria_gui.main_window import MainWindow
from ferreteria_gui.pages import InventoryPage, PosPage, ProductsPage


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    value = Database(tmp_path / "v111.db")
    value.migrate()
    return value


def external(db, barcode="7500000090001", description="Producto externo", stock=0):
    return ProductService(db).crear_producto_externo(barcode, description, Decimal("10"), stock)


def truper_row(db, code="17562", key="SIL-85T", description="Silicón", stock=3):
    with db.transaction() as connection:
        cursor = connection.execute(
            """INSERT INTO productos
               (codigo_truper,clave,descripcion,precio_venta,existencia,es_truper,datos_completos,
                requiere_revision,activo,tipo_venta,existencia_granel_mg,controla_inventario)
               VALUES (?,?,?,?,?,1,1,0,1,'UNIDAD',0,1)""",
            (code, key, description, 5100, stock),
        )
        product_id = cursor.lastrowid
    return ProductService(db).get(product_id)


def test_alta_rapida_truper_existente_recupera_y_actualiza(db):
    original = truper_row(db)
    service = ProductService(db)
    found = service.buscar_exacto("codigo_truper", "17562")
    assert (found.clave, found.descripcion, found.precio_venta, found.existencia) == ("SIL-85T", "Silicón", 5100, 3)
    saved = service.alta_rapida_truper_existente(original.id, "7501206683729", Decimal("55"), 8)
    assert (saved.codigo_barras, saved.precio_venta, saved.existencia) == ("7501206683729", 5500, 8)
    with db.connect() as connection:
        movement = connection.execute("SELECT * FROM movimientos_inventario WHERE producto_id=?", (original.id,)).fetchone()
        assert (movement["tipo"], movement["cantidad"], movement["nota"]) == ("AJUSTE", 5, "Alta/vinculación rápida")


def test_alta_truper_existente_descripcion_precio_stock_barcode_atomicos(db):
    original=truper_row(db);service=ProductService(db)
    saved=service.alta_rapida_truper_existente(original.id,"7500000080001",Decimal("58"),9,descripcion="Descripción corregida")
    assert (saved.descripcion,saved.precio_venta,saved.existencia,saved.codigo_barras)==("Descripción corregida",5800,9,"7500000080001")


def test_fallo_alta_no_deja_descripcion_precio_o_stock_parciales(db):
    owner=external(db,"7500000080001","Dueño");original=truper_row(db);service=ProductService(db)
    with pytest.raises(ValueError):service.alta_rapida_truper_existente(original.id,owner.codigo_barras,Decimal("99"),9,descripcion="No guardar")
    current=service.get(original.id);assert (current.descripcion,current.precio_venta,current.existencia,current.codigo_barras)==("Silicón",5100,3,None)


def test_descripcion_historica_no_cambia_con_alta(db):
    original=truper_row(db,stock=2);sale=SalesService(db).crear_venta([{"producto_id":original.id,"cantidad":1}],"TARJETA")
    ProductService(db).alta_rapida_truper_existente(original.id,"7500000080002",Decimal("60"),1,descripcion="Descripción nueva")
    assert SalesService(db).obtener_por_id(sale.id).detalles[0].descripcion_snapshot=="Silicón"


def test_alta_existente_sin_cambio_stock_no_crea_movimiento(db):
    product = truper_row(db, "10001", "UNO", "Uno", 4)
    ProductService(db).alta_rapida_truper_existente(product.id, "7500000091001", Decimal("10"), 4)
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM movimientos_inventario WHERE producto_id=?", (product.id,)).fetchone()[0] == 0


def test_alta_existente_no_revincula_sin_confirmacion(db):
    product = truper_row(db)
    service = ProductService(db)
    service.alta_rapida_truper_existente(product.id, "7500000091001", Decimal("10"), 3)
    with pytest.raises(ValueError, match="revinculación confirmada"):
        service.alta_rapida_truper_existente(product.id, "7500000091002", Decimal("10"), 3)
    assert service.get(product.id).codigo_barras == "7500000091001"


def test_alta_truper_granel_ajusta_en_miligramos(db):
    with db.transaction() as connection:
        product_id=connection.execute("""INSERT INTO productos (codigo_truper,descripcion,precio_venta,existencia,es_truper,datos_completos,requiere_revision,activo,tipo_venta,existencia_granel_mg,controla_inventario) VALUES ('G-1','Granel',10000,0,1,1,0,1,'GRANEL',500000,1)""").lastrowid
    product=ProductService(db).alta_rapida_truper_existente(product_id,"7500000091003",Decimal("110"),existencia_granel_mg=750000)
    assert product.existencia_granel_mg==750000
    with db.connect() as connection:
        movement=connection.execute("SELECT * FROM movimientos_inventario WHERE producto_id=?",(product_id,)).fetchone();assert (movement["cantidad_mg"],movement["nota"])==(250000,"Alta/vinculación rápida")


def test_creacion_minima_truper(db):
    product = ProductService(db).crear_producto_truper_minimo("99999", "7500000099999", Decimal("22.50"), 7)
    assert product.es_truper and not product.datos_completos and product.requiere_revision
    assert (product.codigo_truper, product.codigo_barras, product.descripcion, product.precio_venta, product.existencia) == ("99999", "7500000099999", None, 2250, 7)


def test_nuevo_manual_externo_permite_sin_barcode(db):
    product=ProductService(db).crear_producto_externo("","Producto suelto",Decimal("3"),5,permitir_sin_barcode=True)
    assert product.codigo_barras is None and not product.es_truper


def test_creacion_minima_duplicados(db):
    ProductService(db).crear_producto_truper_minimo("99999", "7500000099999", Decimal("1"))
    with pytest.raises(ValueError, match="código Truper"):
        ProductService(db).crear_producto_truper_minimo("99999", "7500000099998", Decimal("1"))
    with pytest.raises(ValueError, match="barras"):
        ProductService(db).crear_producto_truper_minimo("99998", "7500000099999", Decimal("1"))


def test_alta_cancelada_no_modifica(app, db):
    before = ProductQueryService(db).contar_productos()
    dialog = QuickProductDialog(db, "7500000012345")
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert ProductQueryService(db).contar_productos() == before


def test_dialogo_truper_existente_precarga_descripcion_editable(app,db):
    truper_row(db);dialog=QuickProductDialog(db,"7500000080003");dialog.code.setText("17562");dialog._lookup()
    assert dialog.description.text()=="Silicón" and not dialog.description.isReadOnly()


def test_revincular_barcode_y_preservar_snapshot(db):
    product = external(db, stock=1)
    sale = SalesService(db).crear_venta([{"producto_id": product.id, "cantidad": 1}], "TARJETA")
    updated = ProductService(db).revincular_codigo_barras(product.id, "7500000090002")
    historical = SalesService(db).obtener_por_id(sale.id)
    assert updated.codigo_barras == "7500000090002"
    assert historical.detalles[0].codigo_barras_snapshot == "7500000090001"


def test_revincular_barcode_duplicado_muestra_propietario(db):
    first = external(db, "7500000090001", "Primero")
    second = external(db, "7500000090002", "Segundo")
    with pytest.raises(ValueError, match="Primero"):
        ProductService(db).revincular_codigo_barras(second.id, first.codigo_barras)


def test_cambiar_codigo_truper_y_preservar_snapshot(db):
    product = truper_row(db)
    sale = SalesService(db).crear_venta([{"producto_id": product.id, "cantidad": 1}], "TARJETA")
    updated = ProductService(db).cambiar_codigo_truper(product.id, "17563")
    assert updated.codigo_truper == "17563"
    assert SalesService(db).obtener_por_id(sale.id).detalles[0].codigo_truper_snapshot == "17562"


def test_cambiar_codigo_truper_duplicado(db):
    first = truper_row(db, "10001", "A", "Primero")
    second = truper_row(db, "10002", "B", "Segundo")
    with pytest.raises(ValueError, match="Primero"):
        ProductService(db).cambiar_codigo_truper(second.id, first.codigo_truper)


def test_producto_sin_historial_se_elimina(db):
    product = external(db)
    state = ProductService(db).estado_eliminacion(product.id)
    assert state["puede_eliminar"]
    assert ProductService(db).eliminar_o_desactivar(product.id)["accion"] == "ELIMINADO"
    assert ProductService(db).get(product.id) is None


def test_producto_con_movimiento_se_desactiva_y_reactiva(db):
    product = external(db, stock=2)
    service = ProductService(db)
    assert not service.estado_eliminacion(product.id)["puede_eliminar"]
    assert service.eliminar_o_desactivar(product.id)["accion"] == "DESACTIVADO"
    assert not service.get(product.id).activo
    assert service.buscar_exacto("codigo_barras", product.codigo_barras) is None
    assert service.reactivar_producto(product.id).activo


def test_producto_con_venta_no_se_borra(db):
    product = external(db, stock=1)
    SalesService(db).crear_venta([{"producto_id": product.id, "cantidad": 1}], "TARJETA")
    result = ProductService(db).eliminar_o_desactivar(product.id)
    assert result["accion"] == "DESACTIVADO" and ProductService(db).get(product.id) is not None


@pytest.mark.parametrize("term", ["7500000090001", "17562", "SIL-85T", "silic"])
def test_busqueda_pos_sin_barcode_por_prioridades(db, term):
    product = truper_row(db)
    ProductService(db).revincular_codigo_barras(product.id, "7500000090001")
    result = ProductQueryService(db).buscar_inteligente(term)
    assert result.products[0].id == product.id


def test_inactivo_excluido_de_busqueda_y_carrito(db):
    product = external(db)
    ProductService(db).eliminar_o_desactivar(product.id)
    assert not ProductQueryService(db).buscar_inteligente("Producto externo").products
    with pytest.raises(LookupError):
        Cart(db).agregar_por_barcode(product.codigo_barras)


def test_productos_enter_barcode_existente_selecciona(app, db):
    product = external(db)
    page = ProductsPage(db);page.show();app.processEvents();page.query.setText(product.codigo_barras);QTest.keyClick(page.query, Qt.Key_Return);app.processEvents()
    assert page.selected_product().id == product.id
    page.close()


def test_inventario_nuevo_reutiliza_dialogo(app, db, monkeypatch):
    called = []
    monkeypatch.setattr("ferreteria_gui.pages.QuickProductDialog.exec", lambda self: called.append(self.__class__.__name__) or QDialog.DialogCode.Rejected)
    page = InventoryPage(db);page._new()
    assert called == ["QuickProductDialog"]


def test_pos_busqueda_codigo_agrega_unidad(app, db):
    product = truper_row(db)
    page = PosPage(db);page.barcode.setText(product.codigo_truper);page._scan()
    assert page.cart.items[0].producto_id == product.id


def _search_products(db):
    service=ProductService(db)
    return [service.crear_producto_externo(f"75000000700{i:02d}",f"Cinta con descripción completa número {i}",Decimal(str(10+i)),5) for i in range(3)]


def test_selector_amplio_columnas_tooltip_y_redimensionable(app,db):
    _search_products(db);dialog=ProductSearchDialog(db,"cinta");dialog.show();app.processEvents()
    assert dialog.width()>=1000 and dialog.table.columnWidth(2)>=400
    assert dialog.table.horizontalHeader().sectionResizeMode(2)==QHeaderView.Interactive
    assert dialog.table.item(0,2).toolTip()==dialog.table.item(0,2).text()


def test_selector_multiple_agrega_dos_sin_lineas_duplicadas(app,db):
    products=_search_products(db);dialog=ProductSearchDialog(db,"cinta");selection=dialog.table.selectionModel();dialog.table.clearSelection()
    for row in (0,1):selection.select(dialog.table.model().index(row,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
    dialog._choose();assert len(dialog.selected_products)==2
    page=PosPage(db);page._add_products(dialog.selected_products);page._add_products(dialog.selected_products)
    assert len(page.cart.items)==2 and sorted(item.cantidad for item in page.cart.items)==[2,2]


def test_selector_doble_clic_agrega_solo_fila_objetivo(app,db):
    _search_products(db);dialog=ProductSearchDialog(db,"cinta");dialog.table.selectAll();dialog._choose_single(dialog.table.model().index(1,2))
    assert len(dialog.selected_products)==1 and dialog.selected_products[0].descripcion.endswith("1")


def test_selector_granel_cancelado_omite_solo_granel(app,db,monkeypatch):
    units=_search_products(db)[:2];bulk=ProductService(db).crear_producto_externo("7500000070099","Cinta a granel",Decimal("30"),0,tipo_venta="GRANEL",controla_inventario=False)
    monkeypatch.setattr("ferreteria_gui.pages.BulkSaleDialog.exec",lambda self:QDialog.DialogCode.Rejected)
    page=PosPage(db);page._add_products([units[0],bulk,units[1]])
    assert {item.producto_id for item in page.cart.items}=={units[0].id,units[1].id}


def test_autofocus_contextual_al_navegar(app,db):
    window=MainWindow(db);window.show();app.processEvents()
    for index,target in ((0,window.pos.barcode),(1,window.products.query),(2,window.inventory.query)):
        window.nav.setCurrentRow(index);app.processEvents();assert window.focusWidget() is target
    window.close()


def test_atajos_contextuales_no_se_disparan_dos_veces(app, db, monkeypatch):
    window = MainWindow(db);window.show();app.processEvents();window.nav.setCurrentRow(1);calls=[]
    monkeypatch.setattr(window.products, "_new", lambda: calls.append("new"))
    QTest.keyClick(window, Qt.Key_F1);app.processEvents()
    assert calls == ["new"]
    window.close()


def test_f7_granel_abre_dialogo_no_suma_un_kg(app, db, monkeypatch):
    product = ProductService(db).crear_producto_externo("7500000090001", "Granel", Decimal("100"), 0, tipo_venta="GRANEL", controla_inventario=False)
    page = PosPage(db);page.cart.agregar_granel(product.id, 100_000);page.refresh();page.table.selectRow(0);called=[]
    monkeypatch.setattr("ferreteria_gui.pages.BulkSaleDialog.exec", lambda self: called.append(True) or QDialog.DialogCode.Rejected)
    page._change(1)
    assert called and page.cart.items[0].cantidad_mg == 100_000
