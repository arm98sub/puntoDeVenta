from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from ferreteria_core.services import BusinessConfigService
from .config import APP_NAME,PURCHASES_ENABLED,visible_business_name
from .pages import HistoryPage, InventoryPage, PosPage, ProductsPage
from .settings_page import SettingsPage
from .purchases_page import PurchasesPage
from ferreteria_core.services import BackupService
import logging


class MainWindow(QMainWindow):
    def __init__(self,database,backup_root=None):
        super().__init__(); self.setWindowTitle(APP_NAME); self.resize(1280,780); self.setMinimumSize(1000,650)
        self.database=database;backup_root=backup_root or database.path.parent/"backups";self.backups=BackupService(database,backup_root);central=QWidget(); outer=QVBoxLayout(central);outer.setContentsMargins(0,0,0,0);header=QHBoxLayout();self.logo=QLabel();self.logo.setFixedSize(90,55);self.logo.setAlignment(Qt.AlignCenter);self.business_name=QLabel();self.business_name.setObjectName("businessName");header.addWidget(self.logo);header.addWidget(self.business_name);header.addStretch();outer.addLayout(header);root=QHBoxLayout(); self.nav=QListWidget(); self.nav.setFixedWidth(210); self.nav.addItems(["Punto de venta","Productos","Inventario","Historial de ventas","Configuración"])
        self.nav.clear();self.stack=QStackedWidget(); self.pos=PosPage(database);self.products=ProductsPage(database);self.inventory=InventoryPage(database);self.purchases=PurchasesPage(database) if PURCHASES_ENABLED else None;self.history=HistoryPage(database);self.settings=SettingsPage(database,backup_root);pages=[("Punto de venta",self.pos),("Productos y precios",self.products),("Existencias y movimientos",self.inventory)]
        if self.purchases:pages.append(("Compras",self.purchases))
        pages.extend([("Historial de ventas",self.history),("Configuración",self.settings)]);self.nav.addItems([label for label,_page in pages]);[self.stack.addWidget(page) for _label,page in pages];root.addWidget(self.nav);root.addWidget(self.stack,1);outer.addLayout(root,1);self.setCentralWidget(central);self.settings.settings_saved.connect(self._apply_settings);self.settings.restored.connect(self._refresh_all);self._apply_settings(BusinessConfigService(database).obtener())
        self._current_index=0;self.nav.currentRowChanged.connect(self._navigate); self.nav.setCurrentRow(0)
        QShortcut(QKeySequence("F1"),self,activated=self._new_product);QShortcut(QKeySequence("F2"),self,activated=self._focus_context);QShortcut(QKeySequence("F3"),self,activated=self._modify_product);QShortcut(QKeySequence("F4"),self,activated=self._charge);QShortcut(QKeySequence("F5"),self,activated=self._refresh);QShortcut(QKeySequence("F6"),self,activated=self._delete_product);QShortcut(QKeySequence("F7"),self,activated=lambda:self._cart_change(1));QShortcut(QKeySequence("F8"),self,activated=lambda:self._cart_change(-1));QShortcut(QKeySequence("F9"),self,activated=self._delete);QShortcut(QKeySequence("Delete"),self,activated=self._delete);QShortcut(QKeySequence("F10"),self,activated=self._set_cart_quantity);QShortcut(QKeySequence("Ctrl+Delete"),self,activated=self._cancel_cart);QShortcut(QKeySequence("Ctrl+F"),self,activated=self._focus_context)
    def _navigate(self,index):
        self._current_index=index
        self.stack.setCurrentIndex(index)
        page=self.stack.currentWidget()
        if page is self.pos:QTimer.singleShot(0,self.pos.focus_scanner)
        elif page in (self.products,self.inventory):page.reload();page.focus_search_deferred()
        elif page in (self.history,self.purchases) and page is not None:page.refresh()
        elif page is self.settings:page.load()
    def _focus_scanner(self):self.nav.setCurrentRow(0); self.pos.focus_scanner()
    def _focus_context(self):
        page=self.stack.currentWidget();target=self.pos.barcode if page is self.pos else getattr(page,"query",None)
        if target:target.setFocus();target.selectAll()
    def _new_product(self):
        page=self.stack.currentWidget()
        if page in (self.products,self.inventory):page._new()
    def _modify_product(self):
        if self.stack.currentWidget() is self.products:self.products._modify()
    def _delete_product(self):
        if self.stack.currentWidget() is self.products:self.products._delete_product()
    def _cart_change(self,delta):
        if self.stack.currentWidget() is self.pos:self.pos._change(delta)
    def _charge(self):
        if self.stack.currentIndex()==0:self.pos.checkout()
    def _delete(self):
        if self.stack.currentIndex()==0:self.pos.remove_selected()
    def _set_cart_quantity(self):
        if self.stack.currentIndex()==0:self.pos.set_selected_quantity()
    def _cancel_cart(self):
        if self.stack.currentIndex()==0:self.pos.cancel_cart()
    def _focus_search(self):
        self._focus_context()
    def _refresh(self):
        page=self.stack.currentWidget()
        if hasattr(page,"reload"):page.reload()
        elif hasattr(page,"refresh"):page.refresh()
    def _apply_settings(self,settings):
        self.business_name.setText(visible_business_name(settings.nombre_negocio))
        if settings.logo_path and Path(settings.logo_path).exists():self.logo.setPixmap(QPixmap(settings.logo_path).scaled(self.logo.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:self.logo.clear()
    def _refresh_all(self):
        self.products.page=1;self.products.reload();self.inventory.page=1;self.inventory.reload();self.history.refresh();
        if self.purchases:self.purchases.refresh()
        self._apply_settings(BusinessConfigService(self.database).obtener());self.nav.setCurrentRow(0)
    def closeEvent(self,event):
        try:self.backups.crear_automatico()
        except Exception:logging.getLogger("ferreteria_gui").exception("No se pudo crear el respaldo automático al cerrar")
        super().closeEvent(event)
