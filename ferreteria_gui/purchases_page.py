from decimal import Decimal

from PySide6.QtCore import QDate,Qt
from PySide6.QtWidgets import (QComboBox,QDateEdit,QDialog,QDialogButtonBox,QFormLayout,QHBoxLayout,QInputDialog,
    QLabel,QLineEdit,QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from ferreteria_core.quantity import formato_cantidad,formato_granel
from ferreteria_core.services import ProductQueryService,ProductService,PurchasePresentationService,PurchaseService,SupplierService
from .dialogs import QuickProductDialog
from .presentation import moneda
from .settings_page import CatalogManagerDialog
from .widgets import show_error


def purchase_presentation_options(presentations):
    return [(item.id,item.nombre) for item in presentations]


class PurchasesPage(QWidget):
    def __init__(self,database,parent=None):
        super().__init__(parent);self.database=database;self.service=PurchaseService(database);root=QVBoxLayout(self);title=QLabel("COMPRAS / ENTRADAS");title.setObjectName("pageTitle");root.addWidget(title);actions=QHBoxLayout();self.new=QPushButton("NUEVA ENTRADA");suppliers=QPushButton("PROVEEDORES");presentations=QPushButton("PRESENTACIONES");actions.addWidget(self.new);actions.addWidget(suppliers);actions.addWidget(presentations);actions.addStretch();self.filter=QComboBox();self.filter.addItem("Todas",None);self.filter.addItem("Confirmadas","CONFIRMADA");self.filter.addItem("Canceladas","CANCELADA");actions.addWidget(self.filter);root.addLayout(actions)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(["Folio","Fecha","Proveedor","Productos","Total","Estado"]);self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);root.addWidget(self.table);self.new.clicked.connect(self._new);suppliers.clicked.connect(lambda:CatalogManagerDialog(database,"supplier",self).exec());presentations.clicked.connect(lambda:CatalogManagerDialog(database,"presentation",self).exec());self.filter.currentIndexChanged.connect(self.refresh);self.table.cellDoubleClicked.connect(self._open);self.refresh()
    def refresh(self):
        self.table.setRowCount(0)
        for purchase in self.service.listar(self.filter.currentData()):
            row=self.table.rowCount();self.table.insertRow(row);values=(purchase["folio"],purchase["fecha"],purchase["proveedor_nombre_snapshot"] or "Sin proveedor",purchase["lineas"],moneda(purchase["total_centavos"]),purchase["estado"])
            for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(str(value)))
            self.table.item(row,0).setData(Qt.UserRole,purchase["id"])
    def _new(self):
        dialog=NewPurchaseDialog(self.database,self)
        if dialog.exec()==QDialog.Accepted:self.refresh();QMessageBox.information(self,"Entrada confirmada",f"Compra {dialog.purchase.folio} registrada; inventario actualizado.")
    def _open(self,row,_column):
        PurchaseDetailDialog(self.database,self.table.item(row,0).data(Qt.UserRole),self).exec();self.refresh()


