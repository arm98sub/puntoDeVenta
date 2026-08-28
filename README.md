# Extractor inicial del catálogo público de Truper

> La fase de extracción está cerrada. El código siguiente del núcleo POS trabaja
> únicamente con archivos locales; no realiza consultas HTTP ni procesa el PDF.

## Núcleo local de productos e inventario

El paquete `ferreteria_core` es independiente de cualquier interfaz y está dividido
en `database/` (conexión y migraciones), `models/`, `repositories/` y `services/`.
La base predeterminada es `data/ferreteria.db`; los archivos `.db` reales están
excluidos de Git. `schema_migrations` permite aplicar nuevas versiones sin recrear
ni borrar la base.

`productos` admite artículos Truper y externos, identificadores opcionales y baja
lógica mediante `activo`. `movimientos_inventario` registra cada entrada o ajuste.
Los importes de `precio_catalogo_publico` y `precio_venta` son **centavos enteros**
en SQLite: 35.00 se persiste como 3500. La API recibe/entrega `Decimal` mediante
`decimal_a_centavos` y `centavos_a_decimal`; nunca usa `float` para dinero.

### Inicialización e importación local

```powershell
.venv\Scripts\python.exe pos_cli.py init-db
.venv\Scripts\python.exe pos_cli.py importar output/catalogo_truper_enriquecido.csv
```

La importación se sincroniza por `codigo_truper`. Al repetirla actualiza el precio
público y completa campos vacíos, pero no duplica registros ni modifica el código
de barras, existencia o precio de venta local; tampoco toca productos externos.
Los productos incompletos se conservan y quedan marcados para revisión.

### CLI de desarrollo

```powershell
python pos_cli.py buscar-truper 10013
python pos_cli.py buscar-clave M-10B
python pos_cli.py buscar-descripcion martillo
python pos_cli.py buscar-barcode 7501234567890
python pos_cli.py mostrar 1
python pos_cli.py vincular-barcode 1 7501234567890
python pos_cli.py existencia-inicial 1 8
python pos_cli.py entrada 1 4 --nota "Compra local"
python pos_cli.py ajustar 1 10 "Conteo físico"
python pos_cli.py crear-externo 7500000000001 "Producto externo" 35.50 6 --marca OTRA
```

La vinculación rechaza códigos ya usados y nunca reemplaza silenciosamente uno
existente. El alta externa y todos los cambios de existencia son transaccionales.
`InitialInventoryService` compone búsqueda por escaneo, vinculación y captura de
existencia inicial en una sola transacción para la futura pantalla de alta rápida.

### Respaldo y pruebas

```powershell
python pos_cli.py backup
python -m pytest -q
```

El respaldo usa la API `sqlite3.Connection.backup`, no una copia insegura del
archivo abierto, y genera `backups/ferreteria_AAAA-MM-DD_HHMMSS.db`. Las pruebas
crean SQLite sólo en directorios temporales y nunca modifican la base real.

## Ventas transaccionales

La migración 2 agrega `ventas` y `detalle_venta`. Los folios son secuenciales y
legibles (`V-000001`, `V-000002`), calculados bajo `BEGIN IMMEDIATE`; un rollback
no deja una venta parcial ni consume el siguiente folio. El detalle conserva
snapshots de barcode, código Truper, clave, descripción y precio unitario, por lo
que el historial no cambia cuando posteriormente se edita o desactiva el producto.

Estados: `COMPLETADA` y `CANCELADA`. Métodos: `EFECTIVO`, `TRANSFERENCIA`,
`TARJETA` y `OTRO`. Todos los cálculos permanecen en centavos enteros; la entrada
de efectivo y descuento usa `Decimal`. En efectivo se exige un importe suficiente
y se calcula el cambio exacto. En otros métodos, recibido y cambio quedan `NULL`.

`SalesService.crear_venta` reconsulta productos, precios y stock, y dentro de una
sola transacción crea cabecera, detalles, descuenta existencias y registra todos
los movimientos. La convención del kardex es: entradas/devoluciones positivas y
salidas por venta negativas. Por ejemplo, dos unidades vendidas crean `cantidad=-2`
y `referencia=VENTA:V-000001`. La cancelación es transaccional, cambia el estado,
anexa el motivo, devuelve el stock con `DEVOLUCION` positiva y conserva todo el
historial original.

### Comandos de ventas

```powershell
# Venta en efectivo: producto 2518, cantidad 1, recibe $100 y descuenta $5
.venv\Scripts\python.exe pos_cli.py crear-venta 2518:1 --metodo EFECTIVO --efectivo 100.00 --descuento 5.00

# Varios productos y pago con tarjeta
.venv\Scripts\python.exe pos_cli.py crear-venta 2518:2 500:1 --metodo TARJETA

.venv\Scripts\python.exe pos_cli.py ver-venta V-000001
.venv\Scripts\python.exe pos_cli.py ver-venta 1
.venv\Scripts\python.exe pos_cli.py ultimas-ventas --limite 10
.venv\Scripts\python.exe pos_cli.py ventas-rango 2026-08-01 2026-08-31T23:59:59
.venv\Scripts\python.exe pos_cli.py cancelar-venta 1 "Devolución del cliente"
```

### Prueba física con lector USB

```powershell
.venv\Scripts\python.exe pos_cli.py venta-interactiva
```

Escanee el barcode y pulse Enter si el lector no lo envía automáticamente. Cada
escaneo repetido incrementa la misma línea. Use `TOTAL`, `QUITAR` (después escanee
el código solicitado), `CANCELAR` o `COBRAR`. Al cobrar, capture método, descuento
y, para efectivo, el importe recibido. La venta sólo se confirma después de una
nueva validación de existencia; cerrar con `CANCELAR` no persiste nada.

## Interfaz gráfica de escritorio

