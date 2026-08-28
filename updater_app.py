import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QApplication,QComboBox,QDialog,QFileDialog,QFormLayout,QHBoxLayout,
                               QLabel,QMessageBox,QProgressBar,QPushButton,QVBoxLayout,QWidget)

from updater_core import (apply_update,compare_versions,detect_installations,load_package,
                          open_pos,validate_installation)


def package_root():
    return Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent


class UpdaterWindow(QWidget):
    def __init__(self,root=None,candidate_paths=None):
        super().__init__();self.package=load_package(root or package_root());self.candidate_paths=candidate_paths;self.installations=[];self.current=None;self.result=None
        self.setWindowTitle("Actualizar PuntoDeVenta");self.setMinimumWidth(680);layout=QVBoxLayout(self)
        title=QLabel("ACTUALIZAR PUNTO DE VENTA");title.setAlignment(Qt.AlignCenter);title.setStyleSheet("font-size:22px;font-weight:bold;color:#1e5f91");layout.addWidget(title)
        self.message=QLabel();self.message.setWordWrap(True);layout.addWidget(self.message)
        self.selector=QComboBox();self.selector.currentIndexChanged.connect(self._selected);layout.addWidget(self.selector)
        form=QFormLayout();self.location=QLabel("—");self.location.setTextInteractionFlags(Qt.TextSelectableByMouse);self.installed=QLabel("—");self.new=QLabel(self.package.version);self.database=QLabel("—")
        form.addRow("Ubicación:",self.location);form.addRow("Versión instalada:",self.installed);form.addRow("Versión nueva:",self.new);form.addRow("Base de datos:",self.database);layout.addLayout(form)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);layout.addWidget(self.progress);self.status=QLabel("Buscando instalación...");layout.addWidget(self.status)
        buttons=QHBoxLayout();self.browse=QPushButton("BUSCAR CARPETA");self.update=QPushButton("ACTUALIZAR");self.update.setStyleSheet("font-size:16px;font-weight:bold;padding:12px;background:#1877c9;color:white");self.open=QPushButton("ABRIR PUNTO DE VENTA");self.open.hide();self.close_button=QPushButton("CERRAR")
        buttons.addWidget(self.browse);buttons.addStretch();buttons.addWidget(self.update);buttons.addWidget(self.open);buttons.addWidget(self.close_button);layout.addLayout(buttons)
        self.browse.clicked.connect(self._browse);self.update.clicked.connect(self._update);self.open.clicked.connect(self._open);self.close_button.clicked.connect(self.close);self._detect()
    def _detect(self):
        self.installations=detect_installations(self.candidate_paths);self.selector.clear()
        if not self.installations:
            self.message.setText("No se encontró automáticamente PuntoDeVenta. Pulse BUSCAR CARPETA y seleccione la carpeta del programa.");self.selector.hide();self.current=None;self._show_current();return
        self.selector.show()
        if len(self.installations)>1:self.message.setText("Se encontraron varias instalaciones. Seleccione cuidadosamente la que desea actualizar.")
        else:self.message.setText("PuntoDeVenta encontrado.")
        for item in self.installations:self.selector.addItem(f"{item.path}  ·  versión {item.version}  ·  {item.modified_at}",item)
        self.selector.setCurrentIndex(0);self._selected(0)
    def _selected(self,index):
        self.current=self.selector.itemData(index) if index>=0 else None;self._show_current()
    def _show_current(self):
        item=self.current;self.location.setText(str(item.path) if item else "—");self.installed.setText(item.version if item else "—")
        compatible=bool(item and item.edition==self.package.edition);valid=bool(item and item.database.valid and compatible)
        database_text=("✓ Encontrada y válida" if item and item.database.valid else (item.database.message if item else "No seleccionada"))
        if item and not compatible:database_text=f"Edición incompatible: instalada {item.edition.value}, paquete {self.package.edition.value}"
        self.database.setText(database_text);self.database.setStyleSheet("color:#217a3c" if valid else "color:#a83232")
        self.update.setEnabled(valid);self.status.setText("Listo para actualizar." if valid else "Seleccione una instalación válida y de la misma edición.")
    def _browse(self):
        path=QFileDialog.getExistingDirectory(self,"Seleccione la carpeta PuntoDeVenta")
        if not path:return
        item=validate_installation(Path(path))
        if item is None:QMessageBox.warning(self,"Carpeta incorrecta","La carpeta seleccionada no contiene PuntoDeVenta.exe.");return
        if not item.database.valid:QMessageBox.critical(self,"Base no válida",item.database.message);return
        self.installations=[item];self.selector.clear();self.selector.addItem(f"{item.path}  ·  versión {item.version}",item);self.selector.show();self.current=item;self._show_current()
    def _update(self):
        if not self.current:return
        comparison=compare_versions(self.current.version,self.package.version)
        if comparison is not None and comparison>=0:
            text="Esta instalación ya tiene la misma versión." if comparison==0 else "Esta instalación tiene una versión superior."
            if QMessageBox.warning(self,"Confirmar actualización",text+"\n\n¿Desea continuar de todas formas?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        if QMessageBox.question(self,"Confirmar",f"Se actualizará:\n{self.current.path}\n\nSe creará un respaldo y se conservarán productos, ventas e inventario.\n\n¿Continuar?",QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)!=QMessageBox.Yes:return
        self.update.setEnabled(False);self.browse.setEnabled(False)
        try:
            self.result=apply_update(self.package,self.current,progress=self._progress)
            self.message.setText("Actualización completada correctamente.\nTus productos, ventas e inventario fueron conservados.");self.status.setText("Completado.");self.open.show();self.selector.setEnabled(False)
            QMessageBox.information(self,"Actualización completada","Actualización completada correctamente.\n\nTus productos, ventas e inventario fueron conservados.")
        except Exception as exc:
            self.status.setText("Actualización cancelada.");QMessageBox.critical(self,"No se pudo actualizar",str(exc));self.update.setText("REINTENTAR");self.update.setEnabled(True);self.browse.setEnabled(True)
    def _progress(self,message,value):
        self.status.setText(message);self.progress.setValue(value);QApplication.processEvents()
    def _open(self):
        if self.result and open_pos(self.result.installation):self.close()
        else:QMessageBox.warning(self,"No se pudo abrir","No se encontró PuntoDeVenta.exe en la instalación actualizada.")


def run():
    app=QApplication.instance() or QApplication(sys.argv)
    try:
        window=UpdaterWindow();window.show()
        if os.environ.get("PUNTO_VENTA_UPDATER_SMOKE_TEST")=="1":QTimer.singleShot(600,lambda:_smoke_close(window,app))
        return app.exec()
    except Exception as exc:QMessageBox.critical(None,"Actualizador inválido",str(exc));return 1


def _smoke_close(window,app):
    code=0
    try:
        if window.windowTitle()!="Actualizar PuntoDeVenta" or window.package.version!="1.1.3":code=2
        if not window.browse.isEnabled() or not window.new.text():code=2
    finally:window.close();app.exit(code)


if __name__=="__main__":raise SystemExit(run())
