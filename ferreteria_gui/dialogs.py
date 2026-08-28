from decimal import Decimal

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QHBoxLayout,
                               QButtonGroup, QFileDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout,QWidget)

from ferreteria_core.services import GenericProductImporter, InitialInventoryService, InventoryService, ProductQueryService, ProductService
from ferreteria_core.money import centavos_a_decimal
from ferreteria_core.pricing import normalizar_porcentaje,porcentaje_real,precio_venta_sugerido
from ferreteria_core.quantity import (auxiliar_granel,cantidad_desde_mayor,formato_cantidad,formato_granel,
                                      importe_a_cantidad,subtotal_granel_centavos)
from .presentation import calcular_pago, cantidad_producto, moneda, nombre_producto, parsear_importe, precio_producto
from .widgets import show_error
from .config import TRUPER_ENABLED


class PaymentDialog(QDialog):
    def __init__(self, total_centavos, parent=None):
        super().__init__(parent); self.total_centavos = total_centavos; self.payment = None
        self.setWindowTitle("Cobrar venta"); self.setMinimumWidth(420)
        layout = QFormLayout(self)
        total = QLabel(moneda(total_centavos)); total.setStyleSheet("font-size:28px;font-weight:bold")
        self.method = QComboBox(); self.method.addItems(["EFECTIVO","TRANSFERENCIA","TARJETA","OTRO"])
        self.received = QLineEdit(); self.received.setPlaceholderText("0.00")
        self.change = QLabel("—"); self.change.setStyleSheet("font-size:22px;font-weight:bold;color:#1877c9")
        layout.addRow("Total a pagar:", total); layout.addRow("Método:", self.method)
        layout.addRow("Recibido:", self.received); layout.addRow("Cambio:", self.change)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("CONFIRMAR VENTA"); buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self._accept); buttons.rejected.connect(self.reject); layout.addRow(buttons)
        self.method.currentTextChanged.connect(self._refresh); self.received.textChanged.connect(self._refresh)
        self._refresh(); self.received.setFocus()

    def _refresh(self):
        cash = self.method.currentText() == "EFECTIVO"; self.received.setEnabled(cash)
        self.payment = calcular_pago(self.total_centavos, self.method.currentText(), self.received.text())
        self.change.setText(moneda(self.payment.cambio_centavos) if self.payment.cambio_centavos is not None else "—")

    def _accept(self):
        self._refresh()
        if not self.payment.puede_confirmar:
            QMessageBox.warning(self, "Pago incompleto", self.payment.mensaje); return
        self.accept()


class BulkSaleDialog(QDialog):
    def __init__(self,product,parent=None):
        super().__init__(parent);self.product=product;self.bulk_unit=product.unidad_granel or "PESO";self.cantidad_mg=None;self._syncing=False;self._source="cantidad";self.setWindowTitle("Agregar producto a granel");self.setMinimumWidth(430)
        form=QFormLayout(self);name=QLabel(nombre_producto(product));name.setStyleSheet("font-size:18px;font-weight:bold");form.addRow(name);form.addRow("Precio unitario:",QLabel(precio_producto(product)))
        if product.controla_inventario:form.addRow("Existencia disponible:",QLabel(formato_granel(product.existencia_granel_mg,self.bulk_unit)))
        suffix="L" if self.bulk_unit=="VOLUMEN" else "kg";self.quantity=QLineEdit();self.quantity.setPlaceholderText("0.500" if self.bulk_unit=="VOLUMEN" else "0.051");self.amount=QLineEdit();self.amount.setPlaceholderText("30.00" if self.bulk_unit=="VOLUMEN" else "5.45");self.help=QLabel(f"Ingrese {suffix} o importe");form.addRow(f"Cantidad ({suffix}):",self.quantity);form.addRow("Importe ($):",self.amount);form.addRow(self.help)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);self.buttons.button(QDialogButtonBox.Ok).setText("ACEPTAR");self.buttons.accepted.connect(self._accept);self.buttons.rejected.connect(self.reject);form.addRow(self.buttons)
        self.quantity.textEdited.connect(self._from_quantity);self.amount.textEdited.connect(self._from_amount);QWidget.setTabOrder(self.quantity,self.amount);QWidget.setTabOrder(self.amount,self.buttons.button(QDialogButtonBox.Ok));self.quantity.setFocus()
    def _set(self,widget,text):
        self._syncing=True;widget.blockSignals(True);widget.setText(text);widget.blockSignals(False);self._syncing=False
    def _from_quantity(self):
        if self._syncing:return
        self._source="cantidad"
        try:
            mg=cantidad_desde_mayor(self.quantity.text(),self.bulk_unit);total=subtotal_granel_centavos(self.product.precio_venta,mg);self._set(self.amount,f"{Decimal(total)/Decimal(100):.2f}");self.help.setText(f"Equivale a {auxiliar_granel(mg,self.bulk_unit)}")
        except ValueError:self._set(self.amount,"");self.help.setText("Cantidad inválida")
    def _from_amount(self):
        if self._syncing:return
        self._source="importe"
        try:
            total=parsear_importe(self.amount.text(),nombre="Importe",vacio_cero=False);mg=importe_a_cantidad(total,self.product.precio_venta,self.bulk_unit);suffix=" L" if self.bulk_unit=="VOLUMEN" else " kg";text=formato_granel(mg,self.bulk_unit).removesuffix(suffix);self._set(self.quantity,text);self.help.setText(f"Equivale aproximadamente a {auxiliar_granel(mg,self.bulk_unit)}")
        except ValueError:self._set(self.quantity,"");self.help.setText("Importe inválido")
    def _accept(self):
        try:
            self.cantidad_mg=cantidad_desde_mayor(self.quantity.text(),self.bulk_unit) if self._source=="cantidad" else importe_a_cantidad(parsear_importe(self.amount.text(),nombre="Importe",vacio_cero=False),self.product.precio_venta,self.bulk_unit)
            if self.product.controla_inventario and self.cantidad_mg>self.product.existencia_granel_mg:raise ValueError(f"Existencia insuficiente. Disponible: {formato_granel(self.product.existencia_granel_mg,self.bulk_unit)}; solicitado: {formato_granel(self.cantidad_mg,self.bulk_unit)}")
            self.accept()
        except Exception as exc:show_error(self,"No se pudo agregar",exc)