La aplicación usa **PySide6**, el enlace oficial de Qt para Python. Se eligió por
su soporte estable de Windows, tablas y diálogos nativos, atajos de teclado y buen
manejo del foco requerido por lectores HID. La GUI vive en `ferreteria_gui/` y es
una capa de presentación: consume `Cart`, `ProductService`, `InventoryService`,
`InitialInventoryService` y `SalesService`; no replica reglas de negocio.

Instale las dependencias y abra el POS:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe pos_app.py
```

La ruta predeterminada es `data/ferreteria.db`. Para usar otra base sin modificar
código, defina `FERRETERIA_DB` antes de iniciar la aplicación. Los errores técnicos
se escriben como `logs/pos_AAAA-MM-DD.log`; al usuario sólo se le muestra un mensaje
comprensible y no un traceback.

### Flujo gráfico de venta

1. La aplicación abre directamente en Punto de venta con foco en el scanner.
2. Escanee cada producto; los escaneos repetidos incrementan la misma línea.
3. Ajuste cantidades con los botones, escriba un descuento monetario si aplica y
   presione `F4` o **COBRAR**.
4. Seleccione efectivo, transferencia, tarjeta u otro. En efectivo capture lo
   recibido y verifique el cambio calculado en tiempo real.
5. Confirme. Al cerrar **Nueva venta**, el carrito se limpia y el scanner recupera
   el foco automáticamente.

Un barcode desconocido ofrece buscar y vincular un producto Truper o crear uno
externo. La vinculación permite buscar por código Truper, clave o descripción y
capturar existencia inicial. El alta externa solicita barcode, descripción, marca
opcional, precio y existencia.

Las secciones laterales permiten:

- **Productos:** buscar por barcode, código Truper, clave o descripción y abrir
  los flujos de vinculación/alta.
- **Inventario:** consultar producto, registrar una entrada o ajustar existencia
  con motivo; ambas acciones usan el kardex existente.
- **Historial:** consultar las últimas ventas, abrir snapshots del detalle y
  cancelar una venta completada con confirmación y motivo.

Atajos:

- `F2`: volver al punto de venta y enfocar el scanner.
- `F4`: abrir el cobro.
- `Delete`: quitar la línea seleccionada.
- `Esc`: cerrar el diálogo activo sin confirmar.

### Búsqueda inteligente y paginación

Productos e Inventario usan un solo campo **Buscar o escanear producto**. Al
presionar Enter se consulta, en este orden, coincidencia exacta de barcode,
`codigo_truper` y clave. Sólo cuando ninguna coincide se realiza búsqueda parcial
normalizada (sin distinguir mayúsculas ni acentos) en descripción, clave, códigos
Truper y barcode. Un scanner HID no necesita elegir el tipo de identificador.

Las tablas consultan SQLite con `LIMIT`/`OFFSET`, 50 productos por página, y orden
estable por descripción, clave o código más `id`. Al borrar el filtro reaparece la
primera página del catálogo. La migración 3 conserva el índice de clave y convierte
los índices únicos de barcode y código Truper en índices completos; SQLite permite
múltiples valores `NULL` y así puede usar esos índices en búsquedas exactas.

La selección siempre abarca una fila, permite una sola selección y mantiene un
contraste visible aunque la tabla pierda foco. Las acciones quedan deshabilitadas
sin selección. Si una edición conserva el producto en la página, la fila se vuelve
a seleccionar después del refresco.

### Edición de precio

Seleccione una fila en Productos o Inventario y pulse **Editar precio**. El diálogo
muestra precio de catálogo y precio de venta por separado. Sólo actualiza
`precio_venta` mediante `ProductService.actualizar_precio_venta`; recibe `Decimal`,
persiste centavos enteros y no cambia el precio de catálogo. Las ventas anteriores
conservan el precio snapshot y las futuras usan el nuevo valor.

### Tickets digitales PDF

Después de confirmar la transacción, el POS genera localmente un PDF con ReportLab.
El ticket mide 80 mm de ancho, ajusta su altura al contenido y usa exclusivamente
los snapshots de `ventas`/`detalle_venta`. Un fallo de PDF se registra en `logs/`
pero nunca revierte ni repite la venta confirmada.

Los archivos operativos se guardan en:

```text
tickets/YYYY/MM/V-000001.pdf
```

Un archivo existente sólo se reutiliza si sus metadatos corresponden al folio; no
se sobrescribe silenciosamente. En Historial, **Abrir ticket** lo genera si falta y
lo abre; **Regenerar ticket** reemplaza explícitamente el PDF usando los snapshots.
Las ventas canceladas incluyen `*** VENTA CANCELADA ***` sin perder sus importes.

Los datos del negocio se editan en la pantalla **Configuración** y se guardan en
SQLite (`configuracion_negocio`). Incluyen nombre, dirección, teléfono, RFC,
mensaje, moneda MXN y logo.

## Mejoras previas a versión 1.0

### Descripción, filtros y orden

Productos e Inventario comparten los diálogos **Editar descripción** y **Editar
precio**. La descripción es local: no cambia código Truper, clave ni snapshots de
ventas anteriores. Las ventas futuras usan el nuevo texto.

El filtro se combina con búsqueda, orden SQL y paginación de 50 filas. Opciones:
Todos, con/sin existencia, con/sin precio, con/sin descripción, Truper, externos y
requieren revisión. Pulse un encabezado para alternar ascendente/descendente; se
pueden ordenar código Truper, barcode, clave, descripción/producto, marca, precio,
existencia y activo según las columnas visibles. Tanto filtro como orden ocurren
en SQLite antes de `LIMIT`/`OFFSET`.

### Configuración y branding

La navegación incluye **Configuración** para nombre, dirección, teléfono, RFC,
mensaje del ticket y logo PNG/JPG/JPEG. El logo seleccionado se valida y se copia,
sin alterar el original, a:

```text
data/branding/
```

El encabezado del POS y los tickets leen esta configuración dinámica. El logo se
escala conservando proporciones y el ticket omite líneas vacías. La tabla forma
parte de los respaldos SQLite existentes.

### Importación genérica

En Productos, **Importar productos** acepta CSV o XLSX y muestra encontrados,
nuevos, duplicados y errores antes de confirmar. Nunca sobrescribe un barcode
existente. Los artículos se crean como externos (`codigo_truper=NULL`,
`es_truper=false`) y el precio se procesa con `Decimal`.

Plantilla: `docs/plantilla_productos.csv`. Columnas obligatorias:
`codigo_barras`, `descripcion`, `precio`, `existencia`. Opcionales: `clave`,
`marca`, `categoria`, `stock_minimo`.

### Stock durante una venta

El carrito ya no acepta cantidad superior a la existencia. Ante stock cero o
insuficiente ofrece **Actualizar existencia** sin perder carrito ni descuento:

- Corregir existencia crea `AJUSTE`.
- Llegó mercancía nueva crea `ENTRADA` por la diferencia.

Después de guardar se reintenta la cantidad solicitada y vuelve el foco al scanner.
La validación final dentro de `crear_venta()` permanece activa.

El carrito muestra Existencia y marca `LÍMITE` cuando la cantidad utiliza todo el
stock disponible.

### Teclado y foco

El orden Tab sigue el flujo principal, los controles enfocados tienen borde naranja
de alto contraste y los botones aceptan Enter o Espacio sin duplicar eventos.

- `F2`: scanner.
- `F4`: cobrar.
- `Delete`: quitar línea del carrito.
- `Ctrl+F`: buscador de la pantalla actual.
- `F5`: refrescar la pantalla actual.
- `Esc`: cerrar el diálogo activo.

Prototipo en Python para crear una **muestra pequeña** del catálogo inicial de una
ferretería. No es un punto de venta ni realiza una descarga masiva.

## Lo observado en el sitio (18 de agosto de 2026)

La portada pública carga `buscador_cat.js`. Ese archivo hace un `POST` a:

`https://www.truper.com/CatVigente/producto/searching`

