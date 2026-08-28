import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class BusinessSettings:
    nombre_negocio: str
    direccion: str | None
    telefono: str | None
    rfc: str | None
    logo_path: str | None
    mensaje_ticket: str | None
    moneda: str


class BusinessConfigService:
    def __init__(self,database,branding_dir="data/branding"):
        self.database=database;self.branding_dir=Path(branding_dir)

    def obtener(self):
        self.database.migrate()
        with self.database.connect() as connection:
            row=connection.execute("SELECT * FROM configuracion_negocio WHERE id=1").fetchone()
        values={name:row[name] for name in BusinessSettings.__dataclass_fields__};logo=values.get("logo_path")
        if logo and not Path(logo).is_absolute():values["logo_path"]=str((self.branding_dir/logo).resolve())
        return BusinessSettings(**values)

    def guardar(self,*,nombre_negocio,direccion="",telefono="",rfc="",mensaje_ticket="",moneda="MXN",logo_origen=None):
        name=(nombre_negocio or "").strip()
        if not name:raise ValueError("El nombre del negocio es obligatorio")
        if moneda!="MXN":raise ValueError("Por ahora la moneda debe ser MXN")
        current=self.obtener();logo=current.logo_path
        if logo_origen:
            source=Path(logo_origen)
            if source.suffix.lower() not in {".png",".jpg",".jpeg"}:raise ValueError("El logo debe ser PNG, JPG o JPEG")
            try:
                with Image.open(source) as image:image.verify()
            except Exception as exc:raise ValueError("El archivo no es una imagen válida") from exc
            self.branding_dir.mkdir(parents=True,exist_ok=True);target=self.branding_dir/f"logo{source.suffix.lower()}"
            if source.resolve()!=target.resolve():shutil.copy2(source,target)
            logo=target.name
        values=(name,_clean(direccion),_clean(telefono),_clean(rfc),logo,_clean(mensaje_ticket),moneda)
        with self.database.transaction() as connection:
            connection.execute("""UPDATE configuracion_negocio SET nombre_negocio=?,direccion=?,telefono=?,rfc=?,logo_path=?,mensaje_ticket=?,moneda=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=1""",values)
        return self.obtener()


def _clean(value):
    value=(value or "").strip();return value or None
