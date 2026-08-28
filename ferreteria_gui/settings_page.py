from pathlib import Path

from PySide6.QtCore import Qt,Signal,QUrl
from PySide6.QtGui import QDesktopServices,QPixmap
from PySide6.QtWidgets import QFileDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QVBoxLayout,QWidget

from ferreteria_core.services import BackupService,BusinessConfigService,validar_respaldo
from ferreteria_core.version import __version__
from .config import BACKUP_ROOT,BRANDING_DIR
from .widgets import show_error


class SettingsPage(QWidget):
    settings_saved=Signal(object)
    restored=Signal()
    def __init__(self,database,backup_root=BACKUP_ROOT,parent=None):
        super().__init__(parent);self.service=BusinessConfigService(database,BRANDING_DIR);self.backups=BackupService(database,backup_root);self.logo_source=None
        root=QVBoxLayout(self);title=QLabel("CONFIGURACIÓN");title.setObjectName("pageTitle");root.addWidget(title);form=QFormLayout();self.name=QLineEdit();self.address=QLineEdit();self.phone=QLineEdit();self.rfc=QLineEdit();self.message=QLineEdit();self.currency=QLineEdit("MXN");self.currency.setReadOnly(True)
        for label,widget in (("Nombre del negocio",self.name),("Dirección",self.address),("Teléfono",self.phone),("RFC (opcional)",self.rfc),("Mensaje del ticket",self.message),("Moneda",self.currency)):form.addRow(label,widget)
        root.addLayout(form);logo_row=QHBoxLayout();self.preview=QLabel("Sin logo");self.preview.setFixedSize(220,100);self.preview.setAlignment(Qt.AlignCenter);self.preview.setStyleSheet("border:1px solid #aeb8c2;background:white");choose=QPushButton("Seleccionar logo");logo_row.addWidget(self.preview);logo_row.addWidget(choose);logo_row.addStretch();root.addLayout(logo_row);save=QPushButton("GUARDAR CONFIGURACIÓN");save.setObjectName("primary");root.addWidget(save,alignment=Qt.AlignLeft)
        backup_title=QLabel("RESPALDOS");backup_title.setObjectName("pageTitle");root.addWidget(backup_title);backup_row=QHBoxLayout();manual=QPushButton("Crear respaldo ahora");restore=QPushButton("Restaurar respaldo");open_folder=QPushButton("Abrir carpeta de respaldos");backup_row.addWidget(manual);backup_row.addWidget(restore);backup_row.addWidget(open_folder);backup_row.addStretch();root.addLayout(backup_row);root.addWidget(QLabel(f"Versión {__version__}"));root.addStretch();choose.clicked.connect(self._choose);save.clicked.connect(self.save);manual.clicked.connect(self._manual_backup);restore.clicked.connect(self._restore);open_folder.clicked.connect(self._open_backups);self.load()
    def load(self):
        settings=self.service.obtener();self.name.setText(settings.nombre_negocio);self.address.setText(settings.direccion or "");self.phone.setText(settings.telefono or "");self.rfc.setText(settings.rfc or "");self.message.setText(settings.mensaje_ticket or "");self._show_logo(settings.logo_path)
    def _choose(self):
        path,_=QFileDialog.getOpenFileName(self,"Seleccionar logo","","Imágenes (*.png *.jpg *.jpeg)")
        if path:self.logo_source=path;self._show_logo(path)
    def _show_logo(self,path):
        if path and Path(path).exists():self.preview.setPixmap(QPixmap(path).scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:self.preview.setPixmap(QPixmap());self.preview.setText("Sin logo")
    def save(self):
        try:
            settings=self.service.guardar(nombre_negocio=self.name.text(),direccion=self.address.text(),telefono=self.phone.text(),rfc=self.rfc.text(),mensaje_ticket=self.message.text(),logo_origen=self.logo_source);self.logo_source=None;self._show_logo(settings.logo_path);self.settings_saved.emit(settings)
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
