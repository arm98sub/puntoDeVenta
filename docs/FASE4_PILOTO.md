# Fase 4 — PuntoDeVenta General 0.9.0 Piloto

## Arquitectura y seguridad

- Build: PyInstaller ONEDIR mediante `build_windows.ps1 -Edition GENERAL`.
- Ruta compilada: la raíz es la carpeta del ejecutable y la base se crea en
  `data/punto_venta.db`.
- Primer arranque: SQLite crea el archivo, aplica migraciones 1–10 y después
  crea categorías y presentaciones `Pieza`, `Caja`, `Paquete` y `Display`.
- GENERAL sólo acepta el override `PUNTO_VENTA_GENERAL_DB`; ignora
  `FERRETERIA_DB`.
- Los builds GENERAL rechazan `-IncludeRealData`. Build y updater rechazan
  `.db`, `.sqlite` y `.sqlite3` sin distinguir mayúsculas.
- El updater valida edición antes del backup y staging, preserva las carpetas
  persistentes y realiza rollback de aplicación y base ante un fallo.

## Rendimiento reproducible

Comando:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_general.py
```

Medición del 29/08/2026 en Windows 11 sobre una DB temporal de 5,472,256 bytes:

| Datos/operación | Resultado |
|---|---:|
| Productos | 5,000 |
| Movimientos | 20,000 |
| Ventas / detalles | 5,000 / 5,000 |
| Compras / detalles | 2,000 / 2,000 |
| Inicializar backend vacío | 180.919 ms |
| Construir ventana (pantallas secundarias diferidas) | 454.460 ms |
| Barcode exacto | 5.938 ms |
| Código exacto | 4.346 ms |
| Descripción (50 resultados) | 129.925 ms |
| Agregar al carrito | 7.726 ms |
| Registrar venta | 35.003 ms |
| Primera página Productos | 14.725 ms |
| Primera página Inventario | 13.145 ms |
| Primera página Compras | 2.239 ms |
| Primera página Historial | 1.980 ms |
| Consulta de stock | 0.454 ms |
| Pico Python medido al construir ventana | 2,068,304 bytes |

La cifra de memoria es `tracemalloc` de asignaciones Python durante la
construcción, no el working set completo de Qt/PyInstaller.

## Prueba manual obligatoria en la PC piloto

1. Copiar únicamente `PuntoDeVenta-General-0.9.0` a una carpeta local fuera de
   OneDrive.
2. Confirmar que no contiene ninguna DB y abrir `PuntoDeVenta.exe`.
3. Confirmar que aparece `data/punto_venta.db` y que la aplicación reabre.
4. Configurar el nombre del negocio.
5. Crear categoría y proveedor.
6. Crear un producto UNIDAD y otro GRANEL.
7. Registrar una compra de ambos y verificar stock.
8. Registrar una venta de ambos y verificar stock.
9. Reiniciar y verificar persistencia de productos, compras, ventas y stock.
10. Crear un respaldo manual; alterar nombre, precio y stock; restaurar el
    respaldo y comprobar que regresan todos los valores.
11. Con el POS cerrado, ejecutar un paquete GENERAL de prueba y comprobar que
    la DB conserva tamaño, datos e integridad.
12. Intentar seleccionar un paquete FERRETERIA y confirmar su rechazo antes de
    que aparezca un nuevo respaldo.

Las operaciones interactivas 4–12 requieren validación humana en la PC Windows
10 real con su scanner y HDD; las pruebas automatizadas cubren el mismo dominio
con bases temporales, pero no sustituyen esa aceptación física.