con un formulario `word=<código, clave o descripción>` y espera JSON. Cada elemento
de `data` contiene, entre otros, `codigo`, `clave`, `pn`, `url` y `pages`. El
extractor usa esos tres primeros campos como código, SKU y descripción.

- **Categoría:** el JSON no la entrega como atributo inequívoco de cada producto.
  Cada resultado sí incluye una página y el extractor lee una vez su `<title>`, con
  caché, para obtener el nombre de categoría.
- **Marca:** no existe como campo separado en la respuesta observada. Se conserva
  sólo cuando la descripción termina explícitamente con una de las marcas mostradas
  por el sitio. Si no hay evidencia, queda vacía; no se inventa.
- No se consultan precios ni existencias.

## Instalación y ejecución

Requiere Python 3.10 o posterior.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python extract_sample.py --term martillo --limit 5
```

El resultado predeterminado es `output/truper_sample.csv`, codificado como UTF-8
con BOM para facilitar su apertura en Excel. Puede buscar por código o clave:

```powershell
python extract_sample.py --term 10200 --limit 1 --output output/por_codigo.csv
```

La pausa mínima predeterminada entre solicitudes es de un segundo. Puede aumentarse
con `--pause`; no se recomienda reducirla. `--limit` limita los resultados escritos,
pero una búsqueda puede requerir una visita por cada página de categoría distinta.

## Diseño

- `truper_catalog/extractor.py`: cliente HTTP y transformación de datos.
- `truper_catalog/storage.py`: deduplicación y almacenamiento CSV.
- `truper_catalog/models.py`: modelo independiente del proveedor.
- `extract_sample.py`: CLI deliberadamente pequeña.
- `tests/`: pruebas locales sin golpear el sitio.

La clave de deduplicación para una corrida ampliada es `codigo`, conservando también
la `clave` original.
El modelo puede ampliarse después para otros proveedores sin hacer que el futuro POS
dependa del sitio de Truper.

## Pruebas

```powershell
python -m pytest -q
```

El sitio puede cambiar su HTML o JSON. El extractor no evade autenticación,
CAPTCHA, bloqueos ni controles de acceso; ante un error HTTP termina y lo muestra.

## Estrategia ampliada y reanudación

El autocompletado exige términos de 4 a 65 caracteres, devuelve como máximo cinco
productos y no informa total ni página. La página `/buscador`, en cambio, entrega
una tabla paginada (30 productos observados por página) con marca, código, clave,
descripción y vínculo de categoría. La estrategia propuesta es consultar las marcas
oficiales visibles en el menú (`truper`, `pretul`, `volteck`, `foset`, `fiero`,
`hermex`, `klintek`) y deduplicar por código. Como auditoría futura, las páginas del
catálogo y `/ficha/fichas` permiten obtener por lotes los códigos y claves de cada
módulo para detectar posibles faltantes.

Prueba ampliada limitada (no es una extracción completa):

```powershell
python extract_expanded_sample.py --limit 50 --term truper
```

Se escriben `state/truper_checkpoint.json` y, sólo si hay fallos,
`logs/truper_errors.jsonl`. Al repetir el comando se carga el CSV existente y se
omiten las páginas completadas. Timeout, pausa y reintentos se ajustan con
`--timeout`, `--delay` y `--retries`.

## Investigación de códigos de barras

`research_barcodes.py` inspecciona entre 1 y 20 fichas públicas y el endpoint
`/ficha_tecnica/findProductsCod`. Busca etiquetas explícitas EAN, UPC, GTIN,
barcode o código de barras; nunca calcula ni supone el valor a partir de `codigo`.

```powershell
python research_barcodes.py --limit 10 --delay 1
```

Genera `output/truper_barcode_sample.csv` y un reporte de evidencia JSON. El campo
`codigo_barras` es opcional y queda vacío cuando la web no publica uno verificable.

## Extracción completa y validación

Ejecutar las siete marcas y luego validar códigos mediante `/ficha/fichas`:

```powershell
python build_full_catalog.py --delay 1
```

Después de completar la auditoría, recupere los códigos faltantes por prefijos
numéricos. La pausa predeterminada es de cinco segundos y cualquier HTTP 429 detiene
la ejecución para reanudarla más tarde sin evasión:

```powershell
python recover_missing_catalog.py --delay 5
```

La recuperación masiva por prefijos está deshabilitada operativamente después de
haber recibido HTTP 429. No la ejecute automáticamente. El catálogo maestro se
construye localmente, sin red, combinando el catálogo enriquecido y los identificadores
de `/ficha/fichas`:

```powershell
python build_master_catalog.py
```

Archivos maestros generados:

- `output/catalogo_truper_master.csv`
- `output/catalogo_truper_master.xlsx`
- `output/reporte_catalogo_master.json`

Los registros con `datos_completos=false` conservan únicamente `codigo_truper` y
la `clave` publicada por la ficha. No se inventan descripción, marca ni categoría.

Para enriquecer posteriormente un solo producto solicitado explícitamente:

```python
from truper_catalog.enrichment import enriquecer_producto

