from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessConfig:
    nombre_negocio: str = "FERRETERÍA"
    direccion: str = "Dirección pendiente de configurar"
    telefono: str = "Teléfono pendiente"
    mensaje_ticket: str = "Gracias por su compra"


BUSINESS_CONFIG = BusinessConfig()