class NewPurchaseDialog(QDialog):
    def __init__(self,database,parent=None):
        super().__init__(parent);self.database=database;self.service=PurchaseService(database);self.lines=[];self.purchase=None;self.setWindowTitle("Nueva entrada de mercancía");self.resize(1050,650);root=QVBoxLayout(self);form=QFormLayout();self.supplier=QComboBox();self.supplier.addItem("Sin proveedor",None)
        for item in SupplierService(database).listar_activos():self.supplier.addItem(item.nombre,item.id)
        self.supplier_folio=QLineEdit();self.date=QDateEdit(QDate.currentDate());self.date.setCalendarPopup(True);self.notes=QLineEdit();form.addRow("Proveedor:",self.supplier);form.addRow("Folio proveedor:",self.supplier_folio);form.addRow("Fecha:",self.date);form.addRow("Notas:",self.notes);root.addLayout(form)
        search=QHBoxLayout();self.query=QLineEdit();self.query.setPlaceholderText("Buscar producto o escanear barcode");add=QPushButton("AGREGAR");search.addWidget(self.query);search.addWidget(add);root.addLayout(search);self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(["Producto","Presentación","Cantidad","Contenido","Entrada base","Costo presentación","Costo unitario","Subtotal"]);root.addWidget(self.table);buttons=QHBoxLayout();edit=QPushButton("EDITAR LÍNEA");remove=QPushButton("ELIMINAR LÍNEA");confirm=QPushButton("CONFIRMAR ENTRADA");confirm.setObjectName("primary");buttons.addWidget(edit);buttons.addWidget(remove);buttons.addStretch();buttons.addWidget(confirm);root.addLayout(buttons);add.clicked.connect(self._add);self.query.returnPressed.connect(self._add);edit.clicked.connect(self._edit);remove.clicked.connect(self._remove);confirm.clicked.connect(self._confirm)
    def _add(self):
        term=self.query.text().strip()
        if not term:return
        result=ProductQueryService(self.database).buscar_inteligente(term,page_size=20);product=result.products[0] if result.products else None
        if product is None:
            dialog=QuickProductDialog(self.database,term,self)
            if dialog.exec()!=QDialog.Accepted:return
            product=dialog.product
        presentations=PurchasePresentationService(self.database).listar_activas();options=purchase_presentation_options(presentations);labels=[name for _item_id,name in options];habitual=next((index for index,(item_id,_name) in enumerate(options) if item_id==product.presentacion_compra_id),0);label,ok=QInputDialog.getItem(self,"Presentación",f"Producto: {product.descripcion}",labels,habitual,False)
        if not ok:return
        presentation_id=options[labels.index(label)][0];default_content=product.contenido_por_presentacion if product.presentacion_compra_id==presentation_id and product.contenido_por_presentacion else 1
        if product.tipo_venta=="GRANEL" and default_content!=1:default_content=formato_granel(default_content,product.unidad_granel or "PESO").split()[0]
        quantity,ok=QInputDialog.getText(self,"Cantidad","Número de presentaciones:",text="1")
        if not ok:return
        content,ok=QInputDialog.getText(self,"Contenido","Unidades base por presentación (pzas, kg o L):",text=str(default_content))
        if not ok:return
        cost,ok=QInputDialog.getText(self,"Costo","Costo por presentación:")
        if not ok:return
        try:self.lines.append(self.service.crear_linea(product.id,presentation_id,quantity,content,Decimal(cost)));self._reload();self.query.clear();self.query.setFocus()
        except Exception as exc:show_error(self,"Línea inválida",exc)
    def _reload(self):
        self.table.setRowCount(0)
        for line in self.lines:
            product=ProductService(self.database).get(line.producto_id);row=self.table.rowCount();self.table.insertRow(row);base=formato_cantidad(product.tipo_venta,unidades=line.cantidad_base,miligramos=line.cantidad_base,unidad_granel=product.unidad_granel or "PESO");values=(product.descripcion,line.presentacion_nombre,str(line.cantidad_presentaciones),base if product.tipo_venta=="GRANEL" else line.contenido_por_presentacion,base,moneda(line.costo_presentacion_centavos),moneda(line.costo_unitario_centavos),moneda(line.subtotal_centavos))
            for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(str(value)))
    def _remove(self):
        row=self.table.currentRow()
        if row>=0:self.lines.pop(row);self._reload()
    def _edit(self):
        row=self.table.currentRow()
        if row<0:return
        old=self.lines[row];product=ProductService(self.database).get(old.producto_id);presentations=PurchasePresentationService(self.database).listar_activas();options=purchase_presentation_options(presentations);labels=[name for _item_id,name in options];current=next((index for index,(item_id,_name) in enumerate(options) if item_id==old.presentacion_id),0);label,ok=QInputDialog.getItem(self,"Presentación",product.descripcion or "Producto",labels,current,False)
        if not ok:return
        presentation_id=options[labels.index(label)][0];quantity,ok=QInputDialog.getText(self,"Cantidad","Número de presentaciones:",text=str(old.cantidad_presentaciones))
        if not ok:return
        content_value=old.contenido_por_presentacion if product.tipo_venta=="UNIDAD" else formato_granel(old.contenido_por_presentacion,product.unidad_granel or "PESO").split()[0];content,ok=QInputDialog.getText(self,"Contenido","Unidades base por presentación:",text=str(content_value))
        if not ok:return
        cost,ok=QInputDialog.getText(self,"Costo","Costo por presentación:",text=f"{Decimal(old.costo_presentacion_centavos)/Decimal(100):.2f}")
        if not ok:return
        try:self.lines[row]=self.service.crear_linea(product.id,presentation_id,quantity,content,cost);self._reload()
        except Exception as exc:show_error(self,"Línea inválida",exc)
    def _confirm(self):
        if not self.lines:QMessageBox.warning(self,"Sin productos","Agregue al menos un producto.");return
        total=sum(line.subtotal_centavos for line in self.lines)
        if QMessageBox.question(self,"Confirmar entrada",f"Proveedor: {self.supplier.currentText()}\nLíneas: {len(self.lines)}\nTotal: {moneda(total)}\n\n¿Confirmar?")!=QMessageBox.Yes:return
        try:self.purchase=self.service.confirmar(self.lines,self.supplier.currentData(),self.supplier_folio.text(),self.date.date().toString("yyyy-MM-dd"),self.notes.text());self.accept()
        except Exception as exc:show_error(self,"No se confirmó la entrada",exc)


class PurchaseDetailDialog(QDialog):
    def __init__(self,database,purchase_id,parent=None):
        super().__init__(parent);self.database=database;self.service=PurchaseService(database);self.purchase=self.service.obtener(purchase_id);self.setWindowTitle(self.purchase.folio);root=QVBoxLayout(self);root.addWidget(QLabel(f"{self.purchase.folio} | {self.purchase.fecha} | {self.purchase.estado}\nProveedor: {self.purchase.proveedor_nombre_snapshot or 'Sin proveedor'}\nFolio proveedor: {self.purchase.folio_proveedor or '—'}\nNotas: {self.purchase.notas or '—'}"));table=QTableWidget(len(self.purchase.detalles),5);table.setHorizontalHeaderLabels(["Producto","Presentación","Cantidad base","Costo unitario","Subtotal"])
        for row,item in enumerate(self.purchase.detalles):
            values=(item.descripcion_snapshot,item.presentacion_snapshot,item.cantidad_base,moneda(item.costo_unitario_centavos),moneda(item.subtotal_centavos))
            for col,value in enumerate(values):table.setItem(row,col,QTableWidgetItem(str(value)))
        root.addWidget(table);buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(self.reject);buttons.accepted.connect(self.accept);root.addWidget(buttons)
        if self.purchase.estado=="CONFIRMADA":cancel=QPushButton("CANCELAR COMPRA");cancel.setObjectName("danger");cancel.clicked.connect(self._cancel);root.addWidget(cancel)
    def _cancel(self):
        if QMessageBox.question(self,"Cancelar compra","Se revertirá el inventario. El costo actual no se restaurará. ¿Continuar?")!=QMessageBox.Yes:return
        try:self.purchase=self.service.cancelar(self.purchase.id);QMessageBox.information(self,"Compra cancelada","Inventario revertido correctamente. El costo actual se conservó.");self.accept()
        except Exception as exc:show_error(self,"No se pudo cancelar",exc)
