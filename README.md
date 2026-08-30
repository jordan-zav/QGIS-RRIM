<div align="center">
  <img src="icon.png" alt="QGIS-RRIM" width="112">

# QGIS-RRIM

**Red Relief Image Map generation directly in QGIS Processing**

Derive slope and differential openness from a projected DEM, apply consistent
display ranges and export a georeferenced RRIM RGB GeoTIFF.

[![Source 2.2.0](https://img.shields.io/badge/source-2.2.0-2563eb)](metadata.txt)
[![Release 2.1.0](https://img.shields.io/github/v/release/jordan-zav/QGIS-RRIM?color=7c3aed)](https://github.com/jordan-zav/QGIS-RRIM/releases/latest)
[![QGIS 3.28+](https://img.shields.io/badge/QGIS-3.28%2B-589632?logo=qgis&logoColor=white)](https://qgis.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-0f766e)](LICENSE)

</div>

> [!IMPORTANT]
> QGIS-RRIM is a terrain-visualization tool. RRIM enhances morphology but does
> not classify landforms or geological structures. Pixel size, vertical units,
> openness radius and edge effects must be considered during interpretation.

## Workflow at a glance

```text
Single-band DEM in a projected CRS
                 │
                 ▼
 Slope ──► positive openness + negative openness
                 │
                 ▼
 Differential openness = (positive - negative) / 2
                 │
                 ▼
 Optional display-ready normalized rasters
                 │
                 ▼
 Red slope × grayscale openness ──► RGB GeoTIFF
```

## Processing tools

### RRIM Generator

Produces the geomorphometric inputs used by the composition:

| Output | Meaning |
| --- | --- |
| Slope | QGIS native slope in degrees |
| Differential openness | Half the difference between positive and negative openness |
| Normalized slope | Optional 0–90° display copy with red ramp and Multiply blending |
| Normalized differential openness | Optional display copy clamped to -50–50 |

The internal horizon implementation currently uses a radius of **10 cells** and
**16 directions**. These values are fixed in source version 2.2.0 and therefore
represent different physical distances when DEM pixel size changes.

### RRIM RGB Composer

Combines existing slope and differential-openness rasters into one packed RGB
GeoTIFF. The operator controls:

- maximum displayed slope;
- minimum differential openness;
- maximum differential openness; and
- output GeoTIFF path.

Both inputs must have the same raster dimensions, extent and CRS.

## Requirements

- QGIS 3.28 or newer;
- a valid single-band DEM;
- projected CRS;
- horizontal and elevation units that are mutually consistent; and
- enough memory and temporary disk space for the DEM and openness halo blocks.

The plugin computes openness internally and does not require the Relief
Visualization Toolbox plugin.

## Installation

### From a release ZIP

1. download the ZIP from the [latest release](https://github.com/jordan-zav/QGIS-RRIM/releases/latest);
2. open **Plugins → Manage and Install Plugins** in QGIS;
3. choose **Install from ZIP**; and
4. select the downloaded archive and enable QGIS-RRIM.

### Development checkout

Copy or link the repository as `QGIS_RRIM` inside the active QGIS profile's
`python/plugins` directory, then restart QGIS and enable the plugin.

## Use in QGIS

1. load a projected DEM and confirm its pixel/elevation units;
2. open **Processing Toolbox → QGIS-RRIM → RRIM Generator**;
3. save slope and differential openness outputs;
4. optionally request normalized display copies;
5. run **RRIM RGB Composer** with reviewed display limits; and
6. inspect the RGB output at several scales and alongside the original DEM.

Because both tools are QGIS Processing algorithms, they can also be used in
batch processing and Model Designer workflows.

## Interpretation and quality control

- The 10-cell radius must be converted to a physical distance using pixel size.
- NoData boundaries and raster edges reduce the available horizon neighborhood.
- Resampling a DEM does not create new topographic detail.
- Slope and openness depend on DEM noise, smoothing and vertical/horizontal units.
- RRIM contrast is a visualization choice, not a quantitative terrain class.
- Compare features against contours, hillshade, imagery and field/geological data.

## Method reference

The implementation follows the RRIM concept described by:

> Chiba, T., Kaneta, S. and Suzuki, Y. (2008). *Red Relief Image Map: New
> Visualization Method for Three Dimensional Data*. The International Archives
> of the Photogrammetry, Remote Sensing and Spatial Information Sciences,
> XXXVII-B2, 1071–1076.

[Read the original ISPRS paper](https://www.isprs.org/proceedings/XXXVII/congress/2_pdf/11_ThS-6/08.pdf).

## Development and verification

The numerical openness tests are independent of QGIS and can be executed with:

```powershell
python -m pytest -q
```

They check flat terrain, uniform planes and agreement with a reference horizon
calculation. A release should additionally be loaded in a supported QGIS version
and exercised with a projected test DEM.

## Repository map

| Path | Contents |
| --- | --- |
| `qgis_rrim.py` | Plugin lifecycle and provider registration |
| `rrim_provider.py` | QGIS Processing provider |
| `rrim_algorithm.py` | RRIM Generator workflow |
| `rrim_openness.py` | Block-based positive/negative openness engine |
| `rrim_rgb_composer.py` | RGB composition and GeoTIFF export |
| `tests` | Numerical openness regression tests |
| `metadata.txt` | QGIS Plugin Repository metadata |

## Project status

The source tree is version 2.2.0 while the latest GitHub release is 2.1.0. The
internal openness implementation removes the former runtime dependency on RVT.
Configurable radius/direction parameters and automated QGIS lifecycle tests are
the main remaining release-hardening tasks.

## License and contact

QGIS-RRIM is distributed under the [GNU General Public License v3.0](LICENSE).

Jordan Zavaleta — GisGeo Dev<br>
[jordanzav@gisgeo.dev](mailto:jordanzav@gisgeo.dev) · [gisgeo.dev](https://gisgeo.dev)
