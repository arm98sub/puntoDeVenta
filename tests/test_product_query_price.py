from decimal import Decimal

import pytest

from ferreteria_core import Database
from ferreteria_core.services import ProductQueryService, ProductService, SalesService


@pytest.fixture
def db(tmp_path):
    value=Database(tmp_path/"query.db"); value.migrate(); return value


def make(db,index,description=None,price="10",stock=20,clave=None,barcode=None):
    return ProductService(db).crear_producto_externo(barcode or f"75000000{index:05d}",description or f"Producto {index:03d}",Decimal(price),stock,clave=clave)


def test_actualizar_precio_y_catalogo_independiente(db):
    p=make(db,1,price="51")
    with db.connect() as c:c.execute("UPDATE productos SET precio_catalogo_publico=5100 WHERE id=?",(p.id,))
    updated=ProductService(db).actualizar_precio_venta(p.id,Decimal("55.25"))
    assert updated.precio_venta==5525 and updated.precio_catalogo_publico==5100


def test_precio_cero_permitido(db):assert ProductService(db).actualizar_precio_venta(make(db,1).id,Decimal("0")).precio_venta==0


def test_precio_negativo_rechazado(db):
    with pytest.raises(ValueError):ProductService(db).actualizar_precio_venta(make(db,1).id,Decimal("-0.01"))


def test_venta_nueva_precio_nuevo_historico_conservado(db):
    p=make(db,1,price="51"); service=SalesService(db); first=service.crear_venta([{"producto_id":p.id,"cantidad":1}],"TARJETA")
    ProductService(db).actualizar_precio_venta(p.id,Decimal("55")); second=service.crear_venta([{"producto_id":p.id,"cantidad":1}],"TARJETA")
    assert service.obtener_por_id(first.id).detalles[0].precio_unitario_centavos==5100
    assert second.detalles[0].precio_unitario_centavos==5500


def populated(db,count=123):
    for i in range(count):make(db,i,description=f"Artículo {i:03d}")
    return ProductQueryService(db)


def test_contar_y_primera_pagina(db):
    q=populated(db); page=q.listar_productos_paginados(page=1,page_size=50)
    assert page.total==123 and len(page.products)==50 and page.start==1 and page.end==50


def test_pagina_intermedia_y_ultima(db):
    q=populated(db); middle=q.listar_productos_paginados(page=2,page_size=50); last=q.listar_productos_paginados(page=3,page_size=50)
    assert len(middle.products)==50 and middle.start==51 and len(last.products)==23 and last.end==123


def test_pagina_fuera_de_rango_vacia(db):
    page=populated(db,3).listar_productos_paginados(page=9,page_size=2)
    assert page.total==3 and page.products==[]


def test_maximo_page_size(db):
    q=populated(db,2)
    assert len(q.listar_productos_paginados(page_size=200).products)==2
    with pytest.raises(ValueError):q.listar_productos_paginados(page_size=201)


def test_orden_estable(db):
    make(db,1,description="Mismo"); make(db,2,description="Mismo"); q=ProductQueryService(db)
    first=[p.id for p in q.listar_productos_paginados(page_size=1).products]; second=[p.id for p in q.listar_productos_paginados(page=2,page_size=1).products]
    assert first[0]<second[0]


def test_busqueda_barcode_codigo_y_clave_exactos(db):
    p=make(db,1,clave="SIL-85T",barcode="7501206683729")
    with db.connect() as c:c.execute("UPDATE productos SET codigo_truper='17562',es_truper=1 WHERE id=?",(p.id,))
    q=ProductQueryService(db)
    assert q.buscar_inteligente("7501206683729").exact_match=="codigo_barras"
    assert q.buscar_inteligente("17562").exact_match=="codigo_truper"
    assert q.buscar_inteligente("SIL-85T").exact_match=="clave"


def test_prioridad_barcode_sobre_clave(db):
    barcode=make(db,1,barcode="ABCD"); make(db,2,clave="ABCD")
    result=ProductQueryService(db).buscar_inteligente("ABCD")
    assert result.exact_match=="codigo_barras" and result.products[0].id==barcode.id


def test_busqueda_textual_sin_acentos_y_paginada(db):
    for i in range(60):make(db,i,description=f"Silicón especial {i}")
    page=ProductQueryService(db).buscar_inteligente("silicon",page=2,page_size=50)
    assert page.total==60 and len(page.products)==10


def test_busqueda_inexistente_y_limpieza(db):
    q=populated(db,3); assert q.buscar_inteligente("NO-EXISTE").total==0
    assert q.buscar_inteligente("").total==3
