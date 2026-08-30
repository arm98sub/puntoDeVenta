from pathlib import Path

from PySide6.QtCore import Qt,Signal,QUrl
from PySide6.QtGui import QDesktopServices,QPixmap
from PySide6.QtWidgets import QCheckBox,QFileDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QScrollArea,QVBoxLayout,QWidget,QDialog,QComboBox,QInputDialog

from ferreteria_core.services import BackupService,BusinessConfigService,CategoryService,PurchasePresentationService,SupplierService,ThermalPrintSettings,validar_respaldo
from edition import EDITION,Edition
from ferreteria_core.version import __version__
from .config import BACKUP_ROOT,BRANDING_DIR,PRINTING_CONFIG_PATH,visible_business_name
from .thermal_printing import ThermalPrinterService
from .widgets import show_error


class SettingsPage(QWidget):
    settings_saved=Signal(object)
    restored=Signal()
    def __init__(self,database,backup_root=BACKUP_ROOT,parent=None):
        super().__init__(parent);self.service=BusinessConfigService(database,BRANDING_DIR);self.backups=BackupService(database,backup_root);self.logo_source=None
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.NoFrame);content=QWidget();scroll.setWidget(content);outer.addWidget(scroll);root=QVBoxLayout(content);title=QLabel("CONFIGURACIÓN");title.setObjectName("pageTitle");root.addWidget(title);form=QFormLayout();self.name=QLineEdit();self.address=QLineEdit();self.phone=QLineEdit();self.rfc=QLineEdit();self.message=QLineEdit();self.currency=QLineEdit("MXN");self.currency.setReadOnly(True)
        for label,widget in (("Nombre del negocio",self.name),("Dirección",self.address),("Teléfono",self.phone),("RFC (opcional)",self.rfc),("Mensaje del ticket",self.message),("Moneda",self.currency)):form.addRow(label,widget)
        root.addLayout(form);logo_row=QHBoxLayout();self.preview=QLabel("Sin logo");self.preview.setFixedSize(220,100);self.preview.setAlignment(Qt.AlignCenter);self.preview.setStyleSheet("border:1px solid #aeb8c2;background:white");choose=QPushButton("Seleccionar logo");logo_row.addWidget(self.preview);logo_row.addWidget(choose);logo_row.addStretch();root.addLayout(logo_row);save=QPushButton("GUARDAR CONFIGURACIÓN");save.setObjectName("primary");root.addWidget(save,alignment=Qt.AlignLeft)
        self.thermal=None
        if EDITION.edition is Edition.GENERAL:
            catalogs=QHBoxLayout();categories=QPushButton("Administrar categorías");suppliers=QPushButton("Administrar proveedores");catalogs.addWidget(categories);catalogs.addWidget(suppliers);catalogs.addStretch();root.addLayout(catalogs);categories.clicked.connect(lambda:CatalogManagerDialog(database,"category",self).exec());suppliers.clicked.connect(lambda:CatalogManagerDialog(database,"supplier",self).exec());self._build_printing(root,database)
        backup_title=QLabel("RESPALDOS");backup_title.setObjectName("pageTitle");root.addWidget(backup_title);backup_row=QHBoxLayout();manual=QPushButton("Crear respaldo ahora");restore=QPushButton("Restaurar respaldo");open_folder=QPushButton("Abrir carpeta de respaldos");backup_row.addWidget(manual);backup_row.addWidget(restore);backup_row.addWidget(open_folder);backup_row.addStretch();root.addLayout(backup_row)
        self.about_title=None;self.about_details=None
        if EDITION.edition is Edition.GENERAL:
            self.about_title=QLabel("ACERCA DE");self.about_title.setObjectName("pageTitle");root.addWidget(self.about_title);self.about_details=QLabel(f"{EDITION.app_name}\nVersión {__version__} — Piloto\nDesarrollado por: {EDITION.author}\n© 2026");self.about_details.setObjectName("aboutDetails");self.about_details.setStyleSheet("color:#374151");root.addWidget(self.about_details)
        else:root.addWidget(QLabel(f"Versión {__version__}"))
        root.addStretch();choose.clicked.connect(self._choose);save.clicked.connect(self.save);manual.clicked.connect(self._manual_backup);restore.clicked.connect(self._restore);open_folder.clicked.connect(self._open_backups);self.load()
    def _build_printing(self,root,database):
        self.thermal=ThermalPrinterService(database,PRINTING_CONFIG_PATH);title=QLabel("IMPRESORA Y CAJÓN");title.setObjectName("pageTitle");root.addWidget(title);form=QFormLayout();self.printer=QComboBox();self.printer.addItem("Seleccione una impresora...","")
        for name in self.thermal.available_printers():self.printer.addItem(name,name)
        self.paper=QComboBox();self.paper.addItem("58 mm",58);self.auto_print=QCheckBox("Imprimir ticket automáticamente al realizar una venta");self.auto_drawer=QCheckBox("Abrir cajón automáticamente en ventas en efectivo");form.addRow("Impresora:",self.printer);form.addRow("Ancho de papel:",self.paper);form.addRow(self.auto_print);form.addRow(self.auto_drawer);root.addLayout(form)
        row=QHBoxLayout();test=QPushButton("IMPRIMIR PRUEBA");drawer=QPushButton("ABRIR CAJÓN");row.addWidget(test);row.addWidget(drawer);row.addStretch();root.addLayout(row);test.clicked.connect(self._print_test);drawer.clicked.connect(self._open_drawer);self._load_printing()
    def _load_printing(self):
        if not self.thermal:return
        settings=self.thermal.settings.load();index=self.printer.findData(settings.printer_name)
        if settings.printer_name and index<0:self.printer.addItem(settings.printer_name+" (no disponible)",settings.printer_name);index=self.printer.count()-1
        self.printer.setCurrentIndex(max(0,index));self.paper.setCurrentIndex(max(0,self.paper.findData(settings.paper_width_mm)));self.auto_print.setChecked(settings.auto_print);self.auto_drawer.setChecked(settings.auto_open_drawer)
    def _save_printing(self):
        if not self.thermal:return
        previous=self.thermal.settings.load();self.thermal.settings.save(ThermalPrintSettings(self.printer.currentData() or "",self.paper.currentData(),self.auto_print.isChecked(),self.auto_drawer.isChecked(),previous.drawer_channel,previous.drawer_pulse_on_ms,previous.drawer_pulse_off_ms))
    def _print_test(self):
        try:self._save_printing();self.thermal.print_test();QMessageBox.information(self,"Impresión enviada","El ticket de prueba fue enviado a la impresora.")
        except Exception as exc:show_error(self,"No se pudo imprimir",exc)
    def _open_drawer(self):
        try:self._save_printing();self.thermal.open_drawer();QMessageBox.information(self,"Comando enviado","Se envió el comando de apertura del cajón.")
        except Exception as exc:show_error(self,"No se pudo abrir el cajón",exc)
    def load(self):
        settings=self.service.obtener();self.name.setText(visible_business_name(settings.nombre_negocio));self.address.setText(settings.direccion or "");self.phone.setText(settings.telefono or "");self.rfc.setText(settings.rfc or "");self.message.setText(settings.mensaje_ticket or "");self._show_logo(settings.logo_path)
    def _choose(self):
        path,_=QFileDialog.getOpenFileName(self,"Seleccionar logo","","Imágenes (*.png *.jpg *.jpeg)")
        if path:self.logo_source=path;self._show_logo(path)
    def _show_logo(self,path):
        if path and Path(path).exists():self.preview.setPixmap(QPixmap(path).scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:self.preview.setPixmap(QPixmap());self.preview.setText("Sin logo")
    def save(self):
        try:
            settings=self.service.guardar(nombre_negocio=self.name.text(),direccion=self.address.text(),telefono=self.phone.text(),rfc=self.rfc.text(),mensaje_ticket=self.message.text(),logo_origen=self.logo_source);self._save_printing();self.logo_source=None;self._show_logo(settings.logo_path);self.settings_saved.emit(settings)
        except Exception as exc:show_error(self,"No se pudo guardar la configuración",exc)
    def _manual_backup(self):
        try:path=self.backups.crear_manual();QMessageBox.information(self,"Respaldo creado",f"Respaldo creado correctamente:\n{path}")
        except Exception as exc:show_error(self,"No se pudo crear el respaldo",exc)
    def _restore(self):
        path,_=QFileDialog.getOpenFileName(self,"Seleccionar respaldo",str(self.backups.root),"Bases SQLite (*.db)")
        if not path:return
        try:
            validar_respaldo(path)
            if QMessageBox.warning(self,"Confirmar restauración","Restaurar este respaldo reemplazará los datos actuales.\nAntes se creará un respaldo de seguridad.",QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Yes:return
            safety=self.backups.restaurar(path);self.load();self.settings_saved.emit(self.service.obtener());self.restored.emit();QMessageBox.information(self,"Restauración completada",f"Datos restaurados correctamente.\nRespaldo previo: {safety}")
        except Exception as exc:show_error(self,"No se pudo restaurar",exc)
    def _open_backups(self):
        self.backups.root.mkdir(parents=True,exist_ok=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backups.root.resolve())))


