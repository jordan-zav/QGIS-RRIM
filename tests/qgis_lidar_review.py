"""Process a public projected LiDAR DTM and export QGIS maps for visual review.

Run with the Python bundled with QGIS. Input data and results stay outside Git.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--dem", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--package-root", type=Path)
parser.add_argument("--render-only", action="store_true")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=args.render_only)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QGIS_AUTH_DB_DIR_PATH"] = str(args.output / "auth")
(args.output / "auth").mkdir(exist_ok=args.render_only)

import numpy as np
from osgeo import gdal
from qgis.core import (
    Qgis, QgsApplication, QgsProject, QgsRasterLayer, QgsProcessingContext,
    QgsProcessingFeedback, QgsMapSettings, QgsMapRendererParallelJob,
    QgsSingleBandGrayRenderer, QgsContrastEnhancement, QgsRectangle,
)
from qgis.PyQt.QtCore import QSize, QSettings
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QFont, QFontDatabase

app = QgsApplication([], True, str(args.output / "profile"))
app.initQgis()
font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
if font_path.exists():
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    assert font_id >= 0, "Could not load the font for the visual review"
app.setFont(QFont("Segoe UI", 10))
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(args.output / "settings"))
sys.path.insert(0, str(Path(QgsApplication.prefixPath()) / "python/plugins"))
from processing.core.Processing import Processing
from qgis import processing
Processing.initialize()

package = (args.package_root or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(package.parent))
provider = importlib.import_module(package.name + ".rrim_provider").RRIMProvider()
assert QgsApplication.processingRegistry().addProvider(provider)
algorithm_module = importlib.import_module(package.name + ".rrim_algorithm")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


before = digest(args.dem)
dem = QgsRasterLayer(str(args.dem), "LiDAR DTM - 1 m")
assert dem.isValid() and dem.bandCount() == 1 and not dem.crs().isGeographic()
source = gdal.Open(str(args.dem))
grid = source.GetGeoTransform()
assert grid[1:] == (1.0, 0.0, grid[3], 0.0, -1.0), grid
shape = (source.RasterYSize, source.RasterXSize)
source_values = source.ReadAsArray()
source_mask = source.GetRasterBand(1).GetMaskBand().ReadAsArray() != 0
assert np.count_nonzero(source_mask) > source_values.size * .95
project = QgsProject.instance()
project.setCrs(dem.crs())
context = QgsProcessingContext()
context.setProject(project)
feedback = QgsProcessingFeedback()
paths = {name: str(args.output / (name + ".tif"))
         for name in ("slope", "diff", "slope_norm", "diff_norm", "rgb", "hillshade")}
started = time.perf_counter()
if not args.render_only:
    processing.run("qgis_rrim:rrim_generator", {
    "INPUT_RASTER": dem, "OUT_SLOPE": paths["slope"], "OUT_DIFF": paths["diff"],
    "AUTO_NORMALIZE": True, "OUT_SLOPE_NORM": paths["slope_norm"],
    "OUT_DIFF_NORM": paths["diff_norm"],
    }, context=context, feedback=feedback)
generator_seconds = time.perf_counter() - started
print("LiDAR generator completed", round(generator_seconds, 2), "seconds", flush=True)
started = time.perf_counter()
if not args.render_only:
    processing.run("qgis_rrim:rrim_rgb_composer", {
    "INPUT_SLOPE": paths["slope"], "INPUT_DO": paths["diff"],
    "SLOPE_MAX": 90, "DO_MIN": -50, "DO_MAX": 50, "OUTPUT": paths["rgb"],
    }, context=context, feedback=feedback)
rgb_seconds = time.perf_counter() - started
if not args.render_only:
    gdal.DEMProcessing(paths["hillshade"], str(args.dem), "hillshade", computeEdges=True)
else:
    previous_manifest = json.loads((args.output / "results.json").read_text(encoding="utf-8"))
    assert previous_manifest["input_sha256"] == before
    generator_seconds = previous_manifest["generator_seconds"]
    rgb_seconds = previous_manifest["rgb_seconds"]

statistics = {}
for name in ("slope", "diff", "slope_norm", "diff_norm", "rgb"):
    dataset = gdal.Open(paths[name])
    assert dataset.GetGeoTransform() == grid
    assert (dataset.RasterYSize, dataset.RasterXSize) == shape
    assert dataset.GetSpatialRef().IsSame(source.GetSpatialRef())
    values = dataset.ReadAsArray()
    mask = dataset.GetRasterBand(1).GetMaskBand().ReadAsArray() != 0
    valid_values = values[:, mask] if values.ndim == 3 else values[mask]
    assert np.isfinite(valid_values).all()
    statistics[name] = {"valid_pixels": int(mask.sum()),
                        "percentiles": np.percentile(valid_values, [0, 2, 50, 98, 100]).tolist(),
                        "sha256": digest(paths[name])}
    dataset = None
assert digest(args.dem) == before, "Input DTM changed"


def gray(layer, minimum, maximum):
    renderer = QgsSingleBandGrayRenderer(layer.dataProvider(), 1)
    enhancement = QgsContrastEnhancement(layer.dataProvider().dataType(1))
    enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
    enhancement.setMinimumValue(float(minimum))
    enhancement.setMaximumValue(float(maximum))
    renderer.setContrastEnhancement(enhancement)
    layer.setRenderer(renderer)


layers = {name: QgsRasterLayer(path, name.replace("_", " ").title()) for name, path in paths.items()}
for name in ("slope_norm", "diff_norm"):
    algorithm_module._LayerNamePostProcessor(name, name).postProcessLayer(layers[name], context, feedback)
gray(layers["slope"], 0, 90)
gray(layers["diff"], -50, 50)
gray(layers["hillshade"], 0, 255)
gray(dem, *np.percentile(source_values[source_mask], [2, 98]))
for layer in [dem] + list(layers.values()):
    project.addMapLayer(layer)
    project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(layer == layers["rgb"])
project.setFileName(str(args.output / "RRIM_Cheddar_LiDAR.qgz"))
assert project.write()


def render(layer, extent, size):
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(dem.crs())
    settings.setExtent(extent)
    settings.setOutputSize(size)
    settings.setBackgroundColor(QColor("#e6e8eb"))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    assert not job.errors(), [e.message for e in job.errors()]
    return job.renderedImage()


extent = dem.extent()
render(layers["rgb"], extent, QSize(2048, 2048)).save(str(args.output / "rrim_full.png"))
overview = QImage(1920, 2100, QImage.Format_ARGB32)
overview.fill(QColor("#101827"))
painter = QPainter(overview)
painter.setPen(QColor("#f0f4fa"))
painter.setFont(QFont("Segoe UI", 20))
painter.drawText(36, 45, "QGIS-RRIM | Cheddar Gorge | public LiDAR DTM, 1 m")
painter.setFont(QFont("Segoe UI", 12))
painter.drawText(36, 78, "Native grid | radius 10 cells | 16 directions | RGB limits: slope 90, openness -50 to 50")
for index, (name, title) in enumerate([
    ("hillshade", "Reference hillshade"), ("slope", "Slope (0-90 degrees)"),
    ("diff", "Differential openness (-50 to 50)"), ("rgb", "RRIM RGB - default ranges"),
]):
    x, y = 30 + (index % 2) * 950, 115 + (index // 2) * 965
    painter.setFont(QFont("Segoe UI", 16))
    painter.drawText(x, y, title)
    painter.drawImage(x, y + 20, render(layers[name], extent, QSize(920, 920)))
painter.setFont(QFont("Segoe UI", 11))
painter.drawText(30, 2080, "Contains Environment Agency data. Copyright and/or database right 2022. Open Government Licence.")
painter.end()
assert overview.save(str(args.output / "comparison.png"))

closeup_extent = QgsRectangle(346300, 153700, 347068, 154468)
closeup = QImage(1600, 890, QImage.Format_ARGB32)
closeup.fill(QColor("#101827"))
painter = QPainter(closeup)
painter.setPen(QColor("#f0f4fa"))
painter.setFont(QFont("Segoe UI", 17))
for index, (name, title) in enumerate([("hillshade", "Hillshade"), ("rgb", "RRIM RGB - 768 m detail")]):
    painter.drawText(index * 800 + 20, 40, title)
    painter.drawImage(index * 800 + 20, 60, render(layers[name], closeup_extent, QSize(768, 768)))
painter.end()
assert closeup.save(str(args.output / "detail.png"))

from processing.gui.AlgorithmDialog import AlgorithmDialog
for name in ("rrim_generator", "rrim_rgb_composer"):
    algorithm = QgsApplication.processingRegistry().algorithmById("qgis_rrim:" + name).create()
    dialog = AlgorithmDialog(algorithm)
    if name == "rrim_generator":
        dialog.setParameters({"INPUT_RASTER": dem, "AUTO_NORMALIZE": True,
                              "OUT_SLOPE": paths["slope"], "OUT_DIFF": paths["diff"],
                              "OUT_SLOPE_NORM": paths["slope_norm"], "OUT_DIFF_NORM": paths["diff_norm"]})
    else:
        dialog.setParameters({"INPUT_SLOPE": layers["slope"], "INPUT_DO": layers["diff"],
                              "SLOPE_MAX": 90, "DO_MIN": -50, "DO_MAX": 50,
                              "OUTPUT": paths["rgb"]})
    dialog.resize(1150, 850)
    dialog.show()
    app.processEvents()
    assert dialog.grab().save(str(args.output / (name + "_dialog.png")))
    dialog.close()
    dialog = None

manifest = {
    "qgis": Qgis.QGIS_VERSION, "gdal": gdal.VersionInfo("--version"),
    "input": str(args.dem), "input_sha256": before, "shape": shape,
    "geotransform": grid, "crs": dem.crs().authid(),
    "generator_seconds": generator_seconds, "rgb_seconds": rgb_seconds,
    "input_unchanged": digest(args.dem) == before, "outputs": statistics,
    "source": "https://www.data.gov.uk/dataset/01b3ee39-da3f-47b6-83da-dc98e73a461f/lidar-composite-digital-terrain-model-dtm-1m",
    "attribution": "Contains Environment Agency data, copyright and/or database right 2022. Open Government Licence.",
    "visual_review": "Pending inspection of comparison.png, detail.png and dialog captures.",
}
(args.output / "results.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest, indent=2), flush=True)