producto = enriquecer_producto("16702")
```

La función nunca procesa listas y se detiene inmediatamente ante HTTP 429.

El proceso guarda el CSV y los checkpoints después de cada página. Para continuar
una ejecución interrumpida, ejecute exactamente el mismo comando. Para empezar de
cero use `--fresh --fresh-validation`; esto ignora los checkpoints y el CSV previos.

- CSV final: `output/catalogo_truper.csv`
- Excel para carga manual: `output/catalogo_truper.xlsx`
- Reporte de extracción: `output/reporte_extraccion.json`
- Reporte de validación: `output/reporte_validacion.json`
- Errores HTTP: `logs/catalogo_errors.jsonl`

El reporte de validación compara los códigos obtenidos por búsquedas de marca con
los códigos de módulos publicados por `/ficha/fichas`. `codes_only_in_ficha_fichas`
son faltantes potenciales; sólo se incorporan cuando una búsqueda exacta por código
devuelve clave y descripción confiables.

## Prueba local con el catálogo PDF 2026

`extract_pdf_sample.py` lee exclusivamente el archivo local
`catalogo_nacional_2026.pdf`; no realiza solicitudes HTTP ni reanuda la recuperación
individual. El PDF se ignora en Git y nunca se modifica ni se mueve.

La prueba predeterminada abre 15 páginas de producto no consecutivas, distribuidas
entre el inicio, centro y final del catálogo, y escribe todos los códigos maestros
hallados únicamente en esas páginas:

```powershell
python extract_pdf_sample.py
```

Salida: `output/prueba_catalogo_pdf.csv`. El catálogo maestro CSV/XLSX no se altera.
Los 11,124 códigos maestros funcionan como anclas para descartar números que sean
medidas, precios o páginas. El parser también normaliza a dígitos los glifos de la
fuente interna del PDF y conserva precios como decimales sin `$` ni separadores de
miles.

`estado_previo` indica si el registro ya estaba `enriquecido` o `pendiente` en el
maestro. `requiere_revision=true` significa que faltó una clave coincidente, una
descripción de familia o el precio público; esos registros no deben aplicarse al
maestro automáticamente. Esta fase es deliberadamente una prueba: no recorre las
644 páginas ni modifica el catálogo completo.

### Validación ampliada del parser PDF

`validate_pdf_parser.py` compara el parser anterior y el parser por columnas sobre
72 páginas no consecutivas. Sólo evalúa productos previamente enriquecidos y usa
esa información después de extraer, como ground truth; nunca rellena claves o
descripciones con los datos maestros.

```powershell
python validate_pdf_parser.py
```

Genera `output/validacion_parser_pdf.csv` y
`output/reporte_validacion_parser.json`. El método nuevo mantiene `pdfplumber` para
coordenadas y usa `pypdf` para leer las fuentes embebidas. Cuando un subconjunto CID
no contiene `cmap`, empareja sus contornos `glyf` con la copia TrueType de la misma
familia que sí conserva Unicode. La confianza de clave se basa sólo en estructura;
una clave dudosa queda como `BAJA`, sin corrección por catálogo maestro.

### Extracción completa local del PDF

La extracción completa no usa Internet ni OCR. Procesa las páginas de producto,
omite los índices finales y conserva los 11,124 registros originales:

```powershell
python build_enriched_pdf_catalog.py
```

El comando normal reanuda `state/pdf_full_checkpoint.json`. Para descartar el
progreso y comenzar una corrida nueva use explícitamente:

```powershell
python build_enriched_pdf_catalog.py --fresh
```

El checkpoint se escribe atómicamente cada cinco páginas. Los resultados finales
sólo se reemplazan después de completar el merge. Archivos principales:

- `output/catalogo_truper_enriquecido.csv`
- `output/catalogo_truper_enriquecido.xlsx`
- `output/productos_requieren_revision.xlsx`
- `output/productos_pdf_no_master.csv`
- `output/reporte_extraccion_pdf_completa.json`

Los maestros originales no se sobrescriben. `precio_venta` se inicializa con el
precio público extraído, pero permanece como columna independiente. Los códigos que
aparecen sólo en el PDF se mantienen separados hasta una revisión humana.

## Distribución Windows 1.0.0

La aplicación usa PyInstaller en modo `onedir` y `windowed`: inicia con mayor
rapidez que `onefile`, no abre una consola y deja los datos persistentes fuera del
ejecutable. En desarrollo se abre con:

```powershell
.venv\Scripts\python.exe pos_app.py
```

Para instalar dependencias de ejecución o compilación:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-pos.txt
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

El build reproducible, sin datos reales, se genera así:

```powershell
.\build_windows.ps1
```

Para preparar explícitamente una copia destinada al negocio con un snapshot
validado de `data/ferreteria.db`, branding y tickets PDF históricos:

```powershell
.\build_windows.ps1 -IncludeRealData
```

La salida queda en `dist\PuntoDeVenta\` con esta estructura portable:

```text
PuntoDeVenta.exe
_internal\
data\ferreteria.db
data\branding\
tickets\
backups\manual\
backups\automatic\
logs\
```

Al ejecutar desde Python las rutas parten del proyecto. Al ejecutar el `.exe`
parten de la carpeta que contiene `PuntoDeVenta.exe`; también pueden dirigirse a
otra carpeta mediante `FERRETERIA_HOME`. Nunca se usa una carpeta temporal de
PyInstaller para la base.

### Respaldos y restauración

En **Configuración > Respaldos**, **Crear respaldo ahora** usa la API de backup de
SQLite y guarda una copia íntegra en `backups\manual\`. **Restaurar respaldo**
comprueba la cabecera SQLite, `integrity_check`, tablas obligatorias y versión de
migración. Antes de reemplazar los datos crea `pre_restore_*.db`; si algo falla,
conserva o recupera la base anterior. Los respaldos manuales nunca se eliminan.

Cada cierre normal crea un respaldo en `backups\automatic\`; sólo se conservan los
30 automáticos más recientes. **Abrir carpeta de respaldos** muestra su ubicación.
Los errores técnicos quedan en `logs\`.

### Migrar a otra computadora

1. Cierre el POS y copie completa la carpeta `dist\PuntoDeVenta\` a una unidad USB.
2. Copie esa carpeta completa a una ubicación escribible en la otra computadora.
3. Verifique que existan `data\ferreteria.db`, `data\branding\` y `tickets\`.
4. Abra `PuntoDeVenta.exe`; compruebe Productos, Inventario, Historial y Configuración.
5. Conecte el scanner HID, pulse F2 y escanee un producto conocido sin cobrarlo.
6. Cree un respaldo manual desde Configuración antes del primer día de operación.

Para crear un acceso directo sin privilegios de administrador, ejecute desde la
carpeta del proyecto:

```powershell
.\crear_acceso_directo.ps1
```

También puede usar **Enviar a > Escritorio (crear acceso directo)** sobre
`PuntoDeVenta.exe`. La versión 1.0.0 es portable; todavía no incluye instalador,
actualizaciones automáticas, nube ni impresión térmica.

## Funciones v1.1: venta por unidad y a granel

La migración 5 agrega `tipo_venta`, con valores `UNIDAD` y `GRANEL`. Todos los
productos anteriores conservan su funcionamiento y migran como `UNIDAD`; nunca se
clasifican automáticamente por descripción, marca o categoría.

- `UNIDAD` conserva `existencia` y `stock_minimo` como piezas enteras.
- `GRANEL` usa exclusivamente `existencia_granel_mg` y
  `stock_minimo_granel_mg`. Un kilogramo equivale a 1,000,000 mg.
- Para granel, `precio_venta` significa precio por kilogramo y se muestra como
  `$80.00 / kg`.

Los miligramos son sólo la representación interna exacta. El usuario captura y ve
gramos o kilogramos. La conversión de peso y los subtotales utilizan `Decimal` con
`ROUND_HALF_UP`: el peso termina en miligramos enteros y el dinero en centavos
enteros. No se usa `float`.

Al escanear un producto `GRANEL`, el POS abre un diálogo que permite vender por
**Peso** —capturando gramos como `62.5`— o por **Importe**, calculando el peso
aproximado. El carrito puede mezclar `2 pzas × $185.00` y
`38 g × $80.00/kg`. La existencia se valida al agregar y otra vez dentro de la
transacción de venta.

Los movimientos conservan cantidades exactas en mg y la cancelación devuelve el
peso vendido. Los detalles guardan snapshots del tipo, peso, unidad y precio por
kilogramo; los tickets históricos siguen usando sus datos originales.

### Productos y precios

La tabla admite selección múltiple estándar con Ctrl+clic y Shift+clic. **Editar
seleccionados** cambia únicamente el tipo de venta de las filas elegidas y conserva
cada precio. Cambiar a `GRANEL` advierte que los precios actuales pasarán a
interpretarse por kilogramo.

El **Modo edición** está bloqueado por defecto. Al activarlo aparece una franja
amarilla persistente y un contador. Sólo son editables directamente descripción,
categoría, tipo de venta y precio de venta. Código Truper, barcode, clave, marca,
precio de catálogo y campos internos están protegidos.

Los cambios permanecen en memoria hasta **Guardar cambios**. **Revisar cambios**
muestra los valores anteriores/nuevos y la advertencia UNIDAD → GRANEL. Todo el
lote se valida antes de una única transacción; cualquier valor inválido o error
provoca rollback completo. Cambiar de pantalla, página/filtro o cerrar con cambios
ofrece Guardar, Descartar y Cancelar.

### Existencias y movimientos

La pantalla muestra unidad, existencia y stock mínimo. Las entradas y ajustes de
`UNIDAD` usan piezas; para `GRANEL` se capturan kilogramos y se convierten
centralmente a mg. La existencia no es una celda normal de producto: cada cambio
genera siempre un movimiento `ENTRADA` o `AJUSTE` con valores anterior/nuevo y la
diferencia exacta.

La verificación visual con base temporal se ejecuta así:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv\Scripts\python.exe scripts\verify_v11_gui.py
Remove-Item Env:\QT_QPA_PLATFORM
```

