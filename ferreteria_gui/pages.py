from decimal import Decimal

from PySide6.QtCore import QDate,QEvent,Qt, Signal, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView,QAbstractSpinBox,QApplication,QComboBox,QDateEdit,QDialog,QGridLayout,QHeaderView,QHBoxLayout,QInputDialog,QLabel,QLineEdit,
                               QMenu,QMessageBox, QPushButton, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem,QToolButton, QVBoxLayout, QWidget)

from ferreteria_core.services import BulkQuantityRequired,VariablePriceRequired, Cart,CategoryService,DailySummaryService, InsufficientStockError, InventoryService, ProductEditSession, ProductQueryService, ProductService, SalesService, TicketService
from ferreteria_core.quantity import formato_granel
from .config import PAGE_SIZE, TICKET_ROOT, TRUPER_ENABLED
from .dialogs import (BulkSaleDialog,BulkStockDialog,BulkTypeDialog,IdentityEditDialog,InventoryMovementsDialog,ProductModifyDialog,DescriptionEditDialog, ExternalProductDialog, GenericImportDialog, LinkProductDialog, PaymentDialog, PriceEditDialog,
                      ProductSearchDialog,QuickProductDialog,QuickStockDialog, SaleCompletedDialog, SaleDetailDialog, UnknownBarcodeDialog,VariablePriceDialog)
from .presentation import cantidad_producto,limpiar_estado_venta, moneda, nombre_producto, parsear_importe,precio_producto
from .widgets import show_error
import logging
import time
from .scanner import ScannerBuffer

logger=logging.getLogger("ferreteria_gui")


