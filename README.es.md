<p align="center"><a href="README.md">English</a> · <strong>Español</strong></p>

# QGIS-RRIM

**Mapas de relieve rojo — RRIM — desde Processing de QGIS.**

Calcula pendiente y apertura diferencial a partir de un DEM proyectado y
compón un GeoTIFF RGB georreferenciado con límites de visualización explícitos.

> RRIM resalta morfología; no clasifica automáticamente geoformas ni
> estructuras geológicas. Resolución, unidades verticales, radio y bordes
> condicionan la interpretación.

## Instalación

Requiere QGIS 3.28 o superior y no depende de Relief Visualization Toolbox.

1. Descarga el ZIP de la [última release](https://github.com/jordan-zav/QGIS-RRIM/releases/latest).
2. Abre Complementos → Administrar e instalar complementos → Instalar a partir de ZIP.
3. Selecciona el ZIP y activa QGIS-RRIM.

En desarrollo, copia o enlaza el repositorio como QGIS_RRIM dentro de
python/plugins del perfil activo y reinicia QGIS.

## Herramientas y uso

**RRIM Generator** genera pendiente en grados y apertura diferencial, definida
como (apertura positiva − apertura negativa) / 2. Puede guardar copias de
presentación: pendiente de 0–90° con rampa roja y mezcla Multiply, y apertura
diferencial limitada a −50–50.

La fuente 2.2.0 utiliza **10 celdas de radio y 16 direcciones**, valores fijos.
Su distancia física depende del tamaño de píxel.

**RRIM RGB Composer** combina pendiente y apertura ya calculadas. Permite
definir pendiente máxima, apertura mínima/máxima y ruta del GeoTIFF. Requiere
igual CRS, extensión, dimensiones y malla en las dos entradas; no remuestrea.

1. Carga un DEM monobanda proyectado y revisa unidades horizontales y verticales.
2. Abre Caja de herramientas de Processing → QGIS-RRIM → RRIM Generator.
3. Guarda las salidas y solicita copias normalizadas si las necesitas.
4. Ejecuta RRIM RGB Composer con límites revisados.
5. Compara el RGB a varias escalas con DEM, curvas, sombreado e imágenes.

Los algoritmos también se pueden usar por lotes y en el Modelador de QGIS.

## Calidad de datos

Una máscara interna conserva los píxeles inválidos; el negro válido no se
convierte en NoData. Se conservan los píxeles rectangulares. Generador y
compositor requieren mallas orientadas al norte: transforma antes entradas
rotadas o cizalladas. El núcleo de apertura utiliza la transformación afín
completa para medir distancias.

Los límites NoData reducen direcciones disponibles; las celdas sin muestras
válidas quedan como NoData. Los bordes externos usan relleno reflejado.
Remuestrear no crea detalle nuevo y el contraste RRIM no es una clase física.

## Método y pruebas

Basado en Chiba, Kaneta y Suzuki (2008), Red Relief Image Map: New Visualization
Method for Three Dimensional Data, ISPRS XXXVII-B2, 1071–1076.
[Artículo original](https://www.isprs.org/proceedings/XXXVII/congress/2_pdf/11_ThS-6/08.pdf).

~~~powershell
python -m pytest -q
~~~

Las pruebas numéricas son independientes de QGIS y contrastan terrenos planos,
planos inclinados y una implementación de horizonte de referencia. Una release
requiere además comprobar carga y procesamiento real en QGIS.

## Estado y organización

La fuente declara 2.2.0 y la última release citada es 2.1.0. Quedan pendientes
parámetros de radio/direcciones configurables y pruebas automáticas de ciclo
de vida QGIS. rrim_openness.py contiene el motor por bloques;
rrim_algorithm.py y rrim_rgb_composer.py implementan los dos algoritmos;
rrim_provider.py registra el proveedor y metadata.txt describe el complemento.

## Licencia y contacto

[GNU GPL v3](LICENSE). Jordan Zavaleta — GisGeo Dev.
[Correo](mailto:jordanzav@gisgeo.dev) · [Sitio web](https://gisgeo.dev).