class VariablePriceDialog(QDialog):
    def __init__(self,product,parent=None,*,current_price=None,quantity=1,price_only=False):
        super().__init__(parent);self.product=product;self.precio_unitario_centavos=None;self.cantidad=quantity;self.setWindowTitle("Precio de esta venta");self.setMinimumWidth(420)
        form=QFormLayout(self);name=QLabel(nombre_producto(product));name.setStyleSheet("font-size:18px;font-weight:bold");form.addRow(name)
        self.price=QLineEdit();suggested=current_price if current_price is not None else product.precio_venta
        if suggested is not None:self.price.setText(_decimal_text(suggested));self.price.selectAll()
        self.quantity=QSpinBox();self.quantity.setRange(1,1_000_000);self.quantity.setValue(quantity);self.quantity.setVisible(not price_only)
        self.subtotal=QLabel("Subtotal: —");self.subtotal.setStyleSheet("font-size:17px;font-weight:bold")
        form.addRow("Precio de esta venta: $",self.price)
        if not price_only:form.addRow("Cantidad:",self.quantity)
        form.addRow(self.subtotal)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText("AGREGAR" if not price_only else "GUARDAR");buttons.accepted.connect(self._accept);buttons.rejected.connect(self.reject);form.addRow(buttons)
        self.price.textChanged.connect(self._refresh);self.quantity.valueChanged.connect(self._refresh);self._refresh();self.price.setFocus()
    def _refresh(self):
        try:self.subtotal.setText(f"Subtotal: {moneda(parsear_importe(self.price.text(),nombre='Precio',vacio_cero=False)*self.quantity.value())}")
        except ValueError:self.subtotal.setText("Subtotal: —")
    def _accept(self):
        try:
            cents=parsear_importe(self.price.text(),nombre="Precio de esta venta",vacio_cero=False)
            if cents<=0:raise ValueError("El precio de esta venta debe ser mayor que cero.")
            self.precio_unitario_centavos=cents;self.cantidad=self.quantity.value();self.accept()
        except Exception as exc:show_error(self,"Precio inválido",exc)


class BulkStockDialog(QDialog):
    def __init__(self,product,mode,parent=None):
        super().__init__(parent);self.product=product;self.mode=mode;self.cantidad_mg=None;self.setWindowTitle("Existencia a granel")
        self.bulk_unit=product.unidad_granel or "PESO";suffix="L" if self.bulk_unit=="VOLUMEN" else "kg";form=QFormLayout(self);form.addRow("Producto:",QLabel(nombre_producto(product)));form.addRow("Actual:",QLabel(formato_granel(product.existencia_granel_mg,self.bulk_unit)));self.value=QLineEdit();self.value.setPlaceholderText(f"{suffix}, por ejemplo 1.250");form.addRow(f"Cantidad en {suffix}:" if mode=="ENTRADA" else f"Nueva existencia en {suffix}:",self.value);self.note=QLineEdit();form.addRow("Nota / motivo:",self.note)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(self._accept);buttons.rejected.connect(self.reject);form.addRow(buttons)
    def _accept(self):
        try:
            self.cantidad_mg=cantidad_desde_mayor(self.value.text(),self.bulk_unit,allow_zero=self.mode=="AJUSTE")
            if self.mode=="AJUSTE" and not self.note.text().strip():raise ValueError("El motivo es obligatorio")
            self.accept()
        except Exception as exc:show_error(self,"Cantidad inválida",exc)


class BulkTypeDialog(QDialog):
    def __init__(self,count,parent=None):
        super().__init__(parent);self.setWindowTitle("Editar seleccionados");form=QFormLayout(self);form.addRow(QLabel(f"Se modificarán {count} productos seleccionados."));self.field=QComboBox();self.field.addItem("Tipo de venta","tipo_venta");self.field.addItem("Activo / inactivo","activo");self.field.addItem("Categoría","categoria");form.addRow("Campo:",self.field);self.kind=QComboBox();self.kind.addItems(["UNIDAD","GRANEL"]);self.bulk_unit=QComboBox();self.bulk_unit.addItem("Peso (kg)","PESO");self.bulk_unit.addItem("Volumen (L)","VOLUMEN");self.active=QComboBox();self.active.addItem("Activo",True);self.active.addItem("Inactivo",False);self.category=QLineEdit();form.addRow("Tipo de venta:",self.kind);form.addRow("Unidad:",self.bulk_unit);form.addRow("Estado:",self.active);form.addRow("Categoría:",self.category);self.warning=QLabel("Los precios individuales no se modificarán; para GRANEL se interpretarán por kg o por L según la unidad elegida.");self.warning.setWordWrap(True);form.addRow(self.warning);buttons=QDialogButtonBox(QDialogButtonBox.Apply|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);form.addRow(buttons);self.field.currentIndexChanged.connect(self._refresh);self.kind.currentTextChanged.connect(self._refresh);self._refresh()
    def _refresh(self):
        field=self.field.currentData();self.kind.setVisible(field=="tipo_venta");self.bulk_unit.setVisible(field=="tipo_venta" and self.kind.currentText()=="GRANEL");self.active.setVisible(field=="activo");self.category.setVisible(field=="categoria");self.warning.setVisible(field=="tipo_venta")
    def change(self):
        field=self.field.currentData()
        value=self.kind.currentText() if field=="tipo_venta" else self.active.currentData() if field=="activo" else self.category.text()
        return field,value,(self.bulk_unit.currentData() if field=="tipo_venta" and value=="GRANEL" else None)


