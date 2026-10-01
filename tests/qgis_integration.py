"""Run with python-qgis-ltr.bat tests/qgis_integration.py (no pytest required)."""
import importlib
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from osgeo import gdal, osr
from qgis.core import (QgsApplication, QgsProject, QgsCoordinateReferenceSystem,
                       QgsRasterLayer, QgsProcessingContext, QgsProcessingFeedback)

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
app = QgsApplication([], False)
app.initQgis()
sys.path.insert(0, str(Path(QgsApplication.prefixPath()) / "python/plugins"))
from processing.core.Processing import Processing
Processing.initialize()
generator = importlib.import_module(root.name + ".rrim_algorithm").RRIMGenerator
composer = importlib.import_module(root.name + ".rrim_rgb_composer").export_rrim_geotiff

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
    path = lambda name: str(Path(temp) / (name + ".tif"))
    transform = (500000, 10, 0, 8700000, 0, -20)
    crs = osr.SpatialReference()
    crs.ImportFromEPSG(32718)
    dem = gdal.GetDriverByName("GTiff").Create(path("dem"), 32, 24, 1, gdal.GDT_Float32)
    dem.SetGeoTransform(transform)
    dem.SetProjection(crs.ExportToWkt())
    values = np.zeros((24, 32), dtype=np.float32)
    values[6:18, 16:25] = 100
    dem.GetRasterBand(1).WriteArray(values)
    dem = None
    openness = importlib.import_module(root.name + ".rrim_openness").compute_openness_raster
    openness(path("dem"), path("op_small"), block_size=7)
    openness(path("dem"), path("op_large"), block_size=512)
    small = gdal.Open(path("op_small"))
    large = gdal.Open(path("op_large"))
    np.testing.assert_allclose(small.ReadAsArray(), large.ReadAsArray(), atol=1e-5)
    small = large = None
    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    algorithm = generator()
    algorithm.initAlgorithm()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    feedback = QgsProcessingFeedback()
    outputs = algorithm.processAlgorithm({
        "INPUT_RASTER": path("dem"), "OUT_SLOPE": path("slope"),
        "OUT_DIFF": path("diff"), "AUTO_NORMALIZE": True,
        "OUT_SLOPE_NORM": path("slope_norm"), "OUT_DIFF_NORM": path("diff_norm"),
    }, context, feedback)
    for name, filename in outputs.items():
        ds = gdal.Open(filename)
        assert (ds.RasterXSize, ds.RasterYSize) == (32, 24), name
        assert ds.GetGeoTransform() == transform, name
        ds = None
    slope = QgsRasterLayer(path("slope"), "Slope")
    diff = QgsRasterLayer(path("diff"), "Diff")
    composer(slope, diff, path("rgb"))
    rgb = gdal.Open(path("rgb"))
    assert rgb.GetGeoTransform() == transform
    assert (rgb.RasterXSize, rgb.RasterYSize, rgb.RasterCount) == (32, 24, 3)
    pixels = rgb.ReadAsArray()
    assert np.std(pixels) > 5, "RGB is blank"
    rgb = None
    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:32718"))
    composer(slope, diff, path("rgb_same_crs"))
    rgb = gdal.Open(path("rgb_same_crs"))
    np.testing.assert_array_equal(pixels, rgb.ReadAsArray())
    rgb = None
    slope = diff = context = algorithm = None
print("PASS: rectangular grid, normalization, RGB dimensions and project CRS independence")

# Regression: alternating rows must survive every supported pixel aspect.
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
    def make_layer(name, values, px, py):
        filename = str(Path(temp) / (name + ".tif"))
        ds = gdal.GetDriverByName("GTiff").Create(filename, 32, 24, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((500000, px, 0, 8700000, 0, -py))
        ds.SetProjection(crs.ExportToWkt())
        ds.GetRasterBand(1).SetNoDataValue(-9999)
        ds.GetRasterBand(1).WriteArray(values)
        ds = None
        return QgsRasterLayer(filename, name)

    stripes = np.tile(np.where(np.arange(24) % 2, 40., -40.)[:, None], (1, 32))
    expected = None
    for px, py in [(10, 10), (20, 10), (10, 20)]:
        slope = make_layer(f"s{px}_{py}", np.zeros((24, 32)), px, py)
        diff = make_layer(f"d{px}_{py}", stripes, px, py)
        destination = str(Path(temp) / f"rgb{px}_{py}.tif")
        composer(slope, diff, destination)
        ds = gdal.Open(destination)
        pixels = ds.ReadAsArray()
        assert np.count_nonzero(np.diff(pixels[0, :, 16].astype(int))) == 23
        if expected is None:
            expected = pixels
        np.testing.assert_array_equal(pixels, expected)
        ds = None
        slope = diff = None

    slope_values = np.zeros((24, 32))
    do_values = np.zeros((24, 32))
    slope_values[4:8, 4:8] = -9999
    do_values[12:16, 12:16] = np.nan
    do_values[0, 0] = -50  # Valid black must not become NoData.
    slope = make_layer("hole_s", slope_values, 10, 10)
    diff = make_layer("hole_d", do_values, 10, 10)
    destination = str(Path(temp) / "masked_rgb.tif")
    composer(slope, diff, destination)
    ds = gdal.Open(destination)
    expected_mask = np.ones((24, 32), dtype=np.uint8) * 255
    expected_mask[4:8, 4:8] = 0
    expected_mask[12:16, 12:16] = 0
    for channel in range(1, 4):
        np.testing.assert_array_equal(ds.GetRasterBand(channel).GetMaskBand().ReadAsArray(), expected_mask)
    assert not Path(destination + ".msk").exists(), "Mask must be internal"
    assert np.all(ds.ReadAsArray()[:, 0, 0] == 0)
    ds = None
    slope = diff = None
print("PASS: RGB pixel preservation and internal NoData mask, including valid black")