class CatalogManagerDialog(QDialog):
    def __init__(self,database,kind,parent=None):
        super().__init__(parent);self.kind=kind;self.service=CategoryService(database) if kind=="category" else (PurchasePresentationService(database) if kind=="presentation" else SupplierService(database));self.setWindowTitle({"category":"Categorías","supplier":"Proveedores","presentation":"Presentaciones"}[kind]);layout=QVBoxLayout(self);self.items=QComboBox();layout.addWidget(self.items);row=QHBoxLayout();create=QPushButton("Crear");rename=QPushButton("Renombrar");toggle=QPushButton("Activar / desactivar");close=QPushButton("Cerrar")
        for button in (create,rename,toggle,close):row.addWidget(button)
        layout.addLayout(row);create.clicked.connect(self._create);rename.clicked.connect(self._rename);toggle.clicked.connect(self._toggle);close.clicked.connect(self.accept);self._load()
    def _all(self):return self.service.listar_todas()
    def _load(self,selected=None):
        self.items.clear()
        for item in self._all():self.items.addItem(item.nombre+(" (inactivo)" if not item.activo else ""),item.id)
        if selected:self.items.setCurrentIndex(max(0,self.items.findData(selected)))
    def _create(self):
        name,ok=QInputDialog.getText(self,"Crear","Nombre:")
        if not ok:return
        try:item=self.service.crear(name);self._load(item.id)
        except Exception as exc:QMessageBox.warning(self,"No se creó",str(exc))
    def _rename(self):
        item=self.service.obtener(self.items.currentData())
        if not item:return
        name,ok=QInputDialog.getText(self,"Renombrar","Nombre:",text=item.nombre)
        if not ok:return
        try:
            if self.kind=="supplier":self.service.editar(item.id,name,item.telefono,item.contacto,item.notas)
            else:self.service.editar(item.id,name)
            self._load(item.id)
        except Exception as exc:QMessageBox.warning(self,"No se actualizó",str(exc))
    def _toggle(self):
        item=self.service.obtener(self.items.currentData())
        if not item:return
        (self.service.desactivar if item.activo else self.service.reactivar)(item.id);self._load(item.id)