class InventoryMovementsDialog(QDialog):
    def __init__(self,product,movements,parent=None):
        super().__init__(parent);unit="L" if product.unidad_granel=="VOLUMEN" else "kg" if product.tipo_venta=="GRANEL" else "pza";self.setWindowTitle(f"Movimientos · {nombre_producto(product)}");self.resize(900,480);root=QVBoxLayout(self);root.addWidget(QLabel(f"Producto: {nombre_producto(product)}   ·   Unidad: {unit}"));table=QTableWidget(len(movements),6);table.setHorizontalHeaderLabels(["Fecha","Tipo","Cantidad","Anterior","Nueva","Nota / referencia"]);table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row,movement in enumerate(movements):
            if movement["tipo_venta_snapshot"]=="GRANEL":values=[movement["fecha_hora"],movement["tipo"],formato_cantidad("GRANEL",miligramos=abs(movement["cantidad_mg"]),unidad_granel=product.unidad_granel or "PESO"),formato_cantidad("GRANEL",miligramos=movement["existencia_anterior_mg"],unidad_granel=product.unidad_granel or "PESO"),formato_cantidad("GRANEL",miligramos=movement["existencia_nueva_mg"],unidad_granel=product.unidad_granel or "PESO"),movement["nota"] or movement["referencia"] or ""]
            else:values=[movement["fecha_hora"],movement["tipo"],movement["cantidad"],movement["existencia_anterior"],movement["existencia_nueva"],movement["nota"] or movement["referencia"] or ""]
            for column,value in enumerate(values):table.setItem(row,column,QTableWidgetItem(str(value)))
        table.horizontalHeader().setStretchLastSection(True);root.addWidget(table);close=QPushButton("Cerrar");close.clicked.connect(self.accept);root.addWidget(close)


class ExternalProductDialog(QDialog):
    def __init__(self, product_service, barcode="", parent=None):
        super().__init__(parent); self.service = product_service; self.product = None; self.setWindowTitle("Crear producto externo")
        form = QFormLayout(self); self.barcode = QLineEdit(barcode); self.description = QLineEdit(); self.brand = QLineEdit()
        self.kind=QComboBox();self.kind.addItems(["UNIDAD","GRANEL"]);self.bulk_unit=QComboBox();self.bulk_unit.addItem("Peso (kg)","PESO");self.bulk_unit.addItem("Volumen (L)","VOLUMEN");self.cost=QLineEdit();self.margin=QLineEdit();self.price=QLineEdit();self.control=QCheckBox();_style_inventory_control(self.control,True);self.stock=QSpinBox();self.stock.setMaximum(1_000_000);self.bulk_stock=QLineEdit("0");self.key=QLineEdit()
        for label,widget in (("Código de barras",self.barcode),("Descripción",self.description),("Se vende",self.kind),("Unidad de granel",self.bulk_unit),("Precio proveedor",self.cost),("Ganancia %",self.margin),("Precio venta",self.price),("",self.control),("Existencia inicial (pzas)",self.stock),("Existencia inicial granel",self.bulk_stock),("Clave (opcional)",self.key),("Marca (opcional)",self.brand)):form.addRow(label,widget)
        self._syncing=False;self.kind.currentTextChanged.connect(self._refresh_stock);self.bulk_unit.currentIndexChanged.connect(self._refresh_stock);self.control.toggled.connect(self._refresh_stock);self.cost.textEdited.connect(lambda:self._sync_prices("cost"));self.margin.textEdited.connect(lambda:self._sync_prices("margin"));self.price.textEdited.connect(lambda:self._sync_prices("sale"));self._refresh_stock()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); form.addRow(buttons)

    def _save(self):
        try:
            cents = parsear_importe(self.price.text(), nombre="Precio", vacio_cero=False)
            bulk=cantidad_desde_mayor(self.bulk_stock.text() or "0",self.bulk_unit.currentData(),allow_zero=True) if self.kind.currentText()=="GRANEL" and self.control.isChecked() else 0
            units=self.stock.value() if self.kind.currentText()=="UNIDAD" and self.control.isChecked() else 0
            cost=_optional_decimal(self.cost.text());margin=self.margin.text().strip() or None
            self.product = self.service.crear_producto_externo(self.barcode.text(), self.description.text(), Decimal(cents) / Decimal(100), units, marca=self.brand.text(),clave=self.key.text(),tipo_venta=self.kind.currentText(),unidad_granel=self.bulk_unit.currentData(),existencia_granel_mg=bulk,precio_proveedor=cost,porcentaje_ganancia=margin,controla_inventario=self.control.isChecked())
            self.accept()
        except Exception as exc: show_error(self, "No se pudo crear el producto", exc)
    def _refresh_stock(self):
        enabled=self.control.isChecked();bulk=self.kind.currentText()=="GRANEL";self.bulk_unit.setEnabled(bulk);self.stock.setVisible(enabled and not bulk);self.bulk_stock.setVisible(enabled and bulk);self.bulk_stock.setPlaceholderText("L" if self.bulk_unit.currentData()=="VOLUMEN" else "kg")
    def _sync_prices(self,source):_sync_price_fields(self.cost,self.margin,self.price,source)


