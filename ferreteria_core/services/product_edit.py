from dataclasses import dataclass
from decimal import Decimal

from ferreteria_core.money import centavos_a_decimal,decimal_a_centavos
from .products import ProductService


@dataclass(frozen=True)
class PendingChange:
    producto_id:int;campo:str;anterior:object;nuevo:object


class ProductEditSession:
    EDITABLE={"descripcion","precio_venta","tipo_venta","categoria"}
    def __init__(self,database):self.database=database;self.service=ProductService(database);self._changes={}
    @property
    def count(self):return sum(len(fields) for fields in self._changes.values())
    @property
    def product_count(self):return len(self._changes)
    @property
    def has_changes(self):return bool(self._changes)
    def set(self,product_id,field,value):
        if field not in self.EDITABLE:raise ValueError(f"Campo protegido: {field}")
        product=self.service.get(product_id)
        if product is None:raise LookupError("Producto inexistente")
        normalized=self._normalize(field,value);old=getattr(product,field)
        if normalized==old:self._changes.get(product_id,{}).pop(field,None)
        else:self._changes.setdefault(product_id,{})[field]=(old,normalized)
        if product_id in self._changes and not self._changes[product_id]:self._changes.pop(product_id)
    def changes(self):
        return [PendingChange(pid,field,old,new) for pid,fields in self._changes.items() for field,(old,new) in fields.items()]
    def grouped_values(self):
        return {pid:{field:(Decimal(new)/Decimal(100) if field=="precio_venta" else new) for field,(_,new) in fields.items()} for pid,fields in self._changes.items()}
    def save(self):
        result=self.service.aplicar_cambios(self.grouped_values());self.discard();return result
    def discard(self):self._changes.clear()
    @staticmethod
    def _normalize(field,value):
        if field=="precio_venta":
            try:decimal=Decimal(str(value))
            except Exception as exc:raise ValueError("Precio inválido") from exc
            if not decimal.is_finite() or decimal<0:raise ValueError("Precio inválido")
            return decimal_a_centavos(decimal)
        if field=="tipo_venta":
            value=(value or "").strip().upper()
            if value not in {"UNIDAD","GRANEL"}:raise ValueError("Tipo de venta inválido")
            return value
        return (value or "").strip() or None

    @staticmethod
    def display(change):
        if change.campo=="precio_venta":return f"${centavos_a_decimal(change.anterior):.2f} → ${centavos_a_decimal(change.nuevo):.2f}"
        return f"{change.anterior or '(vacío)'} → {change.nuevo or '(vacío)'}"