Para probar v1.1 desde Python, sin reconstruir todavía el ejecutable:

```powershell
.venv\Scripts\python.exe pos_app.py
```

## Interfaz simplificada de mostrador

Esta iteración sustituye el modo edición por un flujo más directo. **Productos y
precios** muestra solamente Código, Barcode, Clave, Descripción, Tipo de venta,
Precio proveedor, Ganancia %, Precio venta, Control inventario y Activo. Categoría,
stock mínimo, IDs y flags técnicos permanecen en SQLite, pero no se exponen en la
tabla principal.

Los botones principales son **Nuevo**, **Modificar** e **Importar**. Vincular
barcode, cambiar el tipo de varios productos y activar/desactivar están agrupados
en **Más acciones**. Ctrl+clic y Shift+clic seleccionan únicamente las filas que se
modificarán.

El formulario **Modificar** reúne descripción, UNIDAD/GRANEL, precio catálogo
Truper, precio proveedor, ganancia, precio venta, control de inventario y estado.
Código, barcode y clave son informativos. Los tres precios representan conceptos
distintos:

- `precio_catalogo_publico`: referencia pública de Truper;
- `precio_proveedor`: costo real del negocio, en centavos y opcional;
- `precio_venta`: importe cobrado, en centavos.

`porcentaje_ganancia` se conserva como decimal exacto en texto normalizado. Al
cambiar costo o ganancia se propone `costo × (1 + ganancia/100)`. Al cambiar
directamente el precio de venta, éste prevalece y se recalcula la ganancia mostrada.
Todos los cálculos usan `Decimal` y `ROUND_HALF_UP`.

