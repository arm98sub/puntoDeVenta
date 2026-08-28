import os
import tempfile
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

os.environ["QT_QPA_PLATFORM"]="offscreen"

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from ferreteria_core import Database
from ferreteria_core.services import ProductService
from ferreteria_gui.dialogs import BulkSaleDialog,ProductModifyDialog
from ferreteria_gui.pages import InventoryPage,PosPage,ProductsPage


def main():
    app=QApplication.instance() or QApplication([]);output=Path("tmp/v11_visual");output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        database=Database(Path(folder)/"visual.db");database.migrate();service=ProductService(database)
        bulk=service.crear_producto_externo("7500000090001",'Clavo 2"',Decimal("80"),0,clave="CLA-2",tipo_venta="GRANEL",existencia_granel_mg=3_450_000)
        unit=service.crear_producto_externo("7500000090002","Martillo",Decimal("185"),10,clave="MAR-1")
        products=ProductsPage(database);products.resize(1280,760);products.show();app.processEvents();products.grab().save(str(output/"productos_bloqueado.png"))
        selection=products.table.selectionModel();selection.select(products.table.model().index(0,0),QItemSelectionModel.Select|QItemSelectionModel.Rows);selection.select(products.table.model().index(1,0),QItemSelectionModel.Select|QItemSelectionModel.Rows);app.processEvents();products.grab().save(str(output/"productos_edicion_multiple.png"))
        inventory=InventoryPage(database);inventory.resize(1100,700);inventory.show();app.processEvents();inventory.grab().save(str(output/"existencias.png"))
        pos=PosPage(database);pos.cart.agregar_granel(bulk.id,38_000);pos.cart.agregar_producto(unit.id,2);pos.refresh();pos.resize(1100,700);pos.show();app.processEvents();pos.grab().save(str(output/"carrito_mixto.png"))
        dialog=BulkSaleDialog(bulk);dialog.quantity.setText("0.0625");dialog._from_quantity();dialog.show();app.processEvents();dialog.grab().save(str(output/"dialogo_granel.png"))
        modify=ProductModifyDialog(bulk,service);modify.show();app.processEvents();modify.grab().save(str(output/"modificar_producto.png"))
        assert len(products.selected_products())==2
        assert inventory.table.rowCount()==2 and pos.table.rowCount()==2 and dialog.amount.text()=="5.00"
        for widget in (modify,dialog,pos,inventory,products):widget.close();widget.deleteLater()
        app.processEvents()
        print(f"OK {output.resolve()} 6 capturas; base temporal eliminada")


if __name__=="__main__":main()
