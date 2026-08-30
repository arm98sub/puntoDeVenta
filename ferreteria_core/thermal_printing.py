"""Configuración y representación pura de tickets térmicos."""
from __future__ import annotations

import json
import os
import textwrap
from dataclasses import asdict,dataclass
from decimal import Decimal
from pathlib import Path

from ferreteria_core.money import centavos_a_decimal


@dataclass(frozen=True)
class ThermalPrintSettings:
    printer_name:str=""
    paper_width_mm:int=58
    auto_print:bool=False
    auto_open_drawer:bool=False
    drawer_channel:int=0
    drawer_pulse_on_ms:int=50
    drawer_pulse_off_ms:int=500


class ThermalPrintSettingsService:
    def __init__(self,path):self.path=Path(path)
    def load(self):
        if not self.path.exists():return ThermalPrintSettings()
        try:data=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc:raise ValueError("La configuración de impresora no es válida") from exc
        allowed=ThermalPrintSettings.__dataclass_fields__;return self._validate(ThermalPrintSettings(**{key:value for key,value in data.items() if key in allowed}))
    def save(self,settings):
        value=self._validate(settings);self.path.parent.mkdir(parents=True,exist_ok=True);temporary=self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(value),ensure_ascii=False,indent=2),encoding="utf-8");os.replace(temporary,self.path);return value
    @staticmethod
    def _validate(settings):
        if not isinstance(settings,ThermalPrintSettings):raise TypeError("Configuración de impresión inválida")
        if settings.paper_width_mm not in {58,80}:raise ValueError("Ancho de papel no compatible")
        if settings.drawer_channel not in {0,1}:raise ValueError("Canal de cajón inválido")
        if not 0<settings.drawer_pulse_on_ms<=510 or not 0<settings.drawer_pulse_off_ms<=510:raise ValueError("Pulso de cajón inválido")
        return settings


def drawer_kick_command(settings):
    settings=ThermalPrintSettingsService._validate(settings)
    return bytes((0x1B,0x70,settings.drawer_channel,round(settings.drawer_pulse_on_ms/2),round(settings.drawer_pulse_off_ms/2)))


class ThermalTicketRenderer:
    # Conservative fallbacks used by non-Qt transports and tests.  The Windows
    # backend supplies the capacity measured from the printer's real pageRect.
    WIDTHS={58:28,80:44}
    def render(self,sale,business,paper_width_mm=58,*,columns=None,business_name=None):
        width=columns or self.WIDTHS.get(paper_width_mm)
        if width is None:raise ValueError("Ancho de papel no compatible")
        if width<12:raise ValueError("El área imprimible es demasiado estrecha")
        rule="-"*width;lines=[]
        lines.extend(self._center(business_name or business.nombre_negocio,width))
        for value in (business.direccion,business.telefono,(f"RFC: {business.rfc}" if business.rfc else None)):
            if value:lines.extend(self._center(value,width))
        lines.append("");lines.extend(_field_lines("Folio",sale.folio,width));lines.extend(_field_lines("Fecha",sale.fecha_hora.replace('T',' ')[:19],width));lines.append(rule)
        for detail in sale.detalles:
            name=detail.descripcion_snapshot or detail.clave_snapshot or detail.codigo_barras_snapshot or "Producto"
            lines.extend(textwrap.wrap(name,width=width,break_long_words=True,break_on_hyphens=False) or ["Producto"])
            if detail.tipo_venta_snapshot=="GRANEL":
                unit=detail.unidad_granel_snapshot or "PESO";suffix="L" if unit=="VOLUMEN" else "kg";quantity=f"{Decimal(detail.cantidad_mg)/Decimal(1_000_000):.3f} {suffix}";price=detail.precio_por_kg_centavos
                left=f"{quantity} x {_money(price)}"
            else:left=f"{detail.cantidad} x {_money(detail.precio_unitario_centavos)}"
            lines.extend(_pair_lines(left,_money(detail.subtotal_centavos),width))
        lines.append(rule);lines.extend(_pair_lines("TOTAL",_money(sale.total_centavos),width));lines.extend(_field_lines("MÉTODO",sale.metodo_pago,width))
        if sale.efectivo_recibido_centavos is not None:
            lines.extend(_pair_lines("RECIBIDO",_money(sale.efectivo_recibido_centavos),width));lines.extend(_pair_lines("CAMBIO",_money(sale.cambio_centavos),width))
        lines.append(rule)
        if business.mensaje_ticket:lines.extend(self._center(business.mensaje_ticket,width))
        # Exactly one terminal newline.  Physical feed is controlled by the
        # transport, not by blank logical lines in the ticket.
        return "\n".join(lines).rstrip()+"\n"
    @staticmethod
    def _center(value,width):return [line.center(width) for line in textwrap.wrap(str(value),width=width,break_long_words=True)]


def _pair_lines(left,right,width):
    """Keep the monetary value intact; wrap the left side when both do not fit."""
    left=str(left);right=str(right)
    if len(right)>width:raise ValueError("El importe no cabe en el ancho del ticket")
    if len(left)+1+len(right)<=width:return [f"{left:<{width-len(right)}}{right}"]
    wrapped=textwrap.wrap(left,width=width,break_long_words=True,break_on_hyphens=False) or [""]
    return [*wrapped,right.rjust(width)]
def _field_lines(label,value,width):
    text=f"{label}: {value}"
    if len(text)<=width:return [text]
    return [f"{label}:",*(textwrap.wrap(str(value),width=width,break_long_words=True,break_on_hyphens=False) or [""])]
def _money(cents):return f"${centavos_a_decimal(cents):,.2f}"