class ProductModifyDialog(QDialog):
    def __init__(self,product,service,parent=None):
        super().__init__(parent);self.product=product;self.service=service;self.saved_product=None;self.setWindowTitle("Modificar producto");self.setMinimumWidth(520);form=QFormLayout(self)
        for label,value in (("Código",product.codigo_truper or "—"),("Barcode",product.codigo_barras or "—"),("Clave",product.clave or "—")):form.addRow(label+":",QLabel(value))
        self.description=QLineEdit(product.descripcion or "");self.kind=QComboBox();self.kind.addItems(["UNIDAD","GRANEL"]);self.kind.setCurrentText(product.tipo_venta);self.bulk_unit=QComboBox();self.bulk_unit.addItem("Peso (kg)","PESO");self.bulk_unit.addItem("Volumen (L)","VOLUMEN");self.bulk_unit.setCurrentIndex(max(0,self.bulk_unit.findData(product.unidad_granel or "PESO")));self.catalog=QLineEdit(_decimal_text(product.precio_catalogo_publico));self.cost=QLineEdit(_decimal_text(product.precio_proveedor));self.margin=QLineEdit(product.porcentaje_ganancia or "");self.sale=QLineEdit(_decimal_text(product.precio_venta));self.variable=QCheckBox("Precio variable en cada venta");self.variable.setChecked(product.precio_variable);self.control=QCheckBox();_style_inventory_control(self.control,product.controla_inventario);self.active=QCheckBox("Producto activo");self.active.setChecked(product.activo)
        for label,widget in (("Descripción",self.description),("Se vende",self.kind),("Unidad de granel",self.bulk_unit),("Precio catálogo Truper",self.catalog),("Precio proveedor",self.cost),("Ganancia %",self.margin),("Precio venta / sugerido",self.sale),("",self.variable),("",self.control),("",self.active)):form.addRow(label,widget)
        self.kind.currentTextChanged.connect(self._refresh_bulk_unit);self.variable.toggled.connect(self._refresh_bulk_unit);self._refresh_bulk_unit();self.cost.textEdited.connect(lambda:_sync_price_fields(self.cost,self.margin,self.sale,"cost"));self.margin.textEdited.connect(lambda:_sync_price_fields(self.cost,self.margin,self.sale,"margin"));self.sale.textEdited.connect(lambda:_sync_price_fields(self.cost,self.margin,self.sale,"sale"));buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Save).setText("GUARDAR");buttons.accepted.connect(self._save);buttons.rejected.connect(self.reject);form.addRow(buttons)
    def _refresh_bulk_unit(self):self.bulk_unit.setEnabled(self.kind.currentText()=="GRANEL");self.variable.setEnabled(self.kind.currentText()=="UNIDAD")
    def _save(self):
        try:
            new_unit=self.bulk_unit.currentData() if self.kind.currentText()=="GRANEL" else None
            if self.product.tipo_venta=="GRANEL" and self.kind.currentText()=="GRANEL" and (self.product.unidad_granel or "PESO")!=new_unit:
                if QMessageBox.warning(self,"Cambiar unidad","Este cambio modifica cómo se interpretan el precio y las cantidades futuras.\nLos históricos no cambiarán.\n\n¿Continuar?",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
            self.saved_product=self.service.modificar_producto(self.product.id,descripcion=self.description.text(),tipo_venta=self.kind.currentText(),unidad_granel=new_unit,precio_catalogo_publico=_optional_decimal(self.catalog.text()),precio_proveedor=_optional_decimal(self.cost.text()),porcentaje_ganancia=self.margin.text().strip() or None,precio_venta=_optional_decimal(self.sale.text()),controla_inventario=self.control.isChecked(),activo=self.active.isChecked(),precio_variable=self.variable.isChecked());self.accept()
        except Exception as exc:show_error(self,"No se pudo modificar el producto",exc)


def _decimal_text(cents):return "" if cents is None else f"{centavos_a_decimal(cents):.2f}"
def _optional_decimal(text):return None if not (text or "").strip() else Decimal(text.strip().replace("$","").replace(",",""))
def _style_inventory_control(checkbox,checked=True):
    checkbox.setChecked(bool(checked));checkbox.setMinimumHeight(38);checkbox.setFocusPolicy(Qt.StrongFocus)
    checkbox.setStyleSheet("QCheckBox{font-size:15px;font-weight:700;padding:7px 10px;border:2px solid #6b7280;border-radius:6px;background:#f3f4f6;} QCheckBox::indicator{width:22px;height:22px;} QCheckBox:checked{color:#14532d;border-color:#15803d;background:#dcfce7;} QCheckBox:!checked{color:#7f1d1d;border-color:#b91c1c;background:#fee2e2;} QCheckBox:focus{border:3px solid #1d4ed8;}")
    def refresh(value):checkbox.setText("✓ Controlar inventario: ACTIVADO" if value else "✕ Controlar inventario: DESACTIVADO")
    checkbox.toggled.connect(refresh);refresh(checkbox.isChecked())
def _set_text(widget,value):widget.blockSignals(True);widget.setText(value);widget.blockSignals(False)
def _sync_price_fields(cost_widget,margin_widget,sale_widget,source):
    try:
        cost_text=cost_widget.text().strip();margin_text=margin_widget.text().strip();sale_text=sale_widget.text().strip()
        cost=None if not cost_text else parsear_importe(cost_text,nombre="Precio proveedor",vacio_cero=False)
        if source in {"cost","margin"} and cost is not None and margin_text:
            suggested=precio_venta_sugerido(cost,normalizar_porcentaje(margin_text));_set_text(sale_widget,f"{Decimal(suggested)/Decimal(100):.2f}")
        elif source=="sale" and cost not in {None,0} and sale_text:
            sale=parsear_importe(sale_text,nombre="Precio venta",vacio_cero=False);_set_text(margin_widget,porcentaje_real(cost,sale) or "")
    except ValueError:pass


class PriceEditDialog(QDialog):
    def __init__(self, product, product_service, parent=None):
        super().__init__(parent); self.product=product; self.service=product_service; self.saved_product=None
        self.setWindowTitle("Editar precio de venta"); form=QFormLayout(self)
        form.addRow("Producto:",QLabel(nombre_producto(product))); form.addRow("Clave:",QLabel(product.clave or "—"))
        form.addRow("Precio catálogo:",QLabel(moneda(product.precio_catalogo_publico)))
        form.addRow("Precio de venta actual:",QLabel(moneda(product.precio_venta)))
        self.new_price=QLineEdit("" if product.precio_venta is None else f"{Decimal(product.precio_venta)/Decimal(100):.2f}"); self.new_price.selectAll(); form.addRow("Nuevo precio: $",self.new_price)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.button(QDialogButtonBox.Save).setText("GUARDAR"); buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject); form.addRow(buttons)
    def _save(self):
        try:
            cents=parsear_importe(self.new_price.text(),nombre="Nuevo precio",vacio_cero=False)
            self.saved_product=self.service.actualizar_precio_venta(self.product.id,Decimal(cents)/Decimal(100)); self.accept()
        except Exception as exc:show_error(self,"No se pudo actualizar el precio",exc)


