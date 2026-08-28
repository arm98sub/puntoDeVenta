import argparse
import shutil
import sqlite3
from pathlib import Path

from ferreteria_core.services import validar_respaldo


def main():
    parser=argparse.ArgumentParser(description="Copia explícita y segura de datos reales a la distribución")
    parser.add_argument("--source",required=True);parser.add_argument("--destination",required=True);parser.add_argument("--confirm-real-data",action="store_true");args=parser.parse_args()
    if not args.confirm_real_data:raise SystemExit("Falta --confirm-real-data")
    source=Path(args.source).resolve();destination=Path(args.destination).resolve();validar_respaldo(source);destination.parent.mkdir(parents=True,exist_ok=True)
    src=sqlite3.connect(source);dst=sqlite3.connect(destination)
    try:src.backup(dst)
    finally:dst.close();src.close()
    validar_respaldo(destination)
    source_branding=source.parent/"branding";target_branding=destination.parent/"branding";target_branding.mkdir(parents=True,exist_ok=True)
    if source_branding.exists():
        for item in source_branding.iterdir():
            if item.is_file() and item.suffix.lower() in {".png",".jpg",".jpeg"}:shutil.copy2(item,target_branding/item.name)
    with sqlite3.connect(destination) as connection:
        row=connection.execute("SELECT logo_path FROM configuracion_negocio WHERE id=1").fetchone()
        if row and row[0]:
            logo_name=Path(row[0]).name
            if (target_branding/logo_name).is_file():connection.execute("UPDATE configuracion_negocio SET logo_path=? WHERE id=1",(logo_name,))
    source_tickets=source.parent.parent/"tickets";target_tickets=destination.parent.parent/"tickets"
    if source_tickets.exists():
        for item in source_tickets.rglob("*.pdf"):
            relative=item.relative_to(source_tickets);target=target_tickets/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,target)
    source_backups=source.parent.parent/"backups";target_backups=destination.parent.parent/"backups"
    if source_backups.exists():
        for item in source_backups.rglob("*.db"):
            validar_respaldo(item);relative=item.relative_to(source_backups);target=target_backups/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,target)
    print(destination)


if __name__=="__main__":main()