La tabla permite doble clic únicamente en Descripción, Precio proveedor, Ganancia
% y Precio venta. El valor se valida al terminar la edición y se guarda en una
transacción corta; un valor inválido restaura el dato persistido. Existencia,
barcode, código, clave, tipo, control de inventario y activo requieren sus acciones
explícitas.

### Inventario opcional

La migración 6 agrega `controla_inventario`, con `true` para todos los productos
existentes. Puede combinarse con UNIDAD o GRANEL. Cuando está desactivado, una venta
no valida ni descuenta stock, no crea movimiento `VENTA` y su cancelación no devuelve
existencia. Cuando está activado conserva la validación transaccional, movimientos y
devoluciones anteriores.

**Existencias y movimientos** prioriza el filtro *Con control de inventario* y
muestra Producto, Clave, Barcode, Precio venta, Existencia y Control inventario.
Sólo expone **Agregar existencia**, **Ajustar existencia** y **Ver movimientos**.

### Granel simplificado

El diálogo presenta simultáneamente **Cantidad (kg)** e **Importe ($)**. Editar uno
recalcula el otro sin señales recursivas. La cantidad se muestra con hasta cuatro
decimales de kg y se conserva internamente en mg enteros. Un granel sin control no
muestra ni valida existencia; uno controlado sí mantiene todas las validaciones.

Las columnas de Productos y Existencias usan encabezados redimensionables y cada
celda tiene tooltip con el contenido completo. El ancho inicial de Descripción es
amplio y el doble clic del separador conserva el ajuste estándar de Qt.

## Distribución portable v1.1.0

El build estable con datos reales crea primero un respaldo obligatorio
`pre_build_v1.1.0_*.db`, valida su integridad y después genera la carpeta portable:

```powershell
.\build_windows.ps1 -IncludeRealData
```

