from dataclasses import dataclass
from math import ceil

from ferreteria_core.repositories import ProductRepository


@dataclass(frozen=True)
class ProductPage:
    products: list
    page: int
    page_size: int
    total: int
    term: str
    exact_match: str | None = None
    product_filter: str = "TODOS"
    sort_column: str = "descripcion"
    sort_direction: str = "ASC"

    @property
    def pages(self):
        return max(1, ceil(self.total / self.page_size))

    @property
    def start(self):
        return 0 if not self.products else (self.page - 1) * self.page_size + 1

    @property
    def end(self):
        return min(self.page * self.page_size, self.total)


class ProductQueryService:
    def __init__(self, database):
        self.database = database

    def buscar_inteligente(self, term="", *, page=1, page_size=50, product_filter="TODOS", sort_column="descripcion", sort_direction="ASC"):
        if not isinstance(page, int) or page < 1:
            raise ValueError("La página debe ser un entero positivo")
        term = (term or "").strip()
        with self.database.connect() as connection:
            if term and page == 1:
                for field in ("codigo_barras", "codigo_truper", "clave"):
                    product = ProductRepository.exact(connection, field, term)
                    if product and ProductRepository.matches_filter(connection,product.id,product_filter):
                        return ProductPage([product],1,page_size,1,term,field,product_filter,sort_column,sort_direction)
            total = ProductRepository.count_page(connection, term, product_filter)
            products = ProductRepository.list_page(connection,term=term,product_filter=product_filter,sort_column=sort_column,sort_direction=sort_direction,limit=page_size,offset=(page-1)*page_size)
            return ProductPage(products,page,page_size,total,term,None,product_filter,sort_column,sort_direction)

    def contar_productos(self, term="", product_filter="TODOS"):
        with self.database.connect() as connection:
            return ProductRepository.count_page(connection,term,product_filter)

    def listar_productos_paginados(self, **kwargs):
        return self.buscar_inteligente(**kwargs)
