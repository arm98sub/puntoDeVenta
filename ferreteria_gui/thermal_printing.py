"""Adaptadores de Windows/Qt para impresión térmica y cajón."""
from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

from PySide6.QtCore import QSizeF
from PySide6.QtGui import QFont,QFontMetricsF,QPageSize,QPainter
from PySide6.QtPrintSupport import QPrinter,QPrinterInfo

from ferreteria_core.services import BusinessConfigService,SalesService
from ferreteria_core.thermal_printing import ThermalPrintSettingsService,ThermalTicketRenderer,drawer_kick_command
from .config import visible_business_name

logger=logging.getLogger(__name__)


class WindowsPrinterBackend:
    # A 58 mm roll normally has a 48 mm print head.  POS80 explicitly rejects
    # custom widths above 48.047 mm and otherwise falls back to its continuous
    # 80 x 3275.9 mm form, causing excessive paper feed.
    DRIVER_WIDTHS_MM={58:48.0}
    SIDE_MARGIN_MM=0.1
    TOP_MARGIN_MM=4.0
    FINAL_FEED_MM=6.0
    FONT_POINT_SIZE=8
    @staticmethod
    def printer_names():return sorted(QPrinterInfo.availablePrinterNames(),key=str.casefold)
    @classmethod
    def _font(cls):
        font=QFont("Courier New",cls.FONT_POINT_SIZE);font.setStyleHint(QFont.Monospace);return font
    @classmethod
    def driver_page_dimensions(cls,paper_width_mm,height_mm):
        return cls.DRIVER_WIDTHS_MM.get(paper_width_mm,float(paper_width_mm)),float(height_mm)
    @classmethod
    def _printer(cls,printer_name,paper_width_mm,height_mm):
        printer=QPrinter(QPrinter.HighResolution);printer.setPrinterName(printer_name);printer.setOutputFormat(QPrinter.NativeFormat)
        driver_width,driver_height=cls.driver_page_dimensions(paper_width_mm,height_mm)
        printer.setPageSize(QPageSize(QSizeF(driver_width,driver_height),QPageSize.Millimeter,"Ticket térmico"))
        # POS80 reports a corrupt pageRect for custom roll sizes (including
        # negative vertical dimensions).  Full-page mode plus explicit safe
        # margins uses the valid physical paperRect instead.
        printer.setFullPage(True)
        return printer
    def printable_columns(self,printer_name,paper_width_mm):
        if not printer_name:raise ValueError("Seleccione una impresora en Configuración")
        if printer_name not in self.printer_names():raise ValueError(f"La impresora configurada no está disponible: {printer_name}")
        printer=self._printer(printer_name,paper_width_mm,100);rect=printer.paperRect(QPrinter.DevicePixel);metrics=QFontMetricsF(self._font(),printer)
        side_px=(self.SIDE_MARGIN_MM/25.4)*printer.resolution();usable_px=max(1.0,rect.width()-(2*side_px))
        return max(1,int(usable_px//metrics.horizontalAdvance("0")))
    @classmethod
    def job_height_mm(cls,line_count,line_height_mm):
        return max(25.0,cls.TOP_MARGIN_MM+(line_count*float(line_height_mm))+cls.FINAL_FEED_MM)
    @staticmethod
    def _geometry(printer):
        layout=printer.pageLayout();size=layout.pageSize().size(QPageSize.Millimeter);paper=printer.paperRect(QPrinter.Millimeter);page=printer.pageRect(QPrinter.Millimeter)
        return {"page_size_mm":(round(size.width(),3),round(size.height(),3)),"paper_rect_mm":(round(paper.width(),3),round(paper.height(),3)),"page_rect_mm":(round(page.width(),3),round(page.height(),3)),"resolution_dpi":printer.resolution()}
    def print_text(self,printer_name,text,paper_width_mm):
        if not printer_name:raise ValueError("Seleccione una impresora en Configuración")
        if printer_name not in self.printer_names():raise ValueError(f"La impresora configurada no está disponible: {printer_name}")
        lines=text.rstrip("\n").splitlines();probe=self._printer(printer_name,paper_width_mm,100);probe_metrics=QFontMetricsF(self._font(),probe)
        line_mm=(probe_metrics.lineSpacing()/probe.resolution())*25.4
        height=self.job_height_mm(len(lines),line_mm)
        printer=self._printer(printer_name,paper_width_mm,height)
        logger.info("Impresión térmica solicitada: rollo=%s mm, contenido=%s líneas, altura_calculada=%.3f mm, geometría_previa=%s",paper_width_mm,len(lines),height,self._geometry(printer))
        painter=QPainter()
        if not painter.begin(printer):raise OSError("Windows no pudo iniciar la impresión")
        try:
            logger.info("Impresión térmica aceptada por driver: geometría_efectiva=%s",self._geometry(printer))
            painter.setFont(self._font());metrics=painter.fontMetrics();rect=printer.paperRect(QPrinter.DevicePixel);side_px=(self.SIDE_MARGIN_MM/25.4)*printer.resolution();top_px=(self.TOP_MARGIN_MM/25.4)*printer.resolution();x=rect.left()+side_px;y=rect.top()+top_px+metrics.ascent()
            usable_right=rect.right()-side_px
            for line in lines:
                if x+metrics.horizontalAdvance(line)>usable_right+1:raise ValueError("Una línea del ticket excede el ancho imprimible")
                painter.drawText(x,y,line);y+=metrics.lineSpacing()
        finally:painter.end()
    def send_raw(self,printer_name,payload):
        if os.name!="nt":raise OSError("La apertura de cajón sólo está disponible en Windows")
        _send_raw_windows(printer_name,payload)


class ThermalPrinterService:
    def __init__(self,database,settings_path,backend=None):
        self.database=database;self.settings=ThermalPrintSettingsService(settings_path);self.backend=backend or WindowsPrinterBackend();self.renderer=ThermalTicketRenderer()
    def available_printers(self):return self.backend.printer_names()
    def _columns(self,settings):
        measure=getattr(self.backend,"printable_columns",None)
        return measure(settings.printer_name,settings.paper_width_mm) if measure else None
    def print_sale(self,sale):
        settings=self.settings.load();business=BusinessConfigService(self.database).obtener();text=self.renderer.render(sale,business,settings.paper_width_mm,columns=self._columns(settings),business_name=visible_business_name(business.nombre_negocio));self.backend.print_text(settings.printer_name,text,settings.paper_width_mm);return text
    def print_sale_id(self,sale_id):
        sale=SalesService(self.database).obtener_por_id(sale_id)
        if sale is None:raise LookupError("La venta no existe")
        return self.print_sale(sale)
    def print_test(self):
        settings=self.settings.load();business=BusinessConfigService(self.database).obtener();name=visible_business_name(business.nombre_negocio);columns=self._columns(settings) or self.renderer.WIDTHS[settings.paper_width_mm];text="\n".join(self.renderer._center(name,columns)+["",*self.renderer._center("PRUEBA DE IMPRESIÓN",columns),f"Papel: {settings.paper_width_mm} mm","",*self.renderer._center("Impresora configurada correctamente.",columns)])+"\n";self.backend.print_text(settings.printer_name,text,settings.paper_width_mm);return text
    def open_drawer(self):
        settings=self.settings.load()
        if not settings.printer_name:raise ValueError("Seleccione una impresora en Configuración")
        command=drawer_kick_command(settings);self.backend.send_raw(settings.printer_name,command);return command


class _DOC_INFO_1(ctypes.Structure):_fields_=[("pDocName",wintypes.LPWSTR),("pOutputFile",wintypes.LPWSTR),("pDatatype",wintypes.LPWSTR)]
def _send_raw_windows(printer_name,payload):
    spool=ctypes.WinDLL("winspool.drv",use_last_error=True);handle=wintypes.HANDLE();written=wintypes.DWORD();doc=_DOC_INFO_1("Apertura de cajón",None,"RAW")
    if not spool.OpenPrinterW(printer_name,ctypes.byref(handle),None):raise ctypes.WinError(ctypes.get_last_error())
    started=False;page=False
    try:
        if not spool.StartDocPrinterW(handle,1,ctypes.byref(doc)):raise ctypes.WinError(ctypes.get_last_error())
        started=True
        if not spool.StartPagePrinter(handle):raise ctypes.WinError(ctypes.get_last_error())
        page=True;buffer=ctypes.create_string_buffer(payload)
        if not spool.WritePrinter(handle,buffer,len(payload),ctypes.byref(written)) or written.value!=len(payload):raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if page:spool.EndPagePrinter(handle)
        if started:spool.EndDocPrinter(handle)
        spool.ClosePrinter(handle)