La carpeta completa `dist\PuntoDeVenta\` debe copiarse a `C:\PuntoDeVenta` o a
otra ubicación local escribible. No copie sólo el `.exe` y evite una carpeta
sincronizada por OneDrive. Las instrucciones sencillas están en
`INSTALAR_EN_OTRA_PC.txt`, incluido dentro de la distribución.

`crear_acceso_directo.ps1`, ejecutado desde la carpeta instalada, crea “Punto de
Venta.lnk” en el escritorio y apunta al `PuntoDeVenta.exe` situado junto al script.
No requiere administrador, firewall, servidor ni Internet. SmartScreen puede
advertir que el ejecutable no está firmado; no desactive la seguridad de Windows.

## Desarrollo v1.1.1: captura diaria rápida

Esta versión se ejecuta desde Python para validación manual; todavía no debe
generarse ni instalarse un build en la computadora del negocio:

```powershell
.venv\Scripts\python.exe pos_app.py
```

En **Productos y precios** y **Existencias y movimientos**, el campo único
*Buscar o escanear producto* recibe el scanner HID. Enter localiza y selecciona un
barcode conocido. Si la entrada parece un código escaneado y no existe, abre el
mismo diálogo **Registrar producto**, ya precargado con el barcode. **Nuevo F1**
abre ese diálogo para altas manuales o productos sin barcode.

Para Truper, escriba el código impreso y pulse **Buscar código Truper**. Si existe,
se recuperan código, clave, descripción, precio y existencia; el mismo guardado
vincula el barcode, actualiza el precio y registra como movimiento `AJUSTE` cualquier
diferencia del conteo físico, con referencia `ALTA_RAPIDA` y nota
*Alta/vinculación rápida*. Si el código no existe, puede crearse un Truper mínimo
con código, barcode, precio y existencia; descripción y clave son opcionales. El
registro queda `es_truper=true` y pendiente de completar. El modo externo exige
barcode, descripción y precio, y permite UNIDAD/GRANEL e inventario opcional.

En el **Punto de venta**, el mismo campo acepta barcode exacto, código Truper,
clave o descripción. Las coincidencias exactas se agregan directamente; para
varios resultados se abre un selector operable con Enter o doble clic. Un producto
GRANEL abre el diálogo de peso/importe existente. Un barcode desconocido reutiliza
el alta rápida y, al guardarlo, agrega el producto al carrito conservado.

En **Más acciones** están *Cambiar/revincular barcode*, *Cambiar código Truper*,
*Ajustar existencia*, tipo de venta y activación. Barcode y código Truper validan
unicidad y piden confirmación; nunca alteran snapshots de ventas. **Eliminar F6**
borra físicamente sólo productos sin detalles de venta ni movimientos. Si existe
historial, desactiva el producto. Los inactivos se consultan con el filtro
*Inactivos* y se reactivan mediante *Activar/desactivar*.

Atajos contextuales: F1 nuevo producto; F2 o Ctrl+F enfoca el buscador de la
pantalla actual; F3 modifica el producto seleccionado; F4 cobra; F5 refresca; F6
elimina/desactiva; F7 aumenta, F8 disminuye y F9/Delete quita la línea seleccionada
del carrito. En GRANEL, F7/F8 reabren el diálogo de cantidad/importe: nunca suman o
restan un kilogramo arbitrariamente. Tras guardar o cerrar un alta se recupera el
foco del buscador correspondiente.

v1.1.1 no requiere cambios de esquema. Todas estas operaciones usan el esquema 6
y transacciones cortas. Las pruebas usan exclusivamente SQLite temporal; una
actualización futura deberá distribuir programa y migraciones, nunca una
`ferreteria.db` que reemplace la base de producción.

### Últimos ajustes de usabilidad v1.1.1

En un Truper existente, la descripción recuperada también puede editarse en el
alta rápida. Descripción, barcode, precio y existencia se guardan en una sola
transacción; una falla revierte el conjunto. Los snapshots de ventas permanecen
inmutables. En un Truper nuevo la descripción sigue siendo opcional.

Al entrar a Punto de Venta, Productos o Existencias, el foco pasa al buscador de
esa pantalla. También se restaura al cerrar altas, selectores, movimientos,
ajustes y diálogos de granel. El foco se solicita únicamente después de cerrar la
operación: no se ejecutan temporizadores periódicos que interrumpan un diálogo o
un editor de celda activo.

El selector del POS abre inicialmente a 1050 × 560 px y puede redimensionarse.
Sus anchos iniciales son Código 100 px, Clave 140 px, Descripción 500 px, Precio
110 px y Existencia 110 px. Todas las columnas son ajustables y cada celda muestra
el contenido completo en tooltip.

Ctrl+clic selecciona productos individuales y Shift+clic selecciona rangos.
**Agregar seleccionados** o Enter agrega todas las filas marcadas; doble clic agrega
únicamente la fila pulsada. Los productos UNIDAD se procesan con cantidad 1 y los
duplicados incrementan su línea actual. Cada GRANEL abre secuencialmente su diálogo;
cancelarlo omite sólo ese producto y continúa con el resto. Todas las validaciones
de existencia del carrito siguen activas.

### Paquete de actualización v1.1.1

Después de aprobar las pruebas puede generarse un paquete sin datos de usuario:

```powershell
.\build_update_v111.ps1
```

El resultado es `dist\PuntoDeVenta_v1.1.1\`, dividido en `app\` para los binarios,
el script `actualizar_v1.1.1.ps1` y las instrucciones
`ACTUALIZAR_A_V1.1.1.txt`. El paquete no contiene `ferreteria.db`, branding,
tickets, respaldos ni logs.

En la computadora del negocio, con el POS cerrado:

```powershell
powershell -ExecutionPolicy Bypass -File .\actualizar_v1.1.1.ps1
```

El actualizador comprueba que exista `C:\PuntoDeVenta\data\ferreteria.db`, crea
un respaldo `pre_update_v1.1.1_*.db` y copia exclusivamente `PuntoDeVenta.exe` y
`_internal`. Preserva íntegramente `data\`, `data\branding\`, `tickets\`,
`backups\` y `logs\`. Para otra instalación use `-Destino "D:\PuntoDeVenta"`.

## Actualizador gráfico para Windows

El procedimiento normal para el usuario final ya no requiere PowerShell. El paquete
`PuntoDeVenta_Actualizacion_1.1.1` incluye `ActualizarPuntoDeVenta.exe`,
`version.json` y el directorio `payload` con únicamente los binarios nuevos.

El actualizador busca directamente, sin recorrer todo el disco, en:

- `C:\PuntoDeVenta`;
- `%USERPROFILE%\Documents\PuntoDeVenta`;
- `%USERPROFILE%\Desktop\PuntoDeVenta`;
- Documents y Desktop de las rutas OneDrive conocidas.

Una instalación requiere `PuntoDeVenta.exe` y `data\ferreteria.db`. Si encuentra
varias, muestra ruta, versión y fecha para que el usuario elija. Si no encuentra
ninguna, **Buscar carpeta** permite seleccionar la carpeta del POS, nunca el archivo
SQLite directamente.

Antes de habilitar **Actualizar**, valida cabecera SQLite, `PRAGMA integrity_check`,
tablas mínimas y compatibilidad del esquema. Al confirmar comprueba que el proceso
esté cerrado, calcula SHA-256 de la base, crea y valida un backup SQLite en
`backups\manual`, copia el payload a staging y conserva temporalmente los binarios
anteriores. Sólo después intercambia `PuntoDeVenta.exe`, `_internal` y
`version.json`.

Una validación posterior confirma versión, binarios, integridad y el mismo SHA-256
de la base. Ante un error restaura los binarios anteriores. Los detalles quedan en
`logs\updater_YYYY-MM-DD.log`. v1.1.1 declara `requires_migration=false`; un paquete
que solicite migración se rechaza hasta implementar explícitamente ese flujo.

Para construir el paquete gráfico:

```powershell
.\build_gui_updater.ps1
```

El usuario sólo debe copiar la carpeta completa, cerrar el POS, hacer doble clic en
`ActualizarPuntoDeVenta.exe`, revisar la instalación detectada, pulsar
**Actualizar** y finalmente **Abrir Punto de Venta**. Las instrucciones para enviar
junto al paquete están en `ACTUALIZAR_PUNTO_DE_VENTA.txt`.

## PuntoDeVenta v1.1.2: granel por peso y volumen

El esquema 7 conserva `tipo_venta` (`UNIDAD`/`GRANEL`) y agrega
`unidad_granel` (`PESO`/`VOLUMEN`). Los graneles anteriores se migran a PESO y
los productos por pieza conservan la unidad vacía. En `detalle_venta`,
`unidad_granel_snapshot` congela la unidad histórica; un detalle GRANEL anterior
al esquema 7 se interpreta como PESO.

La cantidad base continúa en las columnas internas terminadas en `_mg` por
compatibilidad del esquema. Su significado depende de `unidad_granel`: para PESO
es un entero de miligramos (1 kg = 1,000,000 mg) y para VOLUMEN es un entero de
microlitros (1 L = 1,000,000 µL). Esta representación evita `float`; entradas y
cálculos usan `Decimal`. El precio de un granel es por kg o por L.

En **Nuevo** y **Modificar**, al elegir GRANEL aparece **Peso (kg)** o
**Volumen (L)**. El POS reutiliza el mismo diálogo Cantidad/Importe y muestra el
auxiliar en g o ml. Cambiar PESO↔VOLUMEN advierte que precio y cantidades futuras
cambian de interpretación; si el producto controla inventario y su existencia no
es cero, el servicio lo rechaza hasta ajustar la existencia a cero. Los cambios
masivos a GRANEL usan PESO por omisión y permiten escoger Volumen explícitamente.

El control de inventario sigue siendo independiente. Sin control no se valida ni
descuenta existencia y no se generan movimientos de venta/devolución. Con control,
la existencia se guarda en la unidad base entera correspondiente. Carrito,
historial y tickets de 80 mm presentan `kg/g` o `L/ml` según el snapshot.

### Actualización 1.1.1 → 1.1.2

Construya el paquete gráfico sin datos de usuario con:

```powershell
.\build_gui_updater.ps1
```

El resultado es `dist\PuntoDeVenta_Actualizacion_1.1.2\`. No contiene ninguna
base `.db`, branding, tickets, backups ni logs. Su `version.json` exige como mínimo
el esquema 6, apunta al esquema 7 y declara la migración.

El actualizador valida que el POS esté cerrado y la base sea íntegra, crea
`backups\manual\pre_update_v1.1.2_*.db`, instala los binarios mediante staging y
migra la base existente 6→7. Después exige `integrity_check=ok`, esquema 7,
columnas nuevas y los mismos conteos de productos, ventas, detalles, movimientos,
configuración y barcodes. Si falla cualquier paso restaura tanto la base desde el
backup SQLite como los binarios anteriores; nunca sustituye la base por una del
paquete.

## PuntoDeVenta v1.1.3: velocidad de venta y resumen diario

En el carrito, doble clic sobre **Cantidad** o **F10** establece directamente una
cantidad. Los productos UNIDAD aceptan exclusivamente enteros positivos; los
productos GRANEL reutilizan el diálogo Cantidad/Importe precargado en kg o L.
F7 y F8 siguen aumentando/disminuyendo piezas o abriendo el diálogo GRANEL, pero
ahora conservan producto seleccionado y posición vertical. F9/Delete quita la
línea y selecciona la siguiente o, si era la última, la anterior.

El scanner HID ya no exige que el buscador conserve el foco. En Punto de Venta se
reconoce una ráfaga de caracteres alfanuméricos compatible con barcode, con pausas
máximas y Enter final. La captura se suspende cuando hay un diálogo o el foco está
en un `QLineEdit`/editor numérico, incluyendo búsqueda, descuento, efectivo,
cantidad, granel y formularios. F2/Ctrl+F continúa enfocando la búsqueda manual.
Un código se procesa una sola vez: desde el campo se usa su señal Enter y desde la
tabla se usa el buffer global, nunca ambos simultáneamente.

**Cancelar venta · Ctrl+Delete** pide confirmación y vacía únicamente el carrito
actual. No afecta ventas históricas. Después del cobro el PDF sigue generándose
automáticamente; **NUEVA VENTA** es la acción principal y predeterminada para
Enter, mientras **IMPRIMIR TICKET** abre el PDF mediante Windows para imprimirlo.

Historial incluye un selector de fecha y un resumen calculado, no persistido:
ventas completadas, venta neta, desglose por los métodos realmente almacenados,
cancelaciones, importe cancelado y descuentos de ventas completadas. Los productos
vendidos excluyen ventas canceladas y se agrupan usando snapshots de producto y
unidad; piezas, kg y L permanecen separados. La consulta usa los límites UTC del
día local de Windows y el índice existente `ix_ventas_fecha`, sin recorrer el
catálogo de más de 11,000 productos.

v1.1.3 conserva el esquema 7 y no requiere migración. Su paquete gráfico se crea
con `build_gui_updater.ps1` en
`dist\PuntoDeVenta_Actualizacion_1.1.3\`; mantiene backup, staging, validación,
hash idéntico de la base y rollback del actualizador existente.

## PuntoDeVenta v1.1.4: precio variable por venta

El esquema 8 agrega `productos.precio_variable` con valor predeterminado falso.
Todos los productos existentes conservan su precio y comportamiento. La opción
se encuentra en **Nuevo producto** y **Modificar producto** como “Precio variable
en cada venta”; por seguridad, esta primera versión sólo la admite en productos
vendidos por **UNIDAD**. El barcode es opcional y el control de inventario puede
estar desactivado.

Al buscar o escanear un producto variable, el POS solicita un precio unitario
mayor que cero y una cantidad. El precio fijo del catálogo, si existe, se usa sólo
como sugerencia y nunca se modifica al vender. Dos capturas del mismo producto y
el mismo precio se agrupan; precios diferentes permanecen en líneas separadas.
F7, F8 y F10 modifican la línea seleccionada sin volver a pedir precio. Un doble
clic en **Precio unitario** permite cambiar únicamente el precio de una línea
variable.

Ventas, tickets y cancelaciones siguen usando los snapshots de `detalle_venta`.
El resumen diario suma cantidad e importe por producto sin calcular ni mostrar un
precio promedio. Si el producto no controla inventario no se valida stock, no se
descuenta existencia y no se crea movimiento; si sí lo controla, funciona como
cualquier producto por unidad.

La actualización v1.1.3 → v1.1.4 requiere esquema 7 y migra a esquema 8. Cierre
el POS y ejecute `ActualizarPuntoDeVenta.exe` desde
`dist\PuntoDeVenta_Actualizacion_1.1.4\`. El actualizador valida la instalación,
crea un respaldo, instala los binarios, migra la base y restaura base y binarios
si cualquier etapa falla. El paquete no incluye archivos `.db` ni datos reales.
