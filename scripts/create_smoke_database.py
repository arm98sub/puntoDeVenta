"""Crea datos mínimos exclusivamente para smoke tests en una ruta indicada."""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ferreteria_core import Database
from ferreteria_core.services import ProductService, SalesService


def main(path):
    database=Database(path);database.migrate();products=ProductService(database)
    product=products.crear_producto_externo("7500000000999","Producto temporal para smoke test",Decimal("10"),2)
    SalesService(database).crear_venta([{"producto_id":product.id,"cantidad":1}],"TARJETA")


if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("Uso: create_smoke_database.py RUTA_DB")
    main(Path(sys.argv[1]))