class DescriptionEditDialog(QDialog):
    def __init__(self,product,product_service,parent=None):
        super().__init__(parent);self.product=product;self.service=product_service;self.saved_product=None;self.setWindowTitle("Editar descripción")
        form=QFormLayout(self);form.addRow("Producto:",QLabel(nombre_producto(product)));form.addRow("Código Truper:",QLabel(product.codigo_truper or "—"));form.addRow("Clave:",QLabel(product.clave or "—"));form.addRow("Descripción actual:",QLabel(product.descripcion or "—"));self.description=QLineEdit(product.descripcion or "");form.addRow("Nueva descripción:",self.description)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(self._save);buttons.rejected.connect(self.reject);form.addRow(buttons);self.description.setFocus();self.description.selectAll()
    def _save(self):
        try:self.saved_product=self.service.actualizar_descripcion_producto(self.product.id,self.description.text());self.accept()
        except Exception as exc:show_error(self,"No se pudo actualizar la descripción",exc)


class QuickStockDialog(QDialog):
    def __init__(self,database,product,requested,parent=None):
        super().__init__(parent);self.database=database;self.product=product;self.requested=requested;self.setWindowTitle("Actualizar existencia")
        form=QFormLayout(self);form.addRow("Producto:",QLabel(nombre_producto(product)));form.addRow("Existencia registrada:",QLabel(str(product.existencia)));form.addRow("Cantidad solicitada:",QLabel(str(requested)));self.physical=QSpinBox();self.physical.setRange(requested,1_000_000);self.physical.setValue(max(requested,product.existencia));form.addRow("Existencia física real:",self.physical)
        self.adjust=QRadioButton("Corregir existencia");self.entry=QRadioButton("Llegó mercancía nueva");self.adjust.setChecked(True);group=QButtonGroup(self);group.addButton(self.adjust);group.addButton(self.entry);modes=QVBoxLayout();modes.addWidget(self.adjust);modes.addWidget(self.entry);form.addRow("Motivo:",modes)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Save).setText("GUARDAR Y CONTINUAR");buttons.accepted.connect(self._save);buttons.rejected.connect(self.reject);form.addRow(buttons)
    def _save(self):
        try:
            inventory=InventoryService(self.database);new=self.physical.value()
            if self.adjust.isChecked():inventory.ajustar_existencia(self.product.id,new,"Corrección rápida desde venta")
            else:
                delta=new-self.product.existencia
                if delta<=0:raise ValueError("La existencia física debe ser mayor para registrar una entrada")
                inventory.registrar_entrada(self.product.id,delta,"Entrada rápida desde venta")
            self.accept()
        except Exception as exc:show_error(self,"No se pudo actualizar la existencia",exc)


class GenericImportDialog(QDialog):
    def __init__(self,database,parent=None):
        super().__init__(parent);self.importer=GenericProductImporter(database);self.path=None;self.imported=False;self.setWindowTitle("Importar productos CSV/XLSX");self.resize(560,300)
        root=QVBoxLayout(self);choose=QPushButton("Seleccionar archivo CSV o XLSX");self.summary=QLabel("Seleccione un archivo para revisar su contenido.");self.summary.setWordWrap(True);self.import_button=QPushButton("IMPORTAR NUEVOS");self.import_button.setEnabled(False);cancel=QPushButton("Cancelar");root.addWidget(choose);root.addWidget(self.summary);buttons=QHBoxLayout();buttons.addStretch();buttons.addWidget(self.import_button);buttons.addWidget(cancel);root.addLayout(buttons);choose.clicked.connect(self._choose);self.import_button.clicked.connect(self._import);cancel.clicked.connect(self.reject)
    def _choose(self):
        path,_=QFileDialog.getOpenFileName(self,"Importar productos","","Productos (*.csv *.xlsx)")
        if not path:return
        try:
            result,_=self.importer.analizar(path);self.path=path;self.summary.setText(_import_summary(result));self.import_button.setEnabled(result.nuevos>0)
        except Exception as exc:show_error(self,"No se pudo analizar el archivo",exc)
    def _import(self):
        try:
            result=self.importer.importar(self.path);self.imported=True;QMessageBox.information(self,"Importación terminada",_import_summary(result));self.accept()
        except Exception as exc:show_error(self,"No se pudo importar",exc)


def _import_summary(result):
    text=f"Registros encontrados: {result.encontrados}\nNuevos: {result.nuevos}\nDuplicados: {result.duplicados}\nErrores: {result.errores}"
    if result.detalles_error:text+="\n\n"+"\n".join(result.detalles_error[:8])
    return text


class LinkProductDialog(QDialog):
    def __init__(self, database, barcode="", parent=None):
        super().__init__(parent); self.database = database; self.service = ProductService(database); self.selected_id = None; self.product = None
        self.setWindowTitle("Vincular código de barras"); self.resize(850, 520)
        root = QVBoxLayout(self); form = QHBoxLayout(); self.barcode = QLineEdit(barcode); self.kind = QComboBox(); self.kind.addItems(["Código Truper","Clave","Descripción"]); self.query = QLineEdit(); search = QPushButton("Buscar")
        form.addWidget(QLabel("Barcode:")); form.addWidget(self.barcode); form.addWidget(self.kind); form.addWidget(self.query,1); form.addWidget(search); root.addLayout(form)
        self.table = QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["ID","Código","Clave","Producto","Marca","Existencia"]); self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table)
        lower = QHBoxLayout(); self.stock = QSpinBox(); self.stock.setMaximum(1_000_000); link = QPushButton("Vincular y guardar existencia"); cancel = QPushButton("Cancelar")
        lower.addWidget(QLabel("Existencia inicial:")); lower.addWidget(self.stock); lower.addStretch(); lower.addWidget(link); lower.addWidget(cancel); root.addLayout(lower)
        search.clicked.connect(self._search); self.query.returnPressed.connect(self._search); link.clicked.connect(self._link); cancel.clicked.connect(self.reject)

    def _search(self):
        try:
            text = self.query.text().strip(); kind = self.kind.currentText()
            if kind == "Descripción": products = self.service.buscar(descripcion=text, limit=100)
            else:
                field = "codigo_truper" if kind == "Código Truper" else "clave"; product = self.service.buscar_exacto(field,text); products = [product] if product else []
            self.table.setRowCount(0)
            for product in products:
                row = self.table.rowCount(); self.table.insertRow(row)
                values = [product.id,product.codigo_truper or "",product.clave or "",nombre_producto(product),product.marca or "",product.existencia]
                for col,value in enumerate(values): self.table.setItem(row,col,QTableWidgetItem(str(value)))
        except Exception as exc: show_error(self,"Error al buscar",exc)

    def _link(self):
        row = self.table.currentRow()
        if row < 0: QMessageBox.warning(self,"Seleccione producto","Seleccione el producto Truper que desea vincular."); return
        try:
            product_id = int(self.table.item(row,0).text())
            self.product = InitialInventoryService(self.database).vincular_y_capturar(product_id,self.barcode.text(),self.stock.value())
            self.accept()
        except Exception as exc: show_error(self,"No se pudo vincular",exc)


