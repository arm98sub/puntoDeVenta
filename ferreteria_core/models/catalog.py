from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id:int
    nombre:str
    activo:bool

    @classmethod
    def from_row(cls,row):return cls(row["id"],row["nombre"],bool(row["activo"]))


@dataclass(frozen=True)
class Supplier:
    id:int
    nombre:str
    telefono:str|None
    contacto:str|None
    notas:str|None
    activo:bool

    @classmethod
    def from_row(cls,row):return cls(row["id"],row["nombre"],row["telefono"],row["contacto"],row["notas"],bool(row["activo"]))