class PosPage(QWidget):
    def __init__(self, database, parent=None):
        super().__init__(parent); self.database=database; self.cart=Cart(database); self.sales=SalesService(database);self.scanner_buffer=ScannerBuffer()
        root=QVBoxLayout(self); title=QLabel("PUNTO DE VENTA"); title.setStyleSheet("font-size:24px;font-weight:bold")
        scan=QHBoxLayout(); scan.addWidget(QLabel("Buscar / escanear:")); self.barcode=QLineEdit(); self.barcode.setPlaceholderText("Barcode, código Truper, clave o descripción · Enter" if TRUPER_ENABLED else "Barcode, clave o descripción · Enter"); self.barcode.setStyleSheet("font-size:20px;padding:12px"); scan.addWidget(self.barcode,1)
        root.addWidget(title); root.addLayout(scan)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["Producto","Clave","Cantidad","Existencia","Precio unitario","Subtotal"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setAlternatingRowColors(True); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table,1)
        edits=QHBoxLayout(); self.plus=QPushButton("Aumentar F7"); self.minus=QPushButton("Disminuir F8");self.set_quantity_button=QPushButton("Establecer cantidad F10"); self.remove=QPushButton("Quitar F9"); self.clear=QPushButton("Cancelar venta  Ctrl+Delete"); self.clear.setObjectName("danger")
        for b in (self.plus,self.minus,self.set_quantity_button,self.remove,self.clear): edits.addWidget(b)
        edits.addStretch(); edits.addWidget(QLabel("Descuento: $")); self.discount=QLineEdit("0.00"); self.discount.setMaximumWidth(130); edits.addWidget(self.discount); root.addLayout(edits)
        totals=QHBoxLayout(); self.count=QLabel("Artículos: 0"); totals.addWidget(self.count); totals.addStretch(); self.subtotal=QLabel("Subtotal: $0.00"); self.discount_label=QLabel("Descuento: $0.00"); self.total=QLabel("TOTAL: $0.00"); self.total.setStyleSheet("font-size:30px;font-weight:bold;color:#1877c9")
        totals.addWidget(self.subtotal); totals.addSpacing(20); totals.addWidget(self.discount_label); totals.addSpacing(30); totals.addWidget(self.total); root.addLayout(totals)
        checkout=QHBoxLayout(); checkout.addStretch(); self.charge=QPushButton("COBRAR  [F4]"); self.charge.setObjectName("primary"); checkout.addWidget(self.charge); root.addLayout(checkout)
        self.barcode.returnPressed.connect(self._scan); self.plus.clicked.connect(lambda:self._change(1)); self.minus.clicked.connect(lambda:self._change(-1));self.set_quantity_button.clicked.connect(self.set_selected_quantity); self.remove.clicked.connect(self.remove_selected); self.clear.clicked.connect(self.cancel_cart); self.discount.textChanged.connect(self.refresh); self.charge.clicked.connect(self.checkout);self.table.cellDoubleClicked.connect(self._cell_double_clicked)
        QWidget.setTabOrder(self.barcode,self.table);QWidget.setTabOrder(self.table,self.plus);QWidget.setTabOrder(self.plus,self.minus);QWidget.setTabOrder(self.minus,self.remove);QWidget.setTabOrder(self.remove,self.discount);QWidget.setTabOrder(self.discount,self.charge)
        QApplication.instance().installEventFilter(self);QTimer.singleShot(0,self.focus_scanner)

    def focus_scanner(self): self.barcode.setFocus(); self.barcode.selectAll()
    def _scan(self):
        term=self.barcode.text().strip(); self.barcode.clear();self._process_term(term)
    def _process_term(self,term):
        if not term: return
        try:
            item=self.cart.agregar_por_barcode(term); self.refresh(preserve_id=item.producto_id)
        except BulkQuantityRequired as exc:
            dialog=BulkSaleDialog(exc.product,self)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                try:self.cart.agregar_granel(exc.product.id,dialog.cantidad_mg);self.refresh(preserve_id=exc.product.id)
                except Exception as error:show_error(self,"No se pudo agregar",error)
        except VariablePriceRequired as exc:self._add_variable(exc.product)
        except InsufficientStockError as exc:self._resolve_stock(exc)
        except LookupError:
            result=ProductQueryService(self.database).buscar_inteligente(term,page_size=100)
            if result.products:
                product=result.products[0]
                if len(result.products)>1 and not result.exact_match:
                    selector=ProductSearchDialog(self.database,term,self)
                    if selector.exec()!=QDialog.DialogCode.Accepted:return
                    self._add_products(selector.selected_products);return
                self._add_product(product)
            else:
                dialog=UnknownBarcodeDialog(term,self);action=dialog.exec()
                if action in (UnknownBarcodeDialog.SEARCH,UnknownBarcodeDialog.EXTERNAL):
                    target=QuickProductDialog(self.database,term,self)
                    if action==UnknownBarcodeDialog.EXTERNAL:target.mode.setCurrentIndex(1)
                    if target.exec()==QDialog.DialogCode.Accepted:self._add_product(target.product)
        except Exception as exc: show_error(self,"No se pudo agregar el producto",exc)

    def eventFilter(self,obj,event):
        if event.type()!=QEvent.KeyPress or not self.isVisible():return super().eventFilter(obj,event)
        focus=QApplication.focusWidget()
        if QApplication.activeModalWidget() is not None or isinstance(focus,(QLineEdit,QAbstractSpinBox)):
            self.scanner_buffer.reset();return super().eventFilter(obj,event)
        if event.key() in (Qt.Key_Return,Qt.Key_Enter):
            value=self.scanner_buffer.finish(time.monotonic())
            if value:self._process_term(value);return True
            return super().eventFilter(obj,event)
        text=event.text()
        if text:self.scanner_buffer.character(text,time.monotonic())
        else:self.scanner_buffer.reset()
        return super().eventFilter(obj,event)

    def _add_product(self,product):
        try:
            self.cart.agregar_producto(product.id);self.refresh(preserve_id=product.id)
        except BulkQuantityRequired:
            dialog=BulkSaleDialog(product,self)
            if dialog.exec()==QDialog.DialogCode.Accepted:self.cart.agregar_granel(product.id,dialog.cantidad_mg);self.refresh(preserve_id=product.id)
        except VariablePriceRequired:self._add_variable(product)
        except InsufficientStockError as exc:self._resolve_stock(exc)
        except Exception as exc:show_error(self,"No se pudo agregar el producto",exc)

    def _add_variable(self,product):
        dialog=VariablePriceDialog(product,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        try:
            item=self.cart.agregar_producto(product.id,dialog.cantidad,dialog.precio_unitario_centavos);self.refresh(preserve_id=item.linea_id)
        except InsufficientStockError as exc:self._resolve_stock(exc)
        except Exception as exc:show_error(self,"No se pudo agregar el producto",exc)

    def _add_products(self,products):
        """Agrega secuencialmente; cancelar un diálogo GRANEL omite sólo esa línea."""
        for product in products:self._add_product(product)
        self.refresh(preserve_id=products[-1].id if products else None)

    def refresh(self,preserve_id=None,preserve_scroll=None):
        if preserve_id is None:preserve_id=self._selected_line()
        if preserve_scroll is None:preserve_scroll=self.table.verticalScrollBar().value()
        self.table.setRowCount(0)
        selected_row=None
        for item in self.cart.items:
            product=ProductService(self.database).get(item.producto_id); row=self.table.rowCount(); self.table.insertRow(row)
            bulk=item.tipo_venta=="GRANEL";quantity=cantidad_producto(product,item.cantidad_mg if bulk else item.cantidad);available=cantidad_producto(product,item.existencia_granel_mg if bulk else item.existencia) if product.controla_inventario else "—"
            at_limit=product.controla_inventario and (item.cantidad_mg==item.existencia_granel_mg if bulk else item.cantidad==item.existencia);stock=f"{available} (LÍMITE)" if at_limit else available
            values=[nombre_producto(product),product.clave or "",quantity,stock,moneda(item.precio_unitario_centavos) if item.precio_variable else precio_producto(product),moneda(item.subtotal_centavos)]
            for col,value in enumerate(values): self.table.setItem(row,col,QTableWidgetItem(str(value)))
            self.table.item(row,0).setData(Qt.UserRole,item.linea_id)
            if item.linea_id==preserve_id or item.producto_id==preserve_id:selected_row=row
            if at_limit:
                for col in range(6): self.table.item(row,col).setBackground(Qt.GlobalColor.yellow)
        try: discount=parsear_importe(self.discount.text(),nombre="Descuento")
        except ValueError: discount=0
        total=max(0,self.cart.total_centavos-discount); self.count.setText(f"Artículos: {self.cart.cantidad_articulos}"); self.subtotal.setText(f"Subtotal: {moneda(self.cart.total_centavos)}"); self.discount_label.setText(f"Descuento: {moneda(discount)}"); self.total.setText(f"TOTAL: {moneda(total)}")
        if selected_row is not None:self.table.selectRow(selected_row);self.table.setCurrentCell(selected_row,2)
        self.table.verticalScrollBar().setValue(preserve_scroll)

    def _selected_id(self):
        row=self.table.currentRow()
        value=self.table.item(row,0).data(Qt.UserRole) if row>=0 else None
        return value[0] if isinstance(value,tuple) else value
    def _selected_line(self):
        row=self.table.currentRow()
        return self.table.item(row,0).data(Qt.UserRole) if row>=0 else None
    def _change(self,delta):
        line_id=self._selected_line()
        if line_id is None: QMessageBox.information(self,"Carrito","Selecciona un producto del carrito.");return
        try:
            current=self.cart.item(line_id);product_id=current.producto_id
            product=ProductService(self.database).get(product_id)
            if product.tipo_venta=="GRANEL":
                dialog=BulkSaleDialog(product,self)
                suffix=" L" if product.unidad_granel=="VOLUMEN" else " kg";dialog.quantity.setText(cantidad_producto(product,current.cantidad_mg).removesuffix(suffix));dialog._from_quantity()
                if dialog.exec()!=QDialog.DialogCode.Accepted:return
                self.cart.establecer_peso(product_id,dialog.cantidad_mg)
            elif delta>0:self.cart.incrementar_linea(line_id)
            else:self.cart.decrementar_linea(line_id)
            self.refresh(preserve_id=line_id)
        except InsufficientStockError as exc:self._resolve_stock(exc)
        except Exception as exc: show_error(self,"No se pudo cambiar la cantidad",exc)

    def set_selected_quantity(self):
        line_id=self._selected_line()
        if line_id is None:QMessageBox.information(self,"Carrito","Selecciona un producto del carrito.");return
        current=self.cart.item(line_id);product_id=current.producto_id;product=ProductService(self.database).get(product_id)
        try:
            if product.tipo_venta=="GRANEL":
                dialog=BulkSaleDialog(product,self);suffix=" L" if product.unidad_granel=="VOLUMEN" else " kg";dialog.quantity.setText(cantidad_producto(product,current.cantidad_mg).removesuffix(suffix));dialog._from_quantity()
                if dialog.exec()!=QDialog.DialogCode.Accepted:return
                self.cart.establecer_peso(product_id,dialog.cantidad_mg)
            else:
                quantity,ok=QInputDialog.getInt(self,"Establecer cantidad",f"Producto: {nombre_producto(product)}\nCantidad actual: {current.cantidad}\n\nNueva cantidad:",current.cantidad,1,1_000_000)
                if not ok:return
                self.cart.establecer_cantidad_linea(line_id,quantity)
            self.refresh(preserve_id=line_id)
        except InsufficientStockError as exc:self._resolve_stock(exc)
        except Exception as exc:show_error(self,"No se pudo establecer la cantidad",exc)

    def _cell_double_clicked(self,row,column):
        if column==2:
            self.table.selectRow(row);self.set_selected_quantity()
        elif column==4:
            self.table.selectRow(row);self.edit_selected_price()
    def edit_selected_price(self):
        line_id=self._selected_line()
        if line_id is None:return
        item=self.cart.item(line_id);product=ProductService(self.database).get(item.producto_id)
        if not product.precio_variable:return
        dialog=VariablePriceDialog(product,self,current_price=item.precio_unitario_centavos,quantity=item.cantidad,price_only=True)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            new_item=self.cart.cambiar_precio_linea(line_id,dialog.precio_unitario_centavos);self.refresh(preserve_id=new_item.linea_id)
    def _resolve_stock(self,exc):
        dialog=BulkStockDialog(exc.product,"AJUSTE",self) if exc.product.tipo_venta=="GRANEL" else QuickStockDialog(self.database,exc.product,exc.requested,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            try:
                if exc.product.tipo_venta=="GRANEL":
                    InventoryService(self.database).ajustar_existencia_granel(exc.product.id,dialog.cantidad_mg,dialog.note.text());self.cart.establecer_peso(exc.product.id,exc.requested)
                else:self.cart.establecer_cantidad(exc.product.id,exc.requested)
                self.refresh(preserve_id=exc.product.id)
            except Exception as retry:show_error(self,"Existencia insuficiente",retry)
    def remove_selected(self):
        row=self.table.currentRow();line_id=self._selected_line();scroll=self.table.verticalScrollBar().value()
        if line_id is not None:
            try:
                self.cart.eliminar_linea(line_id);self.refresh(preserve_scroll=scroll)
                if self.table.rowCount():self.table.selectRow(min(row,self.table.rowCount()-1));self.table.setCurrentCell(min(row,self.table.rowCount()-1),2)
            except Exception as exc:show_error(self,"No se pudo quitar",exc)
    def cancel_cart(self):
        if not self.cart.items:return
        if QMessageBox.question(self,"Cancelar venta actual","¿Desea cancelar la venta actual y vaciar el carrito?")!=QMessageBox.Yes:return
        limpiar_estado_venta(self.cart,self.discount,self.barcode); self.refresh(); self.focus_scanner()
    def checkout(self):
        try:
            if not self.cart.items: raise ValueError("El carrito está vacío")
            discount=parsear_importe(self.discount.text(),nombre="Descuento")
            if discount>self.cart.total_centavos: raise ValueError("El descuento no puede superar el subtotal")
            dialog=PaymentDialog(self.cart.total_centavos-discount,self)
            result=dialog.exec()
            if result != QDialog.DialogCode.Accepted: self.focus_scanner(); return
            payment=dialog.payment; received=Decimal(payment.recibido_centavos)/Decimal(100) if payment.recibido_centavos is not None else None
            sale=self.sales.crear_venta(self.cart.como_items_venta(),dialog.method.currentText(),received,Decimal(discount)/Decimal(100))
            ticket_path=ticket_error=None
            try:ticket_path=TicketService(self.database,TICKET_ROOT).generar_para_venta(sale)
            except Exception as exc:
                ticket_error=exc; logger.exception("Venta %s completada, pero falló su ticket",sale.folio)
            SaleCompletedDialog(sale,ticket_path,ticket_error,self).exec()
            limpiar_estado_venta(self.cart,self.discount,self.barcode); self.refresh()
        except Exception as exc:
            title="Existencia insuficiente" if str(exc).startswith("Stock insuficiente") else "No se pudo completar la venta"
            show_error(self,title,exc)
        self.focus_scanner()


class PaginatedProductsPage(QWidget):
    FILTERS=[("Todos activos","TODOS"),("Inactivos","INACTIVOS"),("Con control de inventario","CON_CONTROL"),("Sin control de inventario","SIN_CONTROL"),("Unidad","UNIDAD"),("Granel","GRANEL"),("Con existencia","CON_EXISTENCIA"),("Sin existencia","SIN_EXISTENCIA"),("Con precio","CON_PRECIO"),("Sin precio","SIN_PRECIO"),("Con descripción","CON_DESCRIPCION"),("Sin descripción","SIN_DESCRIPCION"),("Truper","TRUPER"),("Externos","EXTERNOS"),("Requieren revisión","REVISION")]
    def __init__(self,database,title,headers,sort_columns,parent=None,auto_load=True):
        super().__init__(parent); self.database=database; self.products=ProductService(database); self.queries=ProductQueryService(database); self.page=1; self.result=None; self.selection_buttons=[];self.sort_columns=sort_columns;self.sort_column="descripcion";self.sort_direction="ASC";self._loaded=False
        root=QVBoxLayout(self); heading=QLabel(title); heading.setStyleSheet("font-size:24px;font-weight:bold"); root.addWidget(heading)
        bar=QHBoxLayout(); self.query=QLineEdit(); self.query.setPlaceholderText("Buscar o escanear producto..."); search=QPushButton("Buscar");self.filter=QComboBox();filters=self.FILTERS if TRUPER_ENABLED else [item for item in self.FILTERS if item[1] not in {"TRUPER","EXTERNOS","REVISION"}];[self.filter.addItem(label,value) for label,value in filters];bar.addWidget(self.query,1);bar.addWidget(search);bar.addWidget(QLabel("Filtro:"));bar.addWidget(self.filter);root.addLayout(bar)
        self.table=QTableWidget(0,len(headers)); self.table.setHorizontalHeaderLabels(headers); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.table.setAlternatingRowColors(True); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive);self.table.horizontalHeader().setMinimumSectionSize(55);root.addWidget(self.table,1)
        pager=QHBoxLayout(); self.first=QPushButton("<< Primera"); self.previous=QPushButton("< Anterior"); self.page_label=QLabel("Página 1 de 1"); self.next=QPushButton("Siguiente >"); self.last=QPushButton("Última >>"); self.range_label=QLabel("Mostrando 0 de 0 productos")
        for widget in (self.first,self.previous,self.page_label,self.next,self.last):pager.addWidget(widget)
        pager.addStretch(); pager.addWidget(self.range_label); root.addLayout(pager)
        self.table.horizontalHeader().setSortIndicatorShown(True);self.table.horizontalHeader().setSortIndicator(3,Qt.AscendingOrder);self.table.horizontalHeader().sectionClicked.connect(self._sort);search.clicked.connect(self._submit_search); self.query.returnPressed.connect(self._submit_search); self.query.textChanged.connect(self._term_changed);self.filter.currentIndexChanged.connect(self._filter_changed); self.first.clicked.connect(lambda:self.go_page(1)); self.previous.clicked.connect(lambda:self.go_page(self.page-1)); self.next.clicked.connect(lambda:self.go_page(self.page+1)); self.last.clicked.connect(self.go_last); self.table.itemSelectionChanged.connect(self._selection_changed)
        if auto_load:QTimer.singleShot(0,self.reload)
    def ensure_loaded(self):
        if not self._loaded:self.reload()
    def _term_changed(self,text):
        self.page=1; self.table.clearSelection(); self._selection_changed()
        if not text.strip():self.reload()
    def start_search(self):self.page=1; self.reload()
    def _submit_search(self):self.start_search();self.after_search()
    def after_search(self):pass
    def _filter_changed(self):self.page=1;self.table.clearSelection();self.reload()
    def _sort(self,index):
        column=self.sort_columns[index]
        if column==self.sort_column:self.sort_direction="DESC" if self.sort_direction=="ASC" else "ASC"
        else:self.sort_column=column;self.sort_direction="ASC"
        self.table.horizontalHeader().setSortIndicator(index,Qt.AscendingOrder if self.sort_direction=="ASC" else Qt.DescendingOrder);self.page=1;self.table.clearSelection();self.reload()
    def go_page(self,page):
        if self.result and 1<=page<=self.result.pages:self.page=page; self.reload()
    def go_last(self):
        if self.result:self.go_page(self.result.pages)
    def reload(self,preserve_id=None):
        try:
            if preserve_id is None:
                selected=self.selected_product(); preserve_id=selected.id if selected else None
            self.result=self.queries.buscar_inteligente(self.query.text(),page=self.page,page_size=PAGE_SIZE,product_filter=self.filter.currentData(),sort_column=self.sort_column,sort_direction=self.sort_direction)
            if self.result.exact_match and self.result.products:preserve_id=self.result.products[0].id
            self._fill(self.result.products,preserve_id); self.page_label.setText(f"Página {self.result.page} de {self.result.pages}"); self.range_label.setText(f"Mostrando {self.result.start}-{self.result.end} de {self.result.total:,} productos")
            self.first.setEnabled(self.page>1); self.previous.setEnabled(self.page>1); self.next.setEnabled(self.page<self.result.pages); self.last.setEnabled(self.page<self.result.pages)
            self._loaded=True
        except Exception as exc:show_error(self,"Error de búsqueda",exc)
    def _fill(self,products,preserve_id=None):
        self.table.clearSelection(); self.table.setRowCount(0); restore_row=None
        for product in products:
            row=self.table.rowCount(); self.table.insertRow(row)
            for col,value in enumerate(self.row_values(product)):
                item=QTableWidgetItem(str(value));item.setToolTip(str(value));self.table.setItem(row,col,item)
            self.table.item(row,0).setData(Qt.UserRole,product.id)
            if product.id==preserve_id:restore_row=row
        if restore_row is not None:self.table.selectRow(restore_row)
        self._selection_changed()
    def row_values(self,product):raise NotImplementedError
    def selected_product(self):
        row=self.table.currentRow()
        return self.products.get(self.table.item(row,0).data(Qt.UserRole)) if row>=0 and self.table.item(row,0) else None
    def selected_products(self):
        ids=[]
        for index in self.table.selectionModel().selectedRows():
            item=self.table.item(index.row(),0)
            if item:ids.append(item.data(Qt.UserRole))
        return [self.products.get(product_id) for product_id in ids]
    def register_selection_button(self,button):self.selection_buttons.append(button); button.setEnabled(False)
    def _selection_changed(self):
        enabled=self.table.currentRow()>=0
        for button in self.selection_buttons:button.setEnabled(enabled)
    def refresh_preserve(self,product_id):self.reload(preserve_id=product_id)
    def focus_search(self):
        if self.table.state()==QAbstractItemView.State.EditingState:return
        self.query.setFocus();self.query.selectAll()
    def focus_search_deferred(self):QTimer.singleShot(0,self.focus_search)


class LegacyProductsPage(PaginatedProductsPage):
    def __init__(self,database,parent=None,auto_load=True):
        super().__init__(database,"PRODUCTOS Y PRECIOS",["Código Truper","Barcode","Clave","Descripción","Marca","Categoría","Tipo de venta","Precio","Activo"],["codigo_truper","codigo_barras","clave","descripcion","marca","categoria","tipo_venta","precio_venta","activo"],parent,auto_load)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.edit_session=ProductEditSession(database);self.edit_mode=False;self._filling=False
        self.edit_banner=QLabel("MODO EDICIÓN DESACTIVADO");self.edit_banner.setAlignment(Qt.AlignCenter);self.edit_banner.setStyleSheet("font-size:16px;font-weight:bold;padding:8px;background:#e5e7eb");self.layout().insertWidget(1,self.edit_banner)
        self.selected_label=QLabel("Seleccionados: 0");self.selected_label.setStyleSheet("font-weight:bold");self.layout().insertWidget(3,self.selected_label)
        actions=QGridLayout(); self.edit_description=QPushButton("Editar descripción");self.edit_price=QPushButton("Editar precio");self.bulk=QPushButton("Editar seleccionados");self.mode=QPushButton("ACTIVAR MODO EDICIÓN");self.review=QPushButton("Revisar cambios");self.save_changes=QPushButton("Guardar cambios");self.discard=QPushButton("Descartar"); link=QPushButton("Vincular barcode"); external=QPushButton("Crear producto");import_button=QPushButton("Importar productos");
        for index,(button,icon) in enumerate(((self.edit_description,QStyle.SP_FileDialogDetailedView),(self.edit_price,QStyle.SP_DialogApplyButton),(link,QStyle.SP_DialogOpenButton),(external,QStyle.SP_FileDialogNewFolder),(import_button,QStyle.SP_DriveHDIcon))):button.setIcon(self.style().standardIcon(icon));button.setProperty("class","action");actions.addWidget(button,index//3,index%3)
        self.layout().addLayout(actions); self.register_selection_button(self.edit_description);self.register_selection_button(self.edit_price)
        for button in (self.bulk,self.mode,self.review,self.save_changes,self.discard):actions.addWidget(button)
        self.register_selection_button(self.bulk);self.edit_description.clicked.connect(self._edit_description);self.edit_price.clicked.connect(self._edit_price);self.bulk.clicked.connect(self._bulk);self.mode.clicked.connect(self.toggle_edit_mode);self.review.clicked.connect(self._review);self.save_changes.clicked.connect(self._save_pending);self.discard.clicked.connect(self._discard_pending); link.clicked.connect(self._link); external.clicked.connect(self._external);import_button.clicked.connect(self._import);self.table.itemChanged.connect(self._item_changed);self._update_edit_state()
    def row_values(self,p):
        price=("" if p.precio_venta is None else f"{Decimal(p.precio_venta)/Decimal(100):.2f}") if self.edit_mode else precio_producto(p)
        return [p.codigo_truper or "",p.codigo_barras or "",p.clave or "",p.descripcion or "",p.marca or "",p.categoria or "",_tipo_venta_label(p),price,"Sí" if p.activo else "No"]
    def _selection_changed(self):
        super()._selection_changed()
        if hasattr(self,"selected_label"):self.selected_label.setText(f"Seleccionados: {len(self.table.selectionModel().selectedRows())}")
    def _fill(self,products,preserve_id=None):
        self._filling=True
        try:
            super()._fill(products,preserve_id)
            editable={3,5,6,7} if self.edit_mode else set()
            for row in range(self.table.rowCount()):
                for col in range(self.table.columnCount()):
                    item=self.table.item(row,col);item.setFlags(item.flags()|Qt.ItemIsEditable if col in editable else item.flags()&~Qt.ItemIsEditable)
        finally:self._filling=False
    def _item_changed(self,item):
        if self._filling or not self.edit_mode or item.column() not in {3,5,6,7}:return
        product_id=self.table.item(item.row(),0).data(Qt.UserRole);field={3:"descripcion",5:"categoria",6:"tipo_venta",7:"precio_venta"}[item.column()];value=item.text().replace("$","").replace("/ kg","").replace(",","").strip()
        try:self.edit_session.set(product_id,field,value);self._update_edit_state()
        except Exception as exc:show_error(self,"Cambio inválido",exc);self.reload(preserve_id=product_id)
    def toggle_edit_mode(self):
        if self.edit_mode and self.edit_session.has_changes:
            answer=QMessageBox.question(self,"Cambios pendientes","Hay cambios sin guardar. ¿Descartarlos y salir del modo edición?")
            if answer!=QMessageBox.Yes:return
            self.edit_session.discard()
        self.edit_mode=not self.edit_mode;self._update_edit_state();self.reload()
    def _update_edit_state(self):
        if not hasattr(self,"edit_banner"):return
        if self.edit_mode:self.edit_banner.setText(f"*** MODO EDICIÓN ACTIVO ***   {self.edit_session.count} cambios pendientes");self.edit_banner.setStyleSheet("font-size:16px;font-weight:bold;padding:8px;background:#fbbf24;color:#111827");self.mode.setText("DESACTIVAR MODO EDICIÓN")
        else:self.edit_banner.setText("MODO EDICIÓN DESACTIVADO");self.edit_banner.setStyleSheet("font-size:16px;font-weight:bold;padding:8px;background:#e5e7eb");self.mode.setText("ACTIVAR MODO EDICIÓN")
        self.review.setEnabled(self.edit_session.has_changes);self.save_changes.setEnabled(self.edit_session.has_changes);self.discard.setEnabled(self.edit_session.has_changes)
    def _review(self):
        changes=self.edit_session.changes();text="\n".join(f"Producto {c.producto_id} · {c.campo}: {ProductEditSession.display(c)}" for c in changes)
        if any(c.campo=="tipo_venta" and c.anterior=="UNIDAD" and c.nuevo=="GRANEL" for c in changes):text+="\n\nAVISO: los precios actuales se interpretarán por kilogramo."
        QMessageBox.information(self,"Revisar cambios",text or "No hay cambios pendientes")
    def _save_pending(self):
        try:
            self._review()
            if QMessageBox.question(self,"Guardar cambios",f"¿Aplicar {self.edit_session.count} cambios a {self.edit_session.product_count} productos?")!=QMessageBox.Yes:return
            self.edit_session.save();self._update_edit_state();self.reload()
        except Exception as exc:show_error(self,"No se guardó ningún cambio",exc)
    def _discard_pending(self):
        if self.edit_session.has_changes and QMessageBox.question(self,"Descartar cambios","¿Descartar todos los cambios pendientes?")!=QMessageBox.Yes:return
        self.edit_session.discard();self._update_edit_state();self.reload()
    def confirm_context_change(self):
        if not self.edit_session.has_changes:return True
        box=QMessageBox(self);box.setWindowTitle("Cambios pendientes");box.setText("Hay cambios sin guardar.");box.setInformativeText("Guarde o descarte los cambios antes de continuar.");box.setStandardButtons(QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel);box.setDefaultButton(QMessageBox.Cancel);answer=box.exec()
        if answer==QMessageBox.Save:
            try:self.edit_session.save();self._update_edit_state();return True
            except Exception as exc:show_error(self,"No se guardó ningún cambio",exc);return False
        if answer==QMessageBox.Discard:self.edit_session.discard();self._update_edit_state();return True
        return False
    def start_search(self):
        if self.confirm_context_change():super().start_search()
    def _filter_changed(self):
        if self.confirm_context_change():super()._filter_changed()
    def _sort(self,index):
        if self.confirm_context_change():super()._sort(index)
    def go_page(self,page):
        if self.confirm_context_change():super().go_page(page)
    def _term_changed(self,text):
        if text.strip():self.page=1;return
        if self.confirm_context_change():super()._term_changed(text)
    def _bulk(self):
        products=self.selected_products();dialog=BulkTypeDialog(len(products),self)
        if not products or dialog.exec()!=QDialog.DialogCode.Accepted:return
        field,value,bulk_unit=dialog.change();label={"tipo_venta":value,"activo":"ACTIVO" if value else "INACTIVO","categoria":value or "(vacía)"}[field]
        extra="\nLos precios individuales permanecerán sin cambios." if field=="tipo_venta" else ""
        if QMessageBox.question(self,"Confirmar cambio masivo",f"Se modificarán {len(products)} productos: {label}.{extra}")!=QMessageBox.Yes:return
        try:
            changes={p.id:{field:value} for p in products}
            if field=="tipo_venta":
                for fields in changes.values():fields["unidad_granel"]=bulk_unit
            self.products.aplicar_cambios(changes);self.reload()
        except Exception as exc:show_error(self,"No se aplicó ningún cambio",exc)
    def _edit_price(self):
        product=self.selected_product()
        if product and PriceEditDialog(product,self.products,self).exec()==QDialog.DialogCode.Accepted:self.refresh_preserve(product.id)
    def _edit_description(self):
        product=self.selected_product()
        if product and DescriptionEditDialog(product,self.products,self).exec()==QDialog.DialogCode.Accepted:self.refresh_preserve(product.id)
    def _link(self):
        dialog=LinkProductDialog(self.database,parent=self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.reload(preserve_id=dialog.product.id)
    def _external(self):
        dialog=ExternalProductDialog(self.products,parent=self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.reload(preserve_id=dialog.product.id)
    def _import(self):
        dialog=GenericImportDialog(self.database,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.page=1;self.reload()


class ProductsPage(PaginatedProductsPage):
    EDITABLE={3:"descripcion",5:"precio_proveedor",6:"porcentaje_ganancia",7:"precio_venta"}
    def __init__(self,database,parent=None,auto_load=True):
        if TRUPER_ENABLED:
            headers=["Código","Barcode","Clave","Descripción","Tipo de venta","Precio proveedor","Ganancia %","Precio venta","Control inventario","Activo"];sorts=["codigo_truper","codigo_barras","clave","descripcion","tipo_venta","precio_proveedor","porcentaje_ganancia","precio_venta","controla_inventario","activo"]
        else:
            headers=["Código","Barcode","Descripción","Categoría","Costo","Precio venta","Existencia","Stock mínimo","Activo"];sorts=["clave","codigo_barras","descripcion","categoria_id","precio_proveedor","precio_venta","existencia","stock_minimo","activo"]
        super().__init__(database,"PRODUCTOS Y PRECIOS",headers,sorts,parent,auto_load)
        self.EDITABLE={3:"descripcion",5:"precio_proveedor",6:"porcentaje_ganancia",7:"precio_venta"} if TRUPER_ENABLED else {2:"descripcion",4:"precio_proveedor",5:"precio_venta"}
        self._filling=False;self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked|QAbstractItemView.EditTrigger.EditKeyPressed);self.table.setColumnWidth(3,330);self.table.verticalHeader().setDefaultSectionSize(38);self.table.setItemDelegate(ReadableEditDelegate(self.table));self.selected_label=QLabel("Seleccionados: 0");self.selected_label.setStyleSheet("font-weight:bold");self.layout().insertWidget(3,self.selected_label)
        actions=QHBoxLayout();self.new_button=QPushButton("NUEVO  F1");self.modify_button=QPushButton("MODIFICAR  F3");self.delete_button=QPushButton("ELIMINAR  F6");self.import_button=QPushButton("IMPORTAR");self.more=QToolButton();self.more.setText("MÁS ACCIONES ▼");self.more.setPopupMode(QToolButton.InstantPopup)
        menu=QMenu(self.more);self.barcode_action=menu.addAction("Cambiar / revincular barcode");self.code_action=menu.addAction("Cambiar código Truper") if TRUPER_ENABLED else None;self.stock_action=menu.addAction("Ajustar existencia");self.type_action=menu.addAction("Cambiar tipo de venta");self.active_action=menu.addAction("Activar / desactivar");self.more.setMenu(menu)
        for button in (self.new_button,self.modify_button,self.delete_button,self.import_button,self.more):button.setProperty("class","action");actions.addWidget(button)
        actions.addStretch();self.layout().insertLayout(1,actions);self.register_selection_button(self.modify_button);self.register_selection_button(self.delete_button);self.new_button.clicked.connect(self._new);self.modify_button.clicked.connect(self._modify);self.delete_button.clicked.connect(self._delete_product);self.import_button.clicked.connect(self._import);self.barcode_action.triggered.connect(self._change_barcode);self.stock_action.triggered.connect(self._adjust_stock);self.type_action.triggered.connect(self._change_type);self.active_action.triggered.connect(self._change_active);self.table.itemChanged.connect(self._direct_edit)
        if self.code_action:self.code_action.triggered.connect(self._change_code)
    def row_values(self,p):
        if not TRUPER_ENABLED:
            category=CategoryService(self.database).obtener(p.categoria_id) if p.categoria_id else None
            existence=cantidad_producto(p) if p.controla_inventario else "—";minimum=(formato_granel(p.stock_minimo_granel_mg,p.unidad_granel or "PESO") if p.tipo_venta=="GRANEL" else str(p.stock_minimo)) if p.controla_inventario else "—"
            return [p.clave or "",p.codigo_barras or "",p.descripcion or "",category.nombre if category else "Sin categoría",moneda(p.precio_proveedor),precio_producto(p),existence,minimum,"Sí" if p.activo else "No"]
        return [p.codigo_truper or "",p.codigo_barras or "",p.clave or "",p.descripcion or "",_tipo_venta_label(p),moneda(p.precio_proveedor),f"{p.porcentaje_ganancia}%" if p.porcentaje_ganancia is not None else "—",precio_producto(p),"Sí" if p.controla_inventario else "No","Sí" if p.activo else "No"]
    def _fill(self,products,preserve_id=None):
        self._filling=True
        try:
            super()._fill(products,preserve_id)
            for row in range(self.table.rowCount()):
                for col in range(self.table.columnCount()):
                    item=self.table.item(row,col);item.setFlags(item.flags()|Qt.ItemIsEditable if col in self.EDITABLE else item.flags()&~Qt.ItemIsEditable)
        finally:self._filling=False
    def _selection_changed(self):
        super()._selection_changed()
        if hasattr(self,"selected_label"):self.selected_label.setText(f"Seleccionados: {len(self.table.selectionModel().selectedRows())}")
    def _direct_edit(self,item):
        if self._filling or item.column() not in self.EDITABLE:return
        product_id=self.table.item(item.row(),0).data(Qt.UserRole);field=self.EDITABLE[item.column()];raw=item.text().replace("$","").replace("/ kg","").replace("%","").replace(",","").strip()
        try:
            if field=="descripcion":self.products.actualizar_descripcion_producto(product_id,raw)
            elif field=="precio_proveedor":self.products.actualizar_precio_proveedor(product_id,_optional_decimal_ui(raw))
            elif field=="porcentaje_ganancia":self.products.actualizar_porcentaje_ganancia(product_id,raw or None)
            else:self.products.actualizar_precio_venta(product_id,_optional_decimal_ui(raw))
            self.refresh_preserve(product_id)
        except Exception as exc:show_error(self,"No se guardó el cambio",exc);self.refresh_preserve(product_id)
    def _new(self):
        dialog=QuickProductDialog(self.database,parent=self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.reload(preserve_id=dialog.product.id)
        self.query.setFocus();self.query.selectAll()
    def _modify(self):
        product=self.selected_product()
        if product and ProductModifyDialog(product,self.products,self).exec()==QDialog.DialogCode.Accepted:self.refresh_preserve(product.id)
        self.query.setFocus();self.query.selectAll()
    def _import(self):
        dialog=GenericImportDialog(self.database,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.page=1;self.reload()
    def after_search(self):
        term=self.query.text().strip()
        if term and self.result and not self.result.products and _looks_scanned(term):
            dialog=QuickProductDialog(self.database,term,self)
            if dialog.exec()==QDialog.DialogCode.Accepted:self.query.clear();self.reload(preserve_id=dialog.product.id)
        elif self.result and self.result.exact_match and self.result.products:self.table.selectRow(0)
        self.query.setFocus();self.query.selectAll()
    def _change_barcode(self):self._identity("codigo_barras")
    def _change_code(self):self._identity("codigo_truper")
    def _identity(self,field):
        product=self.selected_product()
        if not product:QMessageBox.information(self,"Seleccione producto","Seleccione una fila.");return
        dialog=IdentityEditDialog(product,field,self.products,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.refresh_preserve(product.id)
        self.query.setFocus();self.query.selectAll()
    def _adjust_stock(self):
        product=self.selected_product()
        if not product:QMessageBox.information(self,"Seleccione producto","Seleccione una fila.");return
        _adjust_product_stock(self.database,product,self)
        self.refresh_preserve(product.id)
        self.query.setFocus();self.query.selectAll()
    def _delete_product(self):
        product=self.selected_product()
        if not product:QMessageBox.information(self,"Seleccione producto","Seleccione una fila.");return
        try:
            state=self.products.estado_eliminacion(product.id)
            if state["puede_eliminar"]:message=f"Esta acción eliminará definitivamente {nombre_producto(product)} porque no tiene historial."
            else:message=f"Este producto tiene historial ({state['ventas']} ventas, {state['compras']} compras, {state['movimientos']} movimientos) y no puede eliminarse. Se DESACTIVARÁ."
            if QMessageBox.question(self,"Eliminar producto",message+"\n\n¿Continuar?")!=QMessageBox.Yes:return
            result=self.products.eliminar_o_desactivar(product.id);QMessageBox.information(self,"Producto",f"Producto {result['accion'].lower()} correctamente.");self.reload()
        except Exception as exc:show_error(self,"No se pudo eliminar/desactivar",exc)
    def _change_type(self):
        selected=self.selected_products()
        if not selected:QMessageBox.warning(self,"Seleccione productos","Seleccione una o más filas.");return
        kind,ok=QInputDialog.getItem(self,"Cambiar tipo de venta",f"Se modificarán {len(selected)} productos. Nuevo tipo:",["UNIDAD","GRANEL"],0,False)
        if not ok:return
        bulk_unit=None
        if kind=="GRANEL":
            label,ok=QInputDialog.getItem(self,"Unidad de granel","¿Cómo se medirá el producto?",["Peso (kg)","Volumen (L)"],0,False)
            if not ok:return
            bulk_unit="VOLUMEN" if label.startswith("Volumen") else "PESO"
        if QMessageBox.question(self,"Confirmar",f"Se cambiarán {len(selected)} productos a {kind}.\nLos precios e inventarios no se modificarán.")!=QMessageBox.Yes:return
        try:self.products.cambiar_tipo_masivo([p.id for p in selected],kind,bulk_unit);self.reload()
        except Exception as exc:show_error(self,"No se aplicó ningún cambio",exc)
    def _change_active(self):
        selected=self.selected_products()
        if not selected:return
        label,ok=QInputDialog.getItem(self,"Activar / desactivar",f"Productos seleccionados: {len(selected)}",["ACTIVAR","DESACTIVAR"],0,False)
        if ok:self.products.aplicar_cambios({p.id:{"activo":label=="ACTIVAR"} for p in selected});self.reload()


def _optional_decimal_ui(value):return None if not value else Decimal(value)


def _tipo_venta_label(product):
    if product.tipo_venta=="UNIDAD":return "Unidad"
    return "Granel (L)" if product.unidad_granel=="VOLUMEN" else "Granel (kg)"


class InventoryPage(PaginatedProductsPage):
    def __init__(self,database,parent=None,auto_load=True):
        super().__init__(database,"EXISTENCIAS Y MOVIMIENTOS",["Producto","Clave","Barcode","Precio venta","Existencia","Control inventario"],["descripcion","clave","codigo_barras","precio_venta","existencia","controla_inventario"],parent,auto_load); self.inventory=InventoryService(database);self.table.setColumnWidth(0,360);actions=QHBoxLayout(); self.new_button=QPushButton("NUEVO  F1");self.entry=QPushButton("AGREGAR EXISTENCIA"); self.adjust=QPushButton("AJUSTAR EXISTENCIA");self.movements=QPushButton("VER MOVIMIENTOS")
        self.new_button.setProperty("class","action");actions.addWidget(self.new_button)
        for button,icon in ((self.entry,QStyle.SP_ArrowUp),(self.adjust,QStyle.SP_BrowserReload),(self.movements,QStyle.SP_FileDialogContentsView)):button.setIcon(self.style().standardIcon(icon));button.setProperty("class","action");actions.addWidget(button); self.register_selection_button(button)
        actions.addStretch(); self.layout().insertLayout(1,actions);self.new_button.clicked.connect(self._new); self.entry.clicked.connect(self._entry); self.adjust.clicked.connect(self._adjust);self.movements.clicked.connect(self._movements);self.filter.blockSignals(True);self.filter.setCurrentIndex(self.filter.findData("CON_CONTROL"));self.filter.blockSignals(False)
    def _new(self):
        dialog=QuickProductDialog(self.database,parent=self)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.reload(preserve_id=dialog.product.id)
        self.query.setFocus();self.query.selectAll()
    def after_search(self):
        term=self.query.text().strip()
        if term and self.result and not self.result.products and _looks_scanned(term):
            dialog=QuickProductDialog(self.database,term,self)
            if dialog.exec()==QDialog.DialogCode.Accepted:self.query.clear();self.reload(preserve_id=dialog.product.id)
        elif self.result and self.result.exact_match and self.result.products:self.table.selectRow(0)
        self.query.setFocus();self.query.selectAll()
    def row_values(self,p):return [nombre_producto(p),p.clave or "",p.codigo_barras or "",precio_producto(p),cantidad_producto(p) if p.controla_inventario else "—","Sí" if p.controla_inventario else "No"]
    def _selection_changed(self):
        super()._selection_changed();product=self.selected_product()
        if hasattr(self,"entry"):
            self.entry.setEnabled(bool(product and product.controla_inventario));self.adjust.setEnabled(bool(product and product.controla_inventario));self.movements.setEnabled(product is not None)
    def _entry(self):
        product=self.selected_product()
        if not product: QMessageBox.warning(self,"Seleccione producto","Seleccione una fila."); return
        if product.tipo_venta=="GRANEL":
            dialog=BulkStockDialog(product,"ENTRADA",self)
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            quantity=dialog.cantidad_mg;note=dialog.note.text()
        else:
            quantity,ok=QInputDialog.getInt(self,"Registrar entrada","Cantidad:",1,1,1_000_000)
            if not ok:return
            note,ok=QInputDialog.getText(self,"Registrar entrada","Nota (opcional):")
            if not ok:return
        try:
            if product.tipo_venta=="GRANEL":self.inventory.registrar_entrada_granel(product.id,quantity,note)
            else:self.inventory.registrar_entrada(product.id,quantity,note)
            self.refresh_preserve(product.id)
        except Exception as exc:show_error(self,"No se pudo registrar la entrada",exc)
        self.focus_search_deferred()
    def _adjust(self):
        product=self.selected_product()
        if not product: QMessageBox.warning(self,"Seleccione producto","Seleccione una fila."); return
        if product.tipo_venta=="GRANEL":
            dialog=BulkStockDialog(product,"AJUSTE",self)
            if dialog.exec()!=QDialog.DialogCode.Accepted:return
            stock=dialog.cantidad_mg;reason=dialog.note.text()
        else:
            stock,ok=QInputDialog.getInt(self,"Ajustar existencia","Nueva existencia:",product.existencia,0,1_000_000)
            if not ok:return
            reason,ok=QInputDialog.getText(self,"Ajustar existencia","Motivo:")
            if not ok:return
        try:
            if product.tipo_venta=="GRANEL":self.inventory.ajustar_existencia_granel(product.id,stock,reason)
            else:self.inventory.ajustar_existencia(product.id,stock,reason)
            self.refresh_preserve(product.id)
        except Exception as exc:show_error(self,"No se pudo ajustar",exc)
        self.focus_search_deferred()
    def _movements(self):
        product=self.selected_product()
        if product:InventoryMovementsDialog(product,self.inventory.listar_movimientos(product.id),self).exec()
        self.focus_search_deferred()


class ReadableEditDelegate(QStyledItemDelegate):
    def updateEditorGeometry(self,editor,option,index):
        rect=option.rect.adjusted(2,2,-2,-2);editor.setGeometry(rect)


def _looks_scanned(term):return len(term)>=8 and term.replace("-","").replace("_","").isalnum()


def _adjust_product_stock(database,product,parent):
    inventory=InventoryService(database)
    if not product.controla_inventario:QMessageBox.information(parent,"Sin control","El producto no controla inventario.");return False
    if product.tipo_venta=="GRANEL":
        dialog=BulkStockDialog(product,"AJUSTE",parent)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return False
        inventory.ajustar_existencia_granel(product.id,dialog.cantidad_mg,dialog.note.text())
    else:
        stock,ok=QInputDialog.getInt(parent,"Ajustar existencia","Nueva existencia:",product.existencia,0,1_000_000)
        if not ok:return False
        reason,ok=QInputDialog.getText(parent,"Ajustar existencia","Motivo:")
        if not ok:return False
        inventory.ajustar_existencia(product.id,stock,reason)
    return True


class HistoryPage(QWidget):
    def __init__(self,database,parent=None,auto_refresh=True):
        super().__init__(parent); self.sales=SalesService(database);self.summaries=DailySummaryService(database); self.tickets=TicketService(database,TICKET_ROOT); root=QVBoxLayout(self); heading=QLabel("HISTORIAL DE VENTAS"); heading.setStyleSheet("font-size:24px;font-weight:bold"); root.addWidget(heading)
        summary_bar=QHBoxLayout();summary_bar.addWidget(QLabel("Resumen del día:"));self.summary_date=QDateEdit(QDate.currentDate());self.summary_date.setCalendarPopup(True);self.summary_date.setDisplayFormat("dd/MM/yyyy");summary_bar.addWidget(self.summary_date);refresh=QPushButton("Actualizar");summary_bar.addWidget(refresh);summary_bar.addStretch();root.addLayout(summary_bar)
        self.summary_title=QLabel();self.summary_title.setStyleSheet("font-size:16px;font-weight:bold");self.net=QLabel();self.net.setStyleSheet("font-size:26px;font-weight:bold;color:#1877c9");self.summary_stats=QLabel();self.summary_stats.setWordWrap(True);root.addWidget(self.summary_title);root.addWidget(self.net);root.addWidget(self.summary_stats)
        root.addWidget(QLabel("Productos vendidos"));self.sold_table=QTableWidget(0,5);self.sold_table.setHorizontalHeaderLabels(["Producto","Clave","Cantidad","Unidad","Importe"]);self.sold_table.setEditTriggers(QTableWidget.NoEditTriggers);self.sold_table.horizontalHeader().setStretchLastSection(True);self.sold_table.setMaximumHeight(220);root.addWidget(self.sold_table)
        root.addWidget(QLabel("Ventas recientes")); self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(["Folio","Fecha","Método","Total","Estado"]); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table);pager=QHBoxLayout();self.previous=QPushButton("< Anterior");self.next=QPushButton("Siguiente >");self.page_label=QLabel();pager.addWidget(self.previous);pager.addWidget(self.next);pager.addWidget(self.page_label);pager.addStretch();root.addLayout(pager);self.page=1;self.page_size=50; self.open_button=QPushButton("Ver detalle"); self.open_button.setEnabled(False); root.addWidget(self.open_button,alignment=Qt.AlignRight); refresh.clicked.connect(self.refresh);self.summary_date.dateChanged.connect(lambda _date:self.refresh_summary()); self.open_button.clicked.connect(self.open_sale); self.table.doubleClicked.connect(self.open_sale); self.table.itemSelectionChanged.connect(lambda:self.open_button.setEnabled(self.table.currentRow()>=0));self.previous.clicked.connect(lambda:self._go(self.page-1));self.next.clicked.connect(lambda:self._go(self.page+1));self._loaded=False
        if auto_refresh:self.refresh()
    def ensure_loaded(self):
        if not self._loaded:self.refresh()
    def refresh(self):
        try:
            self.refresh_summary()
            total=self.sales.contar_ventas();pages=max(1,(total+self.page_size-1)//self.page_size);self.page=min(self.page,pages);sales=self.sales.ultimas_ventas(self.page_size,(self.page-1)*self.page_size); self.table.setRowCount(0)
            for sale in sales:
                row=self.table.rowCount(); self.table.insertRow(row); values=[sale.folio,sale.fecha_hora,sale.metodo_pago,moneda(sale.total_centavos),sale.estado]
                for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(str(value)))
                self.table.item(row,0).setData(Qt.UserRole,sale.id)
            self._loaded=True
            self.page_label.setText(f"Página {self.page} de {pages} · {total} ventas");self.previous.setEnabled(self.page>1);self.next.setEnabled(self.page<pages)
        except Exception as exc:show_error(self,"No se pudo cargar el historial",exc)
    def _go(self,page):self.page=page;self.refresh()
    def refresh_summary(self):
        try:
            day=self.summary_date.date().toPython();summary=self.summaries.obtener(day);self.summary_title.setText(f"RESUMEN DEL DÍA · {day:%d/%m/%Y}");self.net.setText(f"VENTA NETA  {moneda(summary.venta_neta_centavos)}")
            methods="\n".join(f"{name.title()}: {moneda(value)}" for name,value in summary.metodos_pago.items()) or "Métodos de pago: sin ventas"
            self.summary_stats.setText(f"Ventas completadas: {summary.ventas_completadas}\n{methods}\nVentas canceladas: {summary.ventas_canceladas} · Importe cancelado: {moneda(summary.importe_cancelado_centavos)}\nDescuentos (sólo ventas completadas): {moneda(summary.descuentos_centavos)}")
            self.sold_table.setRowCount(0)
            for product in summary.productos:
                row=self.sold_table.rowCount();self.sold_table.insertRow(row)
                if product.tipo_venta=="UNIDAD":quantity=str(product.cantidad);unit="pzas" if product.cantidad!=1 else "pza"
                else:formatted=formato_granel(product.cantidad,product.unidad_granel or "PESO");quantity,unit=formatted.rsplit(" ",1)
                for column,value in enumerate((product.producto,product.clave or "",quantity,unit,moneda(product.importe_centavos))):self.sold_table.setItem(row,column,QTableWidgetItem(str(value)))
        except Exception as exc:show_error(self,"No se pudo cargar el resumen",exc)
    def open_sale(self,*_):
        row=self.table.currentRow()
        if row<0:return
        sale=self.sales.obtener_por_id(self.table.item(row,0).data(Qt.UserRole)); SaleDetailDialog(sale,self.sales,self.tickets,self).exec(); self.refresh()
