# Revisión de código de QGIS-RRIM

29 de octubre de 2026. Base revisada: 74c53a1, fuente 2.2.0.
Las correcciones se incluyen en la entrega 1.1.0, numeración solicitada por el
mantenedor. Se conservan los tags históricos. La prueba con LiDAR público y
las capturas se describen en [la validación de la entrega](LIDAR_VALIDATION_1_1_0.md).

## Errores reproducidos y corregidos

| Prioridad | Hallazgo | Corrección |
| --- | --- | --- |
| Alta | Apertura y operaciones ráster podían crear la salida sobre el DEM de entrada | Validación previa de rutas, identidad física del archivo y dependencias de VRT |
| Alta | Pendiente, apertura diferencial y copias normalizadas podían compartir destino y sobrescribirse | Las salidas activas deben ser distintas entre sí y de las entradas antes de iniciar el cálculo |
| Alta | Cancelar apertura u operaciones ráster podía modificar o eliminar el resultado anterior; el compositor RGB ignoraba Cancelar | Escrituras por archivo en un destino provisional, cancelación entre bloques y publicación al completar la escritura |
| Alta | Se ignoraban códigos de error devueltos por GDAL al escribir; un resultado incompleto podía anunciarse como correcto | Comprobación de escritura, máscara, georreferenciación y vaciado de caché antes de publicar el archivo |
| Media | Descargar el proveedor conservaba una referencia a un objeto C++ eliminado e impedía reutilizar el controlador | Reinicio de la referencia, descarga repetible y tratamiento de registros duplicados sin retirar el proveedor ajeno |
| Media | Las salidas se asociaban siempre al proyecto global | Se respeta el proyecto del contexto Processing |
| Media | Los nombres y estilos podían dejar de aplicarse al desaparecer el objeto Python del algoritmo | Referencias Python conservadas durante la vida del postprocesador C++, incluso al transferir resultados entre contextos |

Los ocho casos iniciales de regresión fallaron sobre el código anterior.
Las comprobaciones posteriores reprodujeron también la pérdida del
postprocesador y tres rutas que ignoraban un error de escritura GDAL.

Se sustituyó además el import directo de PyQt5 por qgis.PyQt, se validan
parámetros de muestreo y transformaciones degeneradas, y el generador libera
sus propios archivos intermedios también cuando falla una etapa posterior.

## Archivos principales

- [rrim_raster.py](../rrim_raster.py): rutas, publicación por archivo y operaciones ráster.
- [rrim_openness.py](../rrim_openness.py): validación, cancelación y escritura de apertura.
- [rrim_rgb_composer.py](../rrim_rgb_composer.py): cancelación, máscara y errores de escritura RGB.
- [rrim_algorithm.py](../rrim_algorithm.py): prevalidación del flujo, pendiente, contexto y estilos.
- [qgis_rrim.py](../qgis_rrim.py): registro y descarga del proveedor.

La publicación es por archivo. Si una etapa posterior del generador se
cancela, los productos ya completados no se revierten. Se protege el destino
que se está escribiendo, sin prometer una transacción de todas las salidas.

Los destinos con archivos auxiliares .msk, .ovr o .aux.xml requieren un nombre
nuevo para evitar que una máscara, pirámide o metadato antiguo altere el nuevo
ráster. Esos archivos existentes se conservan.

## Validación final

Entorno: QGIS 3.44.12-Solothurn, Qt 5.15.13, GDAL 3.13.1 y Python 3.12.13.
Las pruebas finales de QGIS utilizan perfiles y directorios de autenticación
aislados. Se emplearon datos sintéticos.

| Comprobación | Resultado |
| --- | --- |
| Pruebas Python de apertura y validación de rutas | 19 aprobadas |
| Regresiones con QGIS/GDAL reales | 20 aprobadas |
| Integración original de generador, normalización y RGB | Aprobada, código de salida 0 |
| Ruff, reglas E4/E7/E9/F | Sin errores; los imports posteriores a la inicialización de QGIS se admiten en el ejecutable de pruebas |
| Bandit sobre los siete módulos del plugin | Cero incidencias |

Las regresiones comprueban, entre otros casos: alias mediante enlaces físicos,
dependencias VRT, destinos normalizados conflictivos, cancelación inicial y
entre bloques, errores de escritura simulados, salidas en memoria /vsimem,
registros duplicados, recargas repetidas, transferencia de contexto, aplicación
de estilos, máscaras NoData y conservación del negro válido en RGB.

Se mantienen las comprobaciones numéricas existentes sobre plano horizontal,
plano inclinado, referencia de horizonte y distancias afines. La integración
verifica también la continuidad entre bloques, los píxeles rectangulares, la
independencia respecto del CRS del proyecto y la máscara interna del RGB.

## Repetición

Pruebas independientes de QGIS:

~~~text
python -m pytest -q
~~~

Con el Python de QGIS, usando una ruta de salida nueva:

~~~text
python tests/qgis_integration.py
python tests/qgis_regressions.py --output RUTA_DE_AUDITORIA
~~~

La ejecución de regresiones guarda results.json y environment.json. La evidencia
local de la validación final está en:

~~~text
D:/DevResources/Sessions/QGIS-RRIM/review_final_20261029_193752
~~~

Se repitieron las seis comprobaciones tras corregir el diagrama del flujo,
los requisitos y el estado de publicación de los README, y la ayuda integrada
de ambos algoritmos. Todas terminaron con código 0. La compatibilidad declarada
en metadatos es QGIS 3.28–3.99; el entorno ejecutado fue 3.44.12. No se realizó
una revisión manual interactiva de los diálogos. En la validación LiDAR se
instanciaron y capturaron ambos diálogos reales, con sus parámetros y ayuda.
