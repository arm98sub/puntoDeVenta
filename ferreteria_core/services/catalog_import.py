import csv
from pathlib import Path

from ferreteria_core.money import decimal_a_centavos


def importar_catalogo_truper(database, csv_path: str | Path) -> dict:
    """Sincroniza por codigo_truper sin tocar datos locales operativos."""
    rows = []
    seen = set()
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as source:
        for line, raw in enumerate(csv.DictReader(source), start=2):
            code = _text(raw.get("codigo_truper"))
            if not code:
                raise ValueError(f"Fila {line}: codigo_truper vacío")
            if code in seen:
                raise ValueError(f"Fila {line}: codigo_truper duplicado: {code}")
            seen.add(code)
            public_price = decimal_a_centavos(raw.get("precio_catalogo_publico"))
            sale_price = decimal_a_centavos(raw.get("precio_venta"))
            rows.append({
                "codigo": code, "clave": _text(raw.get("clave")), "descripcion": _text(raw.get("descripcion")),
                "familia": _text(raw.get("descripcion_familia")), "presentacion": _text(raw.get("presentacion")),
                "marca": _text(raw.get("marca")), "categoria": _text(raw.get("categoria")),
                "publico": public_price, "venta": sale_price if sale_price is not None else public_price,
                "completos": _bool(raw.get("datos_completos")), "confianza": _text(raw.get("confianza_extraccion")),
                "revision": _bool(raw.get("requiere_revision"), default=True),
            })
    inserted = updated = 0
    database.migrate()
    with database.transaction() as connection:
        for row in rows:
            existing = connection.execute("SELECT id FROM productos WHERE codigo_truper=?", (row["codigo"],)).fetchone()
            if existing:
                connection.execute(
                    """UPDATE productos SET
                       clave=CASE WHEN (clave IS NULL OR clave='') AND :clave IS NOT NULL THEN :clave ELSE clave END,
                       descripcion=CASE WHEN (descripcion IS NULL OR descripcion='') AND :descripcion IS NOT NULL THEN :descripcion ELSE descripcion END,
                       descripcion_familia=CASE WHEN (descripcion_familia IS NULL OR descripcion_familia='') AND :familia IS NOT NULL THEN :familia ELSE descripcion_familia END,
                       presentacion=CASE WHEN (presentacion IS NULL OR presentacion='') AND :presentacion IS NOT NULL THEN :presentacion ELSE presentacion END,
                       marca=CASE WHEN (marca IS NULL OR marca='') AND :marca IS NOT NULL THEN :marca ELSE marca END,
                       categoria=CASE WHEN (categoria IS NULL OR categoria='') AND :categoria IS NOT NULL THEN :categoria ELSE categoria END,
                       precio_catalogo_publico=COALESCE(:publico,precio_catalogo_publico),
                       datos_completos=MAX(datos_completos,:completos),
                       confianza_extraccion=COALESCE(confianza_extraccion,:confianza),
                       requiere_revision=MAX(requiere_revision,:revision),
                       updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE codigo_truper=:codigo""", row)
                updated += 1
            else:
                connection.execute(
                    """INSERT INTO productos
                       (codigo_truper,clave,descripcion,descripcion_familia,presentacion,marca,categoria,
                        precio_catalogo_publico,precio_venta,existencia,stock_minimo,es_truper,
                        datos_completos,confianza_extraccion,requiere_revision,activo)
                       VALUES (:codigo,:clave,:descripcion,:familia,:presentacion,:marca,:categoria,
                               :publico,:venta,0,0,1,:completos,:confianza,:revision,1)""", row)
                inserted += 1
    return {"leidos": len(rows), "insertados": inserted, "actualizados": updated}


def _text(value):
    value = (value or "").strip()
    if len(value) > 1 and value[0] == "'" and value[1] in "=+-@":
        value = value[1:]
    return value or None


def _bool(value, default=False):
    if value is None or str(value).strip() == "":
        return int(default)
    return int(str(value).strip().lower() in {"1", "true", "sí", "si", "yes"})
