import os
from datetime import datetime
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader

from ferreteria_core.money import centavos_a_decimal
from ferreteria_core.quantity import formato_cantidad,formato_granel
from .business_config import BusinessConfigService
from .sales import SalesService


class TicketService:
    WIDTH = 80 * mm

    def __init__(self, database, root="tickets", business=None):
        self.database = database; self.root = Path(root); self.business = business

    def ruta_ticket(self, sale):
        date = _sale_datetime(sale.fecha_hora)
        return self.root / f"{date:%Y}" / f"{date:%m}" / f"{sale.folio}.pdf"

    def obtener_o_generar(self, venta_id):
        sale = SalesService(self.database).obtener_por_id(venta_id)
        if sale is None: raise LookupError("La venta no existe")
        path = self.ruta_ticket(sale)
        return self._use_existing(path, sale.folio) if path.exists() else self._write(sale, path)

    def regenerar(self, venta_id):
        sale = SalesService(self.database).obtener_por_id(venta_id)
        if sale is None: raise LookupError("La venta no existe")
        return self._write(sale, self.ruta_ticket(sale), replace=True)

    def generar_para_venta(self, sale):
        path = self.ruta_ticket(sale)
        return self._use_existing(path, sale.folio) if path.exists() else self._write(sale, path)

    @staticmethod
    def _use_existing(path, folio):
        try:
            subject = (PdfReader(path).metadata or {}).get("/Subject")
        except Exception as exc:
            raise FileExistsError(f"Existe un archivo distinto o inválido en {path}; use regenerar explícitamente") from exc
        if subject != folio:
            raise FileExistsError(f"El PDF existente no corresponde al folio {folio}; no fue sobrescrito")
        return path

    def _write(self, sale, path, replace=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not replace:
            raise FileExistsError(f"El ticket ya existe: {path}")
        business = self.business or BusinessConfigService(self.database).obtener()
        lines = _ticket_lines(sale, business)
        logo_extra = 16 if any(line[0] == "logo" for line in lines) else 0
        height = max(120 * mm, (len(lines) * 4.6 + 22 + logo_extra) * mm)
        temporary = path.with_name(f".{path.stem}.tmp.pdf")
        canvas = Canvas(str(temporary), pagesize=(self.WIDTH, height), pageCompression=1)
        canvas.setTitle(f"Ticket {sale.folio}"); canvas.setSubject(sale.folio); canvas.setAuthor(business.nombre_negocio)
        y = height - 8 * mm
        for line in lines:
            kind, left, right = line
            if kind == "space": y -= 3 * mm; continue
            if kind == "logo":
                canvas.drawImage(left,22.5*mm,y-17*mm,width=35*mm,height=17*mm,preserveAspectRatio=True,anchor="c",mask="auto"); y-=20*mm; continue
            if kind == "rule":
                canvas.setLineWidth(.4); canvas.line(5 * mm, y, self.WIDTH - 5 * mm, y); y -= 4 * mm; continue
            font, size = ("Helvetica-Bold", 13) if kind == "title" else (("Helvetica-Bold", 11) if kind in {"total","cancelled"} else ("Helvetica", 8.5))
            canvas.setFont(font, size)
            if kind in {"title","center","cancelled"}:
                canvas.drawCentredString(self.WIDTH / 2, y, left)
            else:
                canvas.drawString(5 * mm, y, left)
                if right: canvas.drawRightString(self.WIDTH - 5 * mm, y, right)
            y -= (5.2 if kind in {"title","total","cancelled"} else 4.1) * mm
        canvas.save()
        if path.exists() and not replace:
            temporary.unlink(missing_ok=True); raise FileExistsError(f"El ticket ya existe: {path}")
        os.replace(temporary, path)
        return path


def _ticket_lines(sale, business):
    date = _sale_datetime(sale.fecha_hora)
    lines=[]
    if business.logo_path and Path(business.logo_path).exists(): lines.append(("logo",business.logo_path,""))
    lines.append(("title",business.nombre_negocio,""))
    for value in (business.direccion,business.telefono,(f"RFC: {business.rfc}" if business.rfc else None)):
        if value: lines.append(("center",value,""))
    lines.extend([("rule","",""),("text",f"Folio: {sale.folio}",""),("text",date.strftime("%d/%m/%Y %H:%M"),"")])
    if sale.estado == "CANCELADA": lines.extend([("space","",""),("cancelled","*** VENTA CANCELADA ***","")])
    lines.append(("rule","",""))
    for detail in sale.detalles:
        name = (detail.descripcion_snapshot or detail.clave_snapshot or detail.codigo_truper_snapshot or
                detail.codigo_barras_snapshot or "Producto")
        for wrapped in _wrap(name, 42): lines.append(("text", wrapped, ""))
        if detail.tipo_venta_snapshot=="GRANEL":
            bulk_unit=detail.unidad_granel_snapshot or "PESO";quantity=formato_granel(detail.cantidad_mg,bulk_unit);suffix="L" if bulk_unit=="VOLUMEN" else "kg"
            lines.append(("text",f"{quantity} x {_money(detail.precio_por_kg_centavos)}/{suffix}",_money(detail.subtotal_centavos)))
        else:
            lines.append(("text", f"{detail.cantidad} x {_money(detail.precio_unitario_centavos)}", _money(detail.subtotal_centavos)))
        lines.append(("space","",""))
    lines.extend([("rule","",""),("text","Subtotal",_money(sale.subtotal_centavos)),
                  ("text","Descuento",_money(sale.descuento_centavos)),("space","",""),
                  ("total","TOTAL",_money(sale.total_centavos)),("space","",""),
                  ("text",f"Método: {sale.metodo_pago}","")])
    if sale.efectivo_recibido_centavos is not None:
        lines.append(("text","Recibido",_money(sale.efectivo_recibido_centavos)))
        lines.append(("text","Cambio",_money(sale.cambio_centavos)))
    lines.append(("rule","",""))
    if business.mensaje_ticket: lines.append(("center",business.mensaje_ticket,""))
    return lines


def _money(cents):
    return f"${centavos_a_decimal(cents):,.2f}"


def _sale_datetime(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone() if parsed.tzinfo is not None else parsed


def _wrap(text, length):
    words, lines, current = str(text).split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= length: current = candidate
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    return lines or ["Producto"]
