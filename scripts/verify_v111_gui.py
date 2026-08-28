"""Capturas offscreen de v1.1.1; sólo crea una base SQLite temporal."""
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from ferreteria_core import Database
from ferreteria_core.services import ProductService
from ferreteria_gui.dialogs import ProductSearchDialog, QuickProductDialog
from ferreteria_gui.main_window import MainWindow


def main(output="tmp/v111_visual"):
    target = Path(output);target.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="pos-v111-") as directory:
        database = Database(Path(directory) / "visual.db");database.migrate()
        service = ProductService(database)
        service.crear_producto_truper_minimo("17562", "7501206683729", Decimal("51"), 10,
                                             descripcion="Silicón transparente", clave="SIL-85T")
        service.crear_producto_externo("7500000012345", "Clavo para concreto con una descripción larga para verificar que el selector muestre el texto completo", Decimal("2.50"), 100)
        service.crear_producto_externo("7500000012346", "Clavo galvanizado para madera en presentación de uso profesional", Decimal("3.50"), 80)
        service.crear_producto_externo("7500000012347", "Clavo de acero reforzado para aplicaciones especiales", Decimal("4.50"), 60)
        window = MainWindow(database);window.show();app.processEvents()
        window.nav.setCurrentRow(1);app.processEvents();window.grab().save(str(target / "productos.png"))
        window.products.table.editItem(window.products.table.item(0,3));app.processEvents();window.grab().save(str(target / "edicion_directa.png"))
        quick = QuickProductDialog(database, "7509999999999", window);quick.code.setText("17562");quick._lookup();quick.show();app.processEvents();quick.grab().save(str(target / "alta_truper_existente.png"));quick.close()
        new = QuickProductDialog(database, "7508888888888", window);new.code.setText("99999");new._lookup();new.show();app.processEvents();new.grab().save(str(target / "alta_truper_nuevo.png"));new.close()
        window.nav.setCurrentRow(0);selector=ProductSearchDialog(database,"clavo",window);selector.show();selector.table.selectAll();app.processEvents();window.grab().save(str(target / "punto_venta.png"));selector.grab().save(str(target / "resultados_venta.png"));selector.close();window.close()
    print(f"Capturas v1.1.1: {target.resolve()}")


if __name__ == "__main__":main()
