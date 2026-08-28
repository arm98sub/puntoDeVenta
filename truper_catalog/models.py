from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Product:
    codigo: str
    clave: str
    descripcion: str
    marca: str
    categoria: str
    codigo_barras: str = ""

    @property
    def identity(self) -> tuple[str, str]:
        return self.codigo.strip(), self.clave.strip().upper()