class QuickProductDialog(QDialog):
    """Alta única y reutilizable para Productos, Inventario y Punto de Venta."""
    def __init__(self, database, barcode="", parent=None):
        super().__init__(parent);self.database=database;self.service=ProductService(database);self.product=None;self._found=None
        self.setWindowTitle("Registrar producto");self.setMinimumWidth(540);form=QFormLayout(self);self.form=form
        self.mode=QComboBox()
        if TRUPER_ENABLED:self.mode.addItem("Producto Truper","TRUPER")
        self.mode.addItem("Producto externo","EXTERNAL")
        self.barcode=QLineEdit(barcode);self.code=QLineEdit();self.find=QPushButton("BUSCAR CÓDIGO TRUPER")
        code_row=QHBoxLayout();code_row.addWidget(self.code,1);code_row.addWidget(self.find)
        self.status=QLabel("Escriba el código Truper impreso en el producto.");self.status.setWordWrap(True)
        self.key=QLineEdit();self.description=QLineEdit();self.price=QLineEdit();self.variable=QCheckBox("Precio variable en cada venta");self.control=QCheckBox();_style_inventory_control(self.control,True)
        self.kind=QComboBox();self.kind.addItems(["UNIDAD","GRANEL"]);self.bulk_unit=QComboBox();self.bulk_unit.addItem("Peso (kg)","PESO");self.bulk_unit.addItem("Volumen (L)","VOLUMEN");self.stock=QLineEdit("0")
        form.addRow("Tipo de alta:",self.mode);form.addRow("Barcode:",self.barcode);form.addRow("Código Truper:",code_row);form.addRow(self.status)
        form.addRow("Clave (opcional):",self.key);form.addRow("Descripción:",self.description);form.addRow("Se vende:",self.kind);form.addRow("Unidad de granel:",self.bulk_unit)
        form.addRow("Precio de venta / sugerido: $",self.price);form.addRow(self.variable);form.addRow(self.control);form.addRow("Existencia actual:",self.stock)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);self.buttons.button(QDialogButtonBox.Save).setText("GUARDAR Y VINCULAR");self.buttons.accepted.connect(self._save);self.buttons.rejected.connect(self.reject);form.addRow(self.buttons)
        self.mode.currentIndexChanged.connect(self._refresh_mode);self.find.clicked.connect(self._lookup);self.code.returnPressed.connect(self._lookup);self.control.toggled.connect(self.stock.setEnabled);self.kind.currentTextChanged.connect(self._stock_hint);self.bulk_unit.currentIndexChanged.connect(self._stock_hint);self._refresh_mode();self.barcode.setFocus()
        if not TRUPER_ENABLED:
            for widget in (self.mode,self.code,self.status,self.key):form.setRowVisible(widget,False)
    def _refresh_mode(self):
        truper=self.mode.currentData()=="TRUPER"
        for widget in (self.code,self.find,self.status,self.key):widget.setVisible(truper)
        self.kind.setEnabled(True);self.bulk_unit.setEnabled(self.kind.currentText()=="GRANEL");self._found=None
        self.description.setReadOnly(False);self.description.setPlaceholderText("Opcional" if truper else "Obligatoria")
        self.buttons.button(QDialogButtonBox.Save).setText("GUARDAR Y VINCULAR" if truper else "GUARDAR PRODUCTO")
    def _stock_hint(self):
        bulk=self.kind.currentText()=="GRANEL";self.bulk_unit.setEnabled(bulk);self.variable.setEnabled(not bulk);self.stock.setPlaceholderText(("L" if self.bulk_unit.currentData()=="VOLUMEN" else "kg") if bulk else "piezas")
    def _lookup(self):
        code=self.code.text().strip()
        if not code:QMessageBox.warning(self,"Código requerido","Escriba el código Truper.");return
        product=self.service.buscar_exacto("codigo_truper",code);self._found=product
        if product:
            self.kind.setEnabled(True)
            self.status.setText(f"PRODUCTO TRUPER ENCONTRADO\nCódigo: {product.codigo_truper} · Clave: {product.clave or '—'}\n{product.descripcion or 'Sin descripción'}")
            self.key.setText(product.clave or "");self.description.setText(product.descripcion or "");self.key.setReadOnly(True);self.description.setReadOnly(False);self.kind.setCurrentText(product.tipo_venta)
            self.bulk_unit.setCurrentIndex(max(0,self.bulk_unit.findData(product.unidad_granel or "PESO")));self._stock_hint();self.price.setText(_decimal_text(product.precio_venta));self.variable.setChecked(product.precio_variable);suffix=" L" if product.unidad_granel=="VOLUMEN" else " kg";self.stock.setText(str(product.existencia) if product.tipo_venta=="UNIDAD" else formato_granel(product.existencia_granel_mg,product.unidad_granel or "PESO").removesuffix(suffix));self.control.setChecked(product.controla_inventario)
        else:
            self.status.setText(f"El código Truper {code} no existe actualmente en el catálogo local.\nPuede crear un PRODUCTO TRUPER mínimo.")
            self.key.setReadOnly(False);self.description.setReadOnly(False);self.key.clear();self.description.clear();self.kind.setEnabled(True);self.bulk_unit.setEnabled(True);self.kind.setCurrentText("UNIDAD")
    def _save(self):
        try:
            variable=self.variable.isChecked();price_cents=parsear_importe(self.price.text(),nombre="Precio sugerido") if self.price.text().strip() else None;price=Decimal(price_cents)/Decimal(100) if price_cents is not None else None
            if not variable and price is None:raise ValueError("El precio de venta es obligatorio para productos de precio fijo.")
            if self.mode.currentData()=="EXTERNAL":
                kind=self.kind.currentText();unit=self.bulk_unit.currentData() if kind=="GRANEL" else None;bulk=cantidad_desde_mayor(self.stock.text() or "0",unit,allow_zero=True) if kind=="GRANEL" and self.control.isChecked() else 0
                units=_whole_stock(self.stock.text()) if kind=="UNIDAD" and self.control.isChecked() else 0
                self.product=self.service.crear_producto_externo(self.barcode.text(),self.description.text(),price,units,tipo_venta=kind,unidad_granel=unit,existencia_granel_mg=bulk,controla_inventario=self.control.isChecked(),permitir_sin_barcode=True,precio_variable=variable)
            else:
                if not self.code.text().strip():raise ValueError("El código Truper es obligatorio")
                if self._found and self._found.codigo_truper==self.code.text().strip():
                    kind=self.kind.currentText();unit=self.bulk_unit.currentData() if kind=="GRANEL" else None;stock=_whole_stock(self.stock.text()) if self.control.isChecked() and kind=="UNIDAD" else None
                    bulk=cantidad_desde_mayor(self.stock.text() or "0",unit,allow_zero=True) if self.control.isChecked() and kind=="GRANEL" else None
                    replace=bool(self._found.codigo_barras and self._found.codigo_barras!=self.barcode.text().strip())
                    if replace and QMessageBox.question(self,"Confirmar revinculación",f"Barcode actual: {self._found.codigo_barras}\nBarcode nuevo: {self.barcode.text().strip()}\n\n¿Cambiar?")!=QMessageBox.Yes:return
                    self.product=self.service.alta_rapida_truper_existente(self._found.id,self.barcode.text(),price,stock,descripcion=self.description.text(),existencia_granel_mg=bulk,permitir_reemplazo=replace,tipo_venta=kind,unidad_granel=unit,controla_inventario=self.control.isChecked(),precio_variable=variable)
                else:
                    kind=self.kind.currentText();unit=self.bulk_unit.currentData() if kind=="GRANEL" else None;bulk=cantidad_desde_mayor(self.stock.text() or "0",unit,allow_zero=True) if kind=="GRANEL" and self.control.isChecked() else 0
                    self.product=self.service.crear_producto_truper_minimo(self.code.text(),self.barcode.text(),price,_whole_stock(self.stock.text()) if self.control.isChecked() and kind=="UNIDAD" else 0,descripcion=self.description.text(),clave=self.key.text(),controla_inventario=self.control.isChecked(),tipo_venta=kind,unidad_granel=unit,existencia_granel_mg=bulk,precio_variable=variable)
            self.accept()
        except Exception as exc:show_error(self,"No se pudo registrar el producto",exc)


