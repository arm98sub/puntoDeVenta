from dataclasses import dataclass
from datetime import date,datetime,time,timezone,timedelta

from ferreteria_core.repositories import SaleRepository


@dataclass(frozen=True)
class SoldProduct:
    producto_id:int;producto:str;clave:str|None;tipo_venta:str;unidad_granel:str|None
    cantidad:int;importe_centavos:int


@dataclass(frozen=True)
class DailySummary:
    fecha:date;ventas_completadas:int;venta_neta_centavos:int;metodos_pago:dict[str,int]
    ventas_canceladas:int;importe_cancelado_centavos:int;descuentos_centavos:int
    productos:list[SoldProduct]


class DailySummaryService:
    def __init__(self,database):self.database=database
    def obtener(self,value=None):
        day=_date(value);start,end=_utc_bounds(day)
        with self.database.connect() as connection:totals,methods,products=SaleRepository.daily_summary(connection,start,end)
        sold=[]
        for row in products:
            bulk=row["tipo_venta_snapshot"]=="GRANEL";name=row["descripcion_snapshot"] or row["clave_snapshot"] or row["codigo_truper_snapshot"] or row["codigo_barras_snapshot"] or "Producto"
            sold.append(SoldProduct(row["producto_id"],name,row["clave_snapshot"],row["tipo_venta_snapshot"],row["unidad_granel_snapshot"],row["cantidad_granel"] if bulk else row["cantidad"],row["importe"]))
        return DailySummary(day,totals["completadas"] or 0,totals["venta_neta"],{row["metodo_pago"]:row["total"] for row in methods},totals["canceladas"] or 0,totals["importe_cancelado"],totals["descuentos"],sold)


def _date(value):
    if value is None:return date.today()
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    return date.fromisoformat(str(value))


def _utc_bounds(day):
    local_start=datetime.combine(day,time.min).astimezone();local_end=datetime.combine(day+timedelta(days=1),time.min).astimezone()
    fmt=lambda value:value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return fmt(local_start),fmt(local_end)
