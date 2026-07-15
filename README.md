# QGIS-RRIM

QGIS-RRIM is a QGIS plugin that implements the Red Relief Image Map (RRIM) technique proposed by Chiba, Kaneta & Suzuki (2008). It provides a streamlined workflow for high-resolution geomorphological and morphostructural analysis using Digital Elevation Models (DEMs).

The plugin automates the generation, normalization, and visualization of terrain derivatives required to produce RRIM outputs directly within QGIS.

---


## ⚖️ License (Dual Licensing)

This project is distributed under a **Dual Licensing** model:

1. **Open Source Use (GNU GPLv3):** You can use, study, modify, and redistribute this software for free, provided that any modified version or derivative work is also 100% open source under the GNU GPLv3 license.
2. **Commercial / Private Use (Commercial License):** If you wish to integrate this code into proprietary, closed-source, or commercial software (without the obligation to open your own source code under the GPLv3), you must acquire an exclusive commercial license. Please contact the author to negotiate terms.

For more details, see the [LICENSE](LICENSE) file.

---

## 🌍 Overview

RRIM is a visualization method that enhances subtle topographic features by combining:

- Slope (in red tones) (blending=multiply)
- Differential openness (in grayscale)

This combination allows for improved interpretation of:
- Lineaments and structural controls
- Micro-topography
- Erosional and depositional features
- Subtle geomorphological patterns

---

## ⚙️ Dependency

This plugin requires the Relief Visualization Toolbox (RVT) plugin.

Differential openness is computed using RVT algorithms, which are not natively implemented in QGIS-RRIM.

---

## 🧰 Tools

### 1. RRIM Generator (v2.1)

Generates the required layers from a DEM:

- Slope layer
- Differential openness layer (via RVT)

Features:
- Automatic preprocessing workflow
- Optional normalization of outputs
- Optional direct RRIM RGB generation

---

### 2. RRIM RGB Composer

Creates a final georeferenced RRIM RGB GeoTIFF from precomputed inputs.

Features:
- Combines slope and openness layers
- User-defined normalization ranges
- Full control over visualization parameters
- Export-ready output for GIS workflows

---

## 🧪 Workflow Summary

1. Input DEM
2. Generate slope + differential openness
3. Normalize layers (optional)
4. Compose RRIM RGB
5. Export GeoTIFF

---

## 📚 Citation

Original method:

Chiba, T., Kaneta, S., & Suzuki, Y. (2009). Red relief image map: New visualization method for three dimensional data.
ISPRS Journal of Photogrammetry and Remote Sensing, 62(2), 107–116.

---

Software implementation:

Zavaleta, J. (2026). QGIS-RRIM: Generate RRIM terrain layers and compose RRIM RGB outputs in QGIS.
QGIS Plugin Repository. MIT License.

---

## 🚀 Notes

- Designed for geomorphology, structural geology, and remote sensing applications
- Optimized for integration into QGIS-based workflows
- Suitable for both regional and high-resolution terrain analysis

## License

This project is licensed under the GNU GPLv3 and the Dual Licensing agreement described above. See the [LICENSE](LICENSE) file for more details.