class ProductSearchDialog(QDialog):
    def __init__(self,database,term,parent=None):
        super().__init__(parent);self.database=database;self.selected_product=None;self.selected_products=[];self._committed=False;self.setWindowTitle("Seleccionar productos");self.resize(1050,560);self.setMinimumSize(760,400)
        root=QVBoxLayout(self);root.addWidget(QLabel(f"Resultados para: {term}\nCtrl+clic selecciona filas individuales · Shift+clic selecciona un rango"));self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(["Código","Clave","Descripción","Precio","Existencia"]);self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setSelectionMode(QTableWidget.ExtendedSelection);self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(False);root.addWidget(self.table)
        result=ProductQueryService(database).buscar_inteligente(term,page_size=100)
        self.products=result.products
        for product in self.products:
            row=self.table.rowCount();self.table.insertRow(row);stock=cantidad_producto(product) if product.controla_inventario else "—"
            for col,value in enumerate((product.codigo_truper or "",product.clave or "",nombre_producto(product),precio_producto(product),stock)):
                item=QTableWidgetItem(str(value));item.setToolTip(str(value));self.table.setItem(row,col,item)
            self.table.item(row,0).setData(Qt.UserRole,product.id)
        for column,width in enumerate((100,140,500,110,110)):self.table.setColumnWidth(column,width)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText("AGREGAR SELECCIONADOS");buttons.accepted.connect(self._choose);buttons.rejected.connect(self.reject);root.addWidget(buttons)
        self.table.doubleClicked.connect(self._choose_single)
        if self.table.rowCount():self.table.selectRow(0);self.table.setFocus()
    def _choose(self,*_):
        if self._committed:return
        rows=sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows:return
        self._committed=True;service=ProductService(self.database);self.selected_products=[service.get(self.table.item(row,0).data(Qt.UserRole)) for row in rows];self.selected_product=self.selected_products[0];self.accept()
    def _choose_single(self,index):
        if self._committed:return
        self.table.clearSelection();self.table.selectRow(index.row());self._choose()


class IdentityEditDialog(QDialog):
    def __init__(self,product,field,service,parent=None):
        super().__init__(parent);self.product=product;self.field=field;self.service=service;self.saved_product=None
        label="Barcode" if field=="codigo_barras" else "Código Truper";self.setWindowTitle(f"Cambiar {label}");form=QFormLayout(self)
        form.addRow("Producto:",QLabel(nombre_producto(product)));form.addRow(f"{label} actual:",QLabel(getattr(product,field) or "—"));self.value=QLineEdit(getattr(product,field) or "");self.value.selectAll();form.addRow(f"Nuevo {label}:",self.value)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Save).setText("CAMBIAR");buttons.accepted.connect(self._save);buttons.rejected.connect(self.reject);form.addRow(buttons)
    def _save(self):
        old=getattr(self.product,self.field) or "—";new=self.value.text().strip()
        if QMessageBox.question(self,"Confirmar cambio",f"Producto: {nombre_producto(self.product)}\nAnterior: {old}\nNuevo: {new}\n\n¿Confirmar?")!=QMessageBox.Yes:return
        try:
            self.saved_product=self.service.revincular_codigo_barras(self.product.id,new) if self.field=="codigo_barras" else self.service.cambiar_codigo_truper(self.product.id,new);self.accept()
        except Exception as exc:show_error(self,"No se pudo cambiar el identificador",exc)


