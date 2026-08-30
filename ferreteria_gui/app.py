import sys
import os
from PySide6.QtCore import QEvent,QObject,QTimer,Qt

from PySide6.QtWidgets import QApplication, QMessageBox,QPushButton

from ferreteria_core import Database
from ferreteria_core.services import BackupService
from ferreteria_core.services import seed_general_categories,seed_general_purchase_presentations
from edition import EDITION,Edition
from .config import APP_NAME, BACKUP_ROOT, DATABASE_PATH
from .logging_setup import configure_logging
from .main_window import MainWindow
from .widgets import STYLE
from ferreteria_core.version import __version__


def run(db_path=DATABASE_PATH):
    logger=configure_logging(); app=QApplication.instance() or QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setStyleSheet(STYLE)
    try:
        database=Database(db_path)
        if database.needs_migration():BackupService(database,BACKUP_ROOT).crear_pre_migracion()
        database.migrate()
        if EDITION.edition is Edition.GENERAL:seed_general_categories(database);seed_general_purchase_presentations(database)
        app._keyboard_filter=KeyboardActivationFilter(app);app.installEventFilter(app._keyboard_filter);window=MainWindow(database,BACKUP_ROOT); window.show()
        if os.environ.get("PUNTO_VENTA_SMOKE_TEST")=="1":
            app.setQuitOnLastWindowClosed(False);QTimer.singleShot(800,lambda:_smoke_close(window,app,logger))
        return app.exec()
    except Exception as exc:
        logger.exception("No se pudo iniciar la aplicación")
        QMessageBox.critical(None,"No se pudo abrir el POS",str(exc)); return 1


class KeyboardActivationFilter(QObject):
    def eventFilter(self,obj,event):
        if isinstance(obj,QPushButton) and event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Return,Qt.Key_Enter):
            obj.click();return True
        return super().eventFilter(obj,event)


def _smoke_close(window,app,logger):
    exit_code=0
    try:
        for index in range(window.stack.count()):window.nav.setCurrentRow(index);app.processEvents()
        if window.products.table.rowCount()==0 or window.inventory.table.rowCount()==0:raise RuntimeError("Productos o inventario no muestran datos")
        if window.history.table.rowCount()==0:raise RuntimeError("El historial no muestra ventas existentes")
        if not window.business_name.text().strip():raise RuntimeError("El nombre del negocio está vacío")
        product_headers=[window.products.table.horizontalHeaderItem(i).text() for i in range(window.products.table.columnCount())]
        inventory_headers=[window.inventory.table.horizontalHeaderItem(i).text() for i in range(window.inventory.table.columnCount())]
        expected_headers={"Precio proveedor","Ganancia %"} if EDITION.edition is Edition.FERRETERIA else {"Categoría","Costo","Stock mínimo"}
        if __version__!="1.1.4" or not expected_headers<=set(product_headers):raise RuntimeError("La GUI no corresponde a la edición/version esperada")
        if not window.history.summary_title.text() or window.pos.set_quantity_button.text().find("F10")<0:raise RuntimeError("Faltan funciones esenciales del POS")
        if "Precio venta" not in inventory_headers:raise RuntimeError("Existencias no muestra precio de venta")
        window.nav.setCurrentRow(0);window.pos.focus_scanner();app.processEvents()
        if window.focusWidget() is not window.pos.barcode:raise RuntimeError("El campo del scanner no quedó como widget de foco")
        logger.info("Smoke test GUI correcto: %s pantallas, datos reales visibles y scanner enfocado",window.stack.count())
    except Exception:
        exit_code=2;logger.exception("Falló el smoke test GUI")
    finally:
        window.close();app.exit(exit_code)
