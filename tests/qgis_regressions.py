"""Audit raster safety and Processing behavior with QGIS's own Python."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback
import uuid
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QGIS_AUTH_DB_DIR_PATH"] = str(args.output / "auth")
(args.output / "auth").mkdir(exist_ok=True)

import numpy as np
from osgeo import gdal, osr
from qgis.core import (QgsApplication, QgsProject, QgsRasterLayer, QgsProcessingContext,
                       QgsProcessingFeedback, QgsProcessingException, QgsSettings, Qgis)
from qgis.PyQt.QtCore import QSettings, QT_VERSION_STR

app = QgsApplication([], False, str(args.output / "profile"))
app.initQgis()
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(args.output / "settings"))
assert args.output.resolve() in Path(QgsSettings().fileName()).resolve().parents
(args.output / "environment.json").write_text(json.dumps({
    "qgis": Qgis.QGIS_VERSION, "qt": QT_VERSION_STR,
    "gdal": gdal.VersionInfo("RELEASE_NAME"), "python": sys.version,
}, indent=2), encoding="utf-8")
sys.path.insert(0, str(Path(QgsApplication.prefixPath()) / "python/plugins"))
from processing.core.Processing import Processing
Processing.initialize()

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rrim_review", root / "__init__.py", submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from rrim_review import rrim_algorithm as generator_module
from rrim_review import rrim_rgb_composer as composer_module
from rrim_review import rrim_openness as openness_module
from rrim_review import rrim_raster as raster_module
from rrim_review.qgis_rrim import QGISRRIM

crs = osr.SpatialReference()
crs.ImportFromEPSG(32718)
results = []


def raster(name, values=None):
    filename = str(args.output / (name + ".tif"))
    values = np.zeros((14, 16), dtype=np.float32) if values is None else np.asarray(values, dtype=np.float32)
    dataset = gdal.GetDriverByName("GTiff").Create(filename, values.shape[1], values.shape[0], 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((500000, 10, 0, 8700000, 0, -10))
    dataset.SetProjection(crs.ExportToWkt())
    dataset.GetRasterBand(1).WriteArray(values)
    dataset = None
    return filename


def checksum(filename):
    return hashlib.sha256(Path(filename).read_bytes()).hexdigest() if Path(filename).exists() else None


def run(name, callback):
    try:
        callback()
        result = {"case": name, "passed": True}
    except Exception:
        result = {"case": name, "passed": False, "error": traceback.format_exc()}
    results.append(result)
    (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(("PASS " if result["passed"] else "FAIL ") + name, flush=True)
    if not result["passed"]:
        print(result["error"], flush=True)


def source_alias(operation):
    filename = raster("alias_" + operation)
    original = checksum(filename)
    driver = gdal.GetDriverByName("GTiff")
    class GuardedDriver:
        def Create(self, destination, *a, **kw):
            if os.path.abspath(destination) == os.path.abspath(filename):
                raise AssertionError("Attempted to create an output over the input DEM")
            return driver.Create(destination, *a, **kw)
    with patch.object(gdal, "GetDriverByName", return_value=GuardedDriver()):
        try:
            if operation == "math":
                raster_module.raster_math(filename, filename)
            else:
                openness_module.compute_openness_raster(filename, filename, radius=2)
        except ValueError:
            pass
        else:
            raise AssertionError("Input/output alias was not rejected")
    assert checksum(filename) == original


run("raster_math_rejects_source_overwrite", lambda: source_alias("math"))
run("openness_rejects_source_overwrite", lambda: source_alias("openness"))


def colliding_generator_outputs():
    dem = raster("generator_dem")
    algorithm = generator_module.RRIMGenerator()
    algorithm.initAlgorithm()
    context = QgsProcessingContext()
    context.setProject(QgsProject.instance())
    same_output = str(args.output / "same_destination.tif")
    with patch.object(generator_module, "compute_openness_raster", side_effect=AssertionError("Work started before validating conflicting outputs")):
        try:
            algorithm.processAlgorithm({"INPUT_RASTER": dem, "OUT_SLOPE": same_output,
                                        "OUT_DIFF": same_output, "AUTO_NORMALIZE": False}, context, QgsProcessingFeedback())
        except QgsProcessingException as exc:
            assert "output" in str(exc).casefold()
        else:
            raise AssertionError("Conflicting output destinations were accepted")


run("generator_rejects_conflicting_outputs_before_work", colliding_generator_outputs)


class CancelAfterWork:
    def __init__(self):
        self.calls = 0

    def isCanceled(self):
        self.calls += 1
        return self.calls >= 4

    def setProgress(self, value):
        pass


def cancellation_preserves_existing(operation):
    shape = (1030, 16) if operation == "math" else (14, 16)
    source = raster("cancel_source_" + operation, np.ones(shape))
    destination = raster("cancel_destination_" + operation, np.full(shape, 37))
    original = checksum(destination)
    try:
        if operation == "math":
            raster_module.raster_math(source, destination, feedback=CancelAfterWork())
        else:
            openness_module.compute_openness_raster(source, destination, radius=2, block_size=4, feedback=CancelAfterWork())
    except InterruptedError:
        pass
    else:
        raise AssertionError("Cancellation was ignored")
    assert checksum(destination) == original, "Cancellation changed or removed the previous output"


run("math_cancellation_preserves_previous_output", lambda: cancellation_preserves_existing("math"))
run("openness_cancellation_preserves_previous_output", lambda: cancellation_preserves_existing("openness"))


def rgb_cancelled():
    slope = raster("rgb_slope")
    diff = raster("rgb_openness")
    destination = raster("rgb_destination", np.full((14, 16), 37))
    original = checksum(destination)
    algorithm = composer_module.RRIMRGBComposer()
    algorithm.initAlgorithm()
    feedback = QgsProcessingFeedback()
    feedback.cancel()
    try:
        algorithm.processAlgorithm({"INPUT_SLOPE": slope, "INPUT_DO": diff, "SLOPE_MAX": 90,
                                    "DO_MIN": -50, "DO_MAX": 50, "OUTPUT": destination}, QgsProcessingContext(), feedback)
    except (QgsProcessingException, InterruptedError):
        pass
    else:
        raise AssertionError("RGB composition ignored Cancel and published its output")
    assert checksum(destination) == original


run("rgb_respects_processing_cancellation", rgb_cancelled)


def provider_lifecycle():
    plugin = QGISRRIM(None)
    try:
        for _ in range(3):
            plugin.initGui()
            assert QgsApplication.processingRegistry().providerById("qgis_rrim") is not None
            plugin.unload()
            assert plugin.provider is None, "Unloading left a deleted provider reference"
            plugin.unload()
    finally:
        registered = QgsApplication.processingRegistry().providerById("qgis_rrim")
        if registered:
            QgsApplication.processingRegistry().removeProvider(registered)
        plugin.provider = None


run("provider_reload_and_repeated_unload", provider_lifecycle)


def context_project():
    project = QgsProject()
    context = QgsProcessingContext()
    context.setProject(project)
    algorithm = generator_module.RRIMGenerator()
    filename = raster("context_target")
    algorithm._register_output_layer(context, filename, "OUT_SLOPE", "Slope")
    details = context.layersToLoadOnCompletion()[filename]
    assert details.project is project, "Output targets the global project instead of the Processing context"


run("outputs_respect_processing_context_project", context_project)


def vrt_dependency():
    source = raster("vrt_protected_dem")
    vrt = str(args.output / "input.vrt")
    translated = gdal.Translate(vrt, source, format="VRT")
    assert translated is not None
    translated = None
    original = checksum(source)
    for function in (raster_module.raster_math, openness_module.compute_openness_raster):
        try:
            function(vrt, source)
        except ValueError:
            pass
        else:
            raise AssertionError("A VRT dependency could be overwritten")
    algorithm = generator_module.RRIMGenerator()
    algorithm.initAlgorithm()
    with patch.object(generator_module, "compute_openness_raster", side_effect=AssertionError("VRT alias was not rejected before work")):
        try:
            algorithm.processAlgorithm({"INPUT_RASTER": vrt, "OUT_SLOPE": str(args.output / "vrt_slope.tif"),
                                        "OUT_DIFF": source, "AUTO_NORMALIZE": False}, QgsProcessingContext(), QgsProcessingFeedback())
        except QgsProcessingException:
            pass
        else:
            raise AssertionError("Generator accepted an output over a VRT dependency")
    assert checksum(source) == original


run("vrt_dependencies_cannot_be_overwritten", vrt_dependency)


def normalized_collision():
    dem = raster("normalized_input")
    for alias in (dem, str(args.output / "normalized_diff.tif")):
        algorithm = generator_module.RRIMGenerator()
        algorithm.initAlgorithm()
        with patch.object(generator_module, "compute_openness_raster", side_effect=AssertionError("Invalid normalized output started work")):
            try:
                algorithm.processAlgorithm({"INPUT_RASTER": dem, "OUT_SLOPE": str(args.output / "normalized_slope.tif"),
                                            "OUT_DIFF": str(args.output / "normalized_diff.tif"), "AUTO_NORMALIZE": True,
                                            "OUT_SLOPE_NORM": alias, "OUT_DIFF_NORM": str(args.output / "normalized_diff_copy.tif")},
                                           QgsProcessingContext(), QgsProcessingFeedback())
            except QgsProcessingException:
                pass
            else:
                raise AssertionError("Normalized output collision was accepted")


run("normalized_outputs_cannot_alias_dem_or_other_outputs", normalized_collision)


def virtual_rasters():
    prefix = "/vsimem/rrim_review_" + uuid.uuid4().hex
    source = prefix + "_input.tif"
    destination = prefix + "_output.tif"
    dataset = gdal.GetDriverByName("GTiff").Create(source, 8, 6, 1, gdal.GDT_Float32)
    dataset.GetRasterBand(1).WriteArray(np.full((6, 8), 25, dtype=np.float32))
    dataset = None
    for _ in range(2):
        raster_module.raster_math(source, destination, limits=(0, 10))
        output = gdal.Open(destination)
        np.testing.assert_array_equal(output.ReadAsArray(), np.full((6, 8), 10))
        output = None


run("vsi_memory_output_and_replacement", virtual_rasters)


def rgb_mid_cancellation():
    slope = QgsRasterLayer(raster("mid_rgb_slope", np.zeros((1030, 16))), "slope")
    diff = QgsRasterLayer(raster("mid_rgb_diff", np.zeros((1030, 16))), "diff")
    destination = raster("mid_rgb_output", np.full((1030, 16), 37))
    original = checksum(destination)
    try:
        composer_module.export_rrim_geotiff(slope, diff, destination, feedback=CancelAfterWork())
    except InterruptedError:
        pass
    else:
        raise AssertionError("RGB cancellation between blocks was ignored")
    assert checksum(destination) == original


run("rgb_mid_write_cancellation_preserves_old_output", rgb_mid_cancellation)


def provider_collision():
    first, second = QGISRRIM(None), QGISRRIM(None)
    first.initGui()
    owner = first.provider
    try:
        try:
            second.initGui()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Duplicate provider registration was silently accepted")
        second.unload()
        assert second.provider is None
        assert QgsApplication.processingRegistry().providerById("qgis_rrim") is owner
    finally:
        first.unload()


run("duplicate_provider_does_not_unregister_the_owner", provider_collision)


def postprocessor_lifetime():
    import gc
    from qgis.PyQt.QtGui import QPainter
    filename = raster("postprocess")
    project = QgsProject()
    context = QgsProcessingContext()
    context.setProject(project)
    algorithm = generator_module.RRIMGenerator()
    algorithm._register_output_layer(context, filename, "OUT_SLOPE_NORM", "Normalized Slope", "slope_norm")
    algorithm = None
    gc.collect()
    processor = context.layersToLoadOnCompletion()[filename].postProcessor()
    layer = QgsRasterLayer(filename, "Unstyled")
    processor.postProcessLayer(layer, context, QgsProcessingFeedback())
    assert layer.name() == "Normalized Slope"
    assert layer.renderer().type() == "singlebandpseudocolor"
    assert layer.blendMode() == QPainter.CompositionMode_Multiply


run("postprocessor_survives_algorithm_and_applies_style", postprocessor_lifetime)


def transferred_postprocessor():
    import gc
    filename = raster("transferred_style")
    source, destination = QgsProcessingContext(), QgsProcessingContext()
    algorithm = generator_module.RRIMGenerator()
    algorithm._register_output_layer(source, filename, "OUT_DIFF_NORM", "Differential display", "diff_norm")
    destination.takeResultsFrom(source)
    source = algorithm = None
    gc.collect()
    layer = QgsRasterLayer(filename, "Unstyled")
    destination.layersToLoadOnCompletion()[filename].postProcessor().postProcessLayer(layer, destination, QgsProcessingFeedback())
    assert layer.name() == "Differential display"
    assert layer.renderer().type() == "singlebandpseudocolor"


run("style_survives_processing_context_transfer", transferred_postprocessor)


def math_masks():
    values = np.array([[-9999, 80, -80], [10, 20, 30]], dtype=np.float32)
    source = raster("math_mask_input", values)
    dataset = gdal.Open(source, gdal.GA_Update)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999)
    band.CreateMaskBand(gdal.GMF_PER_DATASET)
    mask = np.full(values.shape, 255, dtype=np.uint8)
    mask[1, 1] = 0
    band.GetMaskBand().WriteArray(mask)
    band = dataset = None
    destination = str(args.output / "math_mask_output.tif")
    raster_module.raster_math(source, destination, limits=(-50, 50))
    output = gdal.Open(destination)
    result = output.ReadAsArray()
    assert np.isnan(result[0, 0]) and np.isnan(result[1, 1])
    assert result[0, 1] == 50 and result[0, 2] == -50 and result[1, 0] == 10
    assert np.isnan(output.GetRasterBand(1).GetNoDataValue())


run("raster_math_preserves_masks_and_clamps_values", math_masks)


def generator_slope_cancellation():
    from qgis.core import QgsProcessingUtils
    source = raster("cancel_generator_dem", np.arange(24 * 32).reshape(24, 32))
    slope = raster("cancel_generator_slope", np.full((24, 32), 37))
    old_slope = checksum(slope)
    original_dem = checksum(source)
    feedback = QgsProcessingFeedback()
    feedback.progressChanged.connect(lambda progress: feedback.cancel() if progress >= 80 else None)
    algorithm = generator_module.RRIMGenerator()
    algorithm.initAlgorithm()
    scratch = Path(QgsProcessingUtils.tempFolder())
    before = set(scratch.glob("rrim_*.tif"))
    try:
        algorithm.processAlgorithm({"INPUT_RASTER": source, "OUT_SLOPE": slope,
                                    "OUT_DIFF": str(args.output / "cancel_generator_diff.tif"), "AUTO_NORMALIZE": False},
                                   QgsProcessingContext(), feedback)
    except QgsProcessingException:
        pass
    else:
        raise AssertionError("Late generator cancellation was ignored")
    assert feedback.isCanceled()
    assert checksum(slope) == old_slope and checksum(source) == original_dem
    assert set(scratch.glob("rrim_*.tif")) == before, "Generator retained its scratch rasters after cancellation"


run("generator_late_cancel_preserves_slope_and_dem", generator_slope_cancellation)


def write_failure(operation):
    source = raster("write_failure_input_" + operation)
    destination = raster("write_failure_output_" + operation, np.full((14, 16), 37))
    previous = checksum(destination)
    driver = gdal.GetDriverByName("GTiff")
    class FailingBand:
        def __init__(self, band):
            self.band = band

        def __getattr__(self, name):
            return getattr(self.band, name)

        def WriteArray(self, *a, **kw):
            return gdal.CE_Failure

    class FailingDataset:
        def __init__(self, dataset):
            self.dataset = dataset

        def __getattr__(self, name):
            return getattr(self.dataset, name)

        def GetRasterBand(self, index):
            return FailingBand(self.dataset.GetRasterBand(index))

    class FailingDriver:
        def Create(self, *a, **kw):
            return FailingDataset(driver.Create(*a, **kw))

    input_layer = QgsRasterLayer(source, "input")
    with patch.object(gdal, "GetDriverByName", return_value=FailingDriver()):
        try:
            if operation == "math":
                raster_module.raster_math(source, destination)
            elif operation == "openness":
                openness_module.compute_openness_raster(source, destination, radius=2)
            else:
                composer_module.export_rrim_geotiff(input_layer, input_layer, destination)
        except (RuntimeError, QgsProcessingException):
            pass
        else:
            raise AssertionError("A failed GDAL write was published as a successful output")
    assert checksum(destination) == previous


run("math_does_not_publish_failed_gdal_write", lambda: write_failure("math"))
run("openness_does_not_publish_failed_gdal_write", lambda: write_failure("openness"))
run("rgb_does_not_publish_failed_gdal_write", lambda: write_failure("rgb"))

print(json.dumps({"passed": sum(item["passed"] for item in results), "failed": sum(not item["passed"] for item in results)}, indent=2))
raise SystemExit(1 if any(not item["passed"] for item in results) else 0)
