import argparse
import json
from dataclasses import asdict
from decimal import Decimal

from ferreteria_core import Database
from ferreteria_core.money import centavos_a_decimal
from ferreteria_core.services import Cart, InventoryService, ProductService, SalesService, importar_catalogo_truper, respaldar_base


def main():
    parser = argparse.ArgumentParser(description="CLI de desarrollo del núcleo de ferretería")
    parser.add_argument("--db", default="data/ferreteria.db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    imp = sub.add_parser("importar"); imp.add_argument("csv", nargs="?", default="output/catalogo_truper_enriquecido.csv")
    for command, field in (("buscar-truper","codigo_truper"),("buscar-clave","clave"),("buscar-barcode","codigo_barras")):
        p = sub.add_parser(command); p.add_argument("valor"); p.set_defaults(field=field)
    p = sub.add_parser("buscar-descripcion"); p.add_argument("texto")
    p = sub.add_parser("mostrar"); p.add_argument("id", type=int)
    p = sub.add_parser("vincular-barcode"); p.add_argument("id", type=int); p.add_argument("codigo")
    for command in ("existencia-inicial", "entrada"):
        p = sub.add_parser(command); p.add_argument("id", type=int); p.add_argument("cantidad", type=int); p.add_argument("--nota")
    p = sub.add_parser("ajustar"); p.add_argument("id", type=int); p.add_argument("existencia", type=int); p.add_argument("motivo")
    p = sub.add_parser("crear-externo"); p.add_argument("barcode"); p.add_argument("descripcion"); p.add_argument("precio"); p.add_argument("existencia", type=int); p.add_argument("--clave"); p.add_argument("--marca"); p.add_argument("--categoria"); p.add_argument("--stock-minimo", type=int, default=0)
    p = sub.add_parser("backup"); p.add_argument("--destino", default="backups")
    sub.add_parser("estadisticas")
    p = sub.add_parser("crear-venta"); p.add_argument("items", nargs="+"); p.add_argument("--metodo", required=True, choices=["EFECTIVO","TRANSFERENCIA","TARJETA","OTRO"]); p.add_argument("--efectivo"); p.add_argument("--descuento", default="0"); p.add_argument("--nota")
    p = sub.add_parser("ver-venta"); p.add_argument("referencia")
    p = sub.add_parser("ultimas-ventas"); p.add_argument("--limite", type=int, default=20)
    p = sub.add_parser("ventas-rango"); p.add_argument("desde"); p.add_argument("hasta"); p.add_argument("--limite", type=int, default=1000)
    p = sub.add_parser("cancelar-venta"); p.add_argument("id", type=int); p.add_argument("motivo")
    sub.add_parser("venta-interactiva")
    args = parser.parse_args(); db = Database(args.db); db.migrate(); products = ProductService(db); inventory = InventoryService(db); sales = SalesService(db)
    if args.command == "init-db": db.migrate(); result = {"base": str(db.path), "estado": "inicializada"}
    elif args.command == "importar": result = importar_catalogo_truper(db, args.csv)
    elif args.command.startswith("buscar-") and args.command != "buscar-descripcion": result = products.buscar_exacto(args.field, args.valor)
    elif args.command == "buscar-descripcion": result = products.buscar(descripcion=args.texto)
    elif args.command == "mostrar": result = products.get(args.id)
    elif args.command == "vincular-barcode": result = products.vincular_codigo_barras(args.id, args.codigo)
    elif args.command == "existencia-inicial": result = {"movimiento_id": inventory.registrar_existencia_inicial(args.id, args.cantidad)}
    elif args.command == "entrada": result = {"movimiento_id": inventory.registrar_entrada(args.id, args.cantidad, args.nota)}
    elif args.command == "ajustar": result = {"movimiento_id": inventory.ajustar_existencia(args.id, args.existencia, args.motivo)}
    elif args.command == "crear-externo": result = products.crear_producto_externo(args.barcode,args.descripcion,Decimal(args.precio),args.existencia,clave=args.clave,marca=args.marca,categoria=args.categoria,stock_minimo=args.stock_minimo)
    elif args.command == "backup": result = {"backup": str(respaldar_base(db, args.destino))}
    elif args.command == "crear-venta": result = sales.crear_venta(_parse_items(args.items), args.metodo, Decimal(args.efectivo) if args.efectivo is not None else None, Decimal(args.descuento), args.nota)
    elif args.command == "ver-venta": result = sales.obtener_por_folio(args.referencia) if args.referencia.upper().startswith("V-") else sales.obtener_por_id(int(args.referencia))
    elif args.command == "ultimas-ventas": result = sales.ultimas_ventas(args.limite)
    elif args.command == "ventas-rango": result = sales.ventas_por_rango(args.desde, args.hasta, args.limite)
    elif args.command == "cancelar-venta": result = sales.cancelar_venta(args.id, args.motivo)
    elif args.command == "venta-interactiva":
        venta_interactiva(db); return
    elif args.command == "estadisticas":
        with db.connect() as connection:
            one = lambda sql: connection.execute(sql).fetchone()[0]
            result = {
                "total": one("SELECT count(*) FROM productos"),
                "truper": one("SELECT count(*) FROM productos WHERE es_truper=1"),
                "externos": one("SELECT count(*) FROM productos WHERE es_truper=0"),
                "con_precio": one("SELECT count(*) FROM productos WHERE precio_venta IS NOT NULL"),
                "sin_precio": one("SELECT count(*) FROM productos WHERE precio_venta IS NULL"),
                "con_descripcion": one("SELECT count(*) FROM productos WHERE descripcion IS NOT NULL AND trim(descripcion) != ''"),
                "sin_descripcion": one("SELECT count(*) FROM productos WHERE descripcion IS NULL OR trim(descripcion) = ''"),
                "con_clave": one("SELECT count(*) FROM productos WHERE clave IS NOT NULL AND trim(clave) != ''"),
                "completos": one("SELECT count(*) FROM productos WHERE datos_completos=1"),
                "revision": one("SELECT count(*) FROM productos WHERE requiere_revision=1"),
                "barcodes": one("SELECT count(*) FROM productos WHERE codigo_barras IS NOT NULL AND codigo_barras != ''"),
                "existencia_total": one("SELECT coalesce(sum(existencia),0) FROM productos"),
                "duplicados": one("SELECT count(*) FROM (SELECT codigo_truper FROM productos WHERE codigo_truper IS NOT NULL GROUP BY codigo_truper HAVING count(*)>1)"),
                "movimientos": one("SELECT count(*) FROM movimientos_inventario"),
                "integridad": connection.execute("PRAGMA integrity_check").fetchone()[0],
            }
    print(json.dumps(_json(result), ensure_ascii=False, indent=2))


def _json(value):
    if hasattr(value, "__dataclass_fields__"): return asdict(value)
    if isinstance(value, list): return [_json(item) for item in value]
    return value


def _parse_items(values):
    items = []
    for value in values:
        try:
            product_id, quantity = value.split(":", 1)
            items.append({"producto_id": int(product_id), "cantidad": int(quantity)})
        except ValueError as exc:
            raise ValueError(f"Item inválido '{value}'; use producto_id:cantidad") from exc
    return items


def venta_interactiva(db):
    cart, sales = Cart(db), SalesService(db)
    print("\nNUEVA VENTA")
    print("Escanee códigos o use TOTAL, QUITAR, CANCELAR, COBRAR.")
    while True:
        command = input("\nEscanee producto: ").strip()
        upper = command.upper()
        try:
            if not command:
                continue
            if upper == "TOTAL":
                _show_cart(cart); continue
            if upper.startswith("QUITAR"):
                parts = command.split(maxsplit=1)
                barcode = parts[1] if len(parts) == 2 else input("Código a quitar: ").strip()
                product = ProductService(db).buscar_exacto("codigo_barras", barcode)
                if product is None: raise LookupError("Código no encontrado")
                cart.eliminar(product.id); _show_cart(cart); continue
            if upper == "CANCELAR":
                cart.vaciar(); print("Venta descartada."); return
            if upper == "COBRAR":
                if not cart.items: raise ValueError("El carrito está vacío")
                _show_cart(cart)
                method = input("Método [EFECTIVO/TRANSFERENCIA/TARJETA/OTRO]: ").strip().upper()
                discount = Decimal(input("Descuento [0]: ").strip() or "0")
                received = Decimal(input("Efectivo recibido: ").strip()) if method == "EFECTIVO" else None
                sale = sales.crear_venta(cart.como_items_venta(), method, received, discount)
                print(f"Venta {sale.folio} completada. Total ${centavos_a_decimal(sale.total_centavos):.2f}")
                if sale.cambio_centavos is not None: print(f"Cambio ${centavos_a_decimal(sale.cambio_centavos):.2f}")
                return
            item = cart.agregar_por_barcode(command)
            warning = "  [SUPERA EXISTENCIA]" if item.cantidad > item.existencia else ""
            print(f"{item.clave or item.descripcion or item.producto_id} | ${centavos_a_decimal(item.precio_unitario_centavos):.2f} | Cantidad {item.cantidad} | Existencia {item.existencia}{warning}")
        except (ValueError, LookupError) as exc:
            print(f"ERROR: {exc}")


def _show_cart(cart):
    print("\nCARRITO")
    for item in cart.items:
        print(f"{item.producto_id}: {item.clave or item.descripcion} x{item.cantidad} = ${centavos_a_decimal(item.subtotal_centavos):.2f}")
    print(f"Artículos: {cart.cantidad_articulos} | Total: ${centavos_a_decimal(cart.total_centavos):.2f}")


if __name__ == "__main__":
    main()