def _whole_stock(value):
    text=(value or "0").strip()
    if not text.isdigit():raise ValueError("La existencia debe ser un entero no negativo")
    return int(text)


class UnknownBarcodeDialog(QDialog):
    SEARCH, EXTERNAL = 10, 20
    def __init__(self, barcode, parent=None):
        super().__init__(parent); self.setWindowTitle("Producto no registrado"); layout = QVBoxLayout(self)
        label = QLabel(f"Producto no registrado\n\nCódigo: {barcode}"); label.setAlignment(Qt.AlignCenter); label.setStyleSheet("font-size:18px;font-weight:bold"); layout.addWidget(label)
        choices=(("Buscar producto Truper",self.SEARCH),("Crear producto externo",self.EXTERNAL),("Cancelar",QDialog.Rejected)) if TRUPER_ENABLED else (("Crear producto",self.EXTERNAL),("Cancelar",QDialog.Rejected))
        for text,code in choices:
            button=QPushButton(text); button.clicked.connect(lambda checked=False,c=code:self.done(c)); layout.addWidget(button)


class SaleDetailDialog(QDialog):
    def __init__(self, sale, sales_service, ticket_service, parent=None):
        super().__init__(parent); self.sale=sale; self.service=sales_service; self.tickets=ticket_service; self.setWindowTitle(f"Venta {sale.folio}"); self.resize(750,450)
        root=QVBoxLayout(self); root.addWidget(QLabel(f"{sale.folio}  |  {sale.fecha_hora}  |  {sale.estado}\nMétodo: {sale.metodo_pago}   Total: {moneda(sale.total_centavos)}"))
        table=QTableWidget(len(sale.detalles),4); table.setHorizontalHeaderLabels(["Producto","Clave","Cantidad","Subtotal"]); table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row,d in enumerate(sale.detalles):
            quantity=formato_cantidad("GRANEL",miligramos=d.cantidad_mg,unidad_granel=d.unidad_granel_snapshot or "PESO") if d.tipo_venta_snapshot=="GRANEL" else formato_cantidad("UNIDAD",unidades=d.cantidad)
            values=[d.descripcion_snapshot or d.clave_snapshot or d.codigo_truper_snapshot or str(d.producto_id),d.clave_snapshot or "",quantity,moneda(d.subtotal_centavos)]
            for col,value in enumerate(values): table.setItem(row,col,QTableWidgetItem(str(value)))
        table.horizontalHeader().setStretchLastSection(True); root.addWidget(table)
        buttons=QHBoxLayout(); open_ticket=QPushButton("ABRIR TICKET"); regenerate=QPushButton("REGENERAR TICKET"); open_ticket.clicked.connect(self._ticket); regenerate.clicked.connect(lambda:self._ticket(True)); buttons.addWidget(open_ticket); buttons.addWidget(regenerate); buttons.addStretch()
        if sale.estado=="COMPLETADA":
            cancel=QPushButton("CANCELAR VENTA"); cancel.setObjectName("danger"); cancel.clicked.connect(self._cancel); buttons.addWidget(cancel)
        close=QPushButton("Cerrar"); close.clicked.connect(self.accept); buttons.addWidget(close); root.addLayout(buttons)

    def _cancel(self):
        reason, ok = _text_prompt(self,"Cancelar venta","Motivo de cancelación:")
        if not ok or not reason.strip(): return
        if QMessageBox.question(self,"Confirmar cancelación",f"¿Cancelar {self.sale.folio} y devolver su inventario?") != QMessageBox.Yes: return
        try:
            self.sale=self.service.cancelar_venta(self.sale.id,reason); QMessageBox.information(self,"Venta cancelada",f"{self.sale.folio} fue cancelada."); self.accept()
        except Exception as exc: show_error(self,"No se pudo cancelar",exc)

    def _ticket(self,regenerate=False):
        try:
            path=self.tickets.regenerar(self.sale.id) if regenerate else self.tickets.obtener_o_generar(self.sale.id)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        except Exception as exc:show_error(self,"No se pudo abrir el ticket",exc)


class SaleCompletedDialog(QDialog):
    def __init__(self,sale,ticket_path=None,ticket_error=None,parent=None):
        super().__init__(parent); self.setWindowTitle("VENTA REALIZADA"); layout=QVBoxLayout(self)
        text=f"VENTA REALIZADA\n\nFolio: {sale.folio}\nTotal: {moneda(sale.total_centavos)}"
        if sale.efectivo_recibido_centavos is not None:text+=f"\nRecibido: {moneda(sale.efectivo_recibido_centavos)}\nCambio: {moneda(sale.cambio_centavos)}"
        if ticket_error:text+="\n\nVenta realizada correctamente, pero no fue posible generar el ticket."
        label=QLabel(text); label.setAlignment(Qt.AlignCenter); label.setStyleSheet("font-size:18px;font-weight:bold"); layout.addWidget(label)
        buttons=QHBoxLayout()
        if ticket_path:
            self.print_button=QPushButton("IMPRIMIR TICKET"); self.print_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(ticket_path.resolve())))); buttons.addWidget(self.print_button)
        self.fresh=QPushButton("NUEVA VENTA"); self.fresh.setObjectName("primary");self.fresh.setDefault(True);self.fresh.setAutoDefault(True);self.fresh.clicked.connect(self.accept); buttons.addWidget(self.fresh); layout.addLayout(buttons);self.fresh.setFocus()


def _text_prompt(parent,title,label):
    from PySide6.QtWidgets import QInputDialog
    return QInputDialog.getText(parent,title,label)
