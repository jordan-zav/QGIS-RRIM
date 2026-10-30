# Copyright (c) 2026 Jordan Zavaleta
# This file is part of QGIS-RRIM.
# QGIS-RRIM is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
QGIS-RRIM
---------

Implements the Red Relief Image Map (RRIM) base layer generation
following Chiba, Kaneta & Suzuki (2008).
"""

import os
import uuid
from typing import ClassVar

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingMultiStepFeedback,
    QgsProcessingException,
    QgsProcessingUtils,
    QgsProviderRegistry,
    QgsRasterShader,
    QgsColorRampShader,
    QgsSingleBandPseudoColorRenderer,
)

from qgis.PyQt.QtGui import QIcon, QColor, QPainter
from qgis.PyQt import sip
from qgis import processing

from .rrim_openness import compute_openness_raster
from .rrim_raster import raster_math, require_north_up, validate_output_paths, check_canceled, atomic_raster_output


def _build_renderer(layer, items, minimum=None, maximum=None):
    shader = QgsColorRampShader()
    shader.setColorRampType(QgsColorRampShader.Interpolated)
    if minimum is not None:
        shader.setMinimumValue(minimum)
    if maximum is not None:
        shader.setMaximumValue(maximum)
    shader.setColorRampItemList(
        [QgsColorRampShader.ColorRampItem(value, QColor(color), label) for value, color, label in items]
    )

    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)

    return QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader)


class _LayerNamePostProcessor(QgsProcessingLayerPostProcessorInterface):
    # Processing can transfer LayerDetails between contexts after the algorithm
    # has returned. Keep the Python overrides alive for the C++ object's lifetime.
    _instances: ClassVar[dict] = {}

    @classmethod
    def create(cls, layer_name, style_mode=None):
        for key, processor in tuple(cls._instances.items()):
            if sip.isdeleted(processor):
                cls._instances.pop(key, None)
        processor = cls(layer_name, style_mode)
        cls._instances[id(processor)] = processor
        return processor

    def __init__(self, layer_name, style_mode=None):
        super().__init__()
        self.layer_name = layer_name
        self.style_mode = style_mode

    def postProcessLayer(self, layer, context, feedback):
        layer.setName(self.layer_name)

        if self.style_mode == "slope_norm":
            items = [
                (0.0, "#fff5f0", "0.0000"),
                (11.7, "#fee0d2", "11.7000"),
                (23.4, "#fcbba1", "23.4000"),
                (35.1, "#fc9272", "35.1000"),
                (46.8, "#fb6a4a", "46.8000"),
                (58.5, "#ef3b2c", "58.5000"),
                (70.2, "#cb181d", "70.2000"),
                (81.0, "#a50f15", "81.0000"),
                (90.0, "#67000d", "90.0000"),
            ]
            layer.setRenderer(_build_renderer(layer, items, minimum=0.0, maximum=90.0))
            layer.setBlendMode(QPainter.CompositionMode_Multiply)
            layer.triggerRepaint()
        elif self.style_mode == "diff_norm":
            items = [
                (-50.0, "#000000", "-50"),
                (50.0, "#ffffff", "50"),
            ]
            layer.setRenderer(_build_renderer(layer, items, minimum=-50.0, maximum=50.0))
            layer.triggerRepaint()


class RRIMGenerator(QgsProcessingAlgorithm):

    INPUT_RASTER = "INPUT_RASTER"
    OUT_SLOPE = "OUT_SLOPE"
    OUT_DIFF = "OUT_DIFF"
    OUT_SLOPE_NORM = "OUT_SLOPE_NORM"
    OUT_DIFF_NORM = "OUT_DIFF_NORM"
    AUTO_NORMALIZE = "AUTO_NORMALIZE"

    def name(self):
        return "rrim_generator"

    def displayName(self):
        return "RRIM Generator"

    def group(self):
        return "QGIS-RRIM"

    def groupId(self):
        return "qgis_rrim"

    def shortHelpString(self):
        return (
            "Generates the geomorphometric products required for "
            "Red Relief Image Map (RRIM):<br><br>"
            "&bull; Slope (native QGIS)<br>"
            "&bull; Differential Openness = (Positive &minus; Negative) / 2 (internal algorithm)<br><br>"
            "Requires a single-band, north-up DEM in a projected CRS with consistent "
            "horizontal and elevation units (slope Z factor = 1). "
            "Openness uses a fixed radius of 10 cells and 16 directions; no RVT plugin is required.<br><br>"
            "Optional normalization additionally creates display-ready copies:<br>"
            "&bull; Normalized Slope: Reds, 0 to 90<br>"
            "&bull; Normalized Differential Openness: Grays, -50 to 50<br><br>"
            "Intermediate rasters are written to the system TEMP directory "
            "and removed after processing.<br><br>"
            "<b>VISUALIZATION NOTE:</b><br>"
            "For the Normalized Slope output, the style is fixed to the RRIM "
            "red ramp from <b>0 to 90</b> with <b>Multiply</b> blending.<br>"
            "For the Normalized Differential Openness output, the style is "
            "fixed to grayscale from <b>-50 to 50</b>.<br><br>"
            "RRIM RGB generation is handled separately by the RRIM RGB Composer.<br><br>"
            "All output paths must differ from the DEM, its VRT dependencies and each other. "
            "Choose a new filename when a destination has external masks, overviews or PAM sidecars. "
            "Cancellation preserves the destination being written; outputs already completed "
            "by earlier stages remain.<br><br>"
            "Workflow follows <a href='https://www.researchgate.net/publication/237517308_Red_relief_image_map_New_visualization_method_for_three_dimensional_data'>Chiba et al. (2008)</a>.<br><br>"
            "-----------------------------------------------------------<br>"
            "&copy; 2025 <a href='https://linkedin.com/in/jordan-zav'><b>Zavaleta, J.</b></a><br>"
            "<i>Geological Engineering Undergraduate Student at UNI</i><br>"
            "Released under the GNU GPLv3 License"
        )

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_RASTER,
                "Input raster surface (DEM)"
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUT_SLOPE,
                "Slope"
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUT_DIFF,
                "Differential Openness"
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.AUTO_NORMALIZE,
                "Create Normalized Slope and Differential Openness",
                defaultValue=False
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUT_SLOPE_NORM,
                "Normalized Slope",
                optional=True,
                createByDefault=True
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUT_DIFF_NORM,
                "Normalized Differential Openness",
                optional=True,
                createByDefault=True
            )
        )

    def _normalized_output_path(self, parameters, output_name, context, filename):
        return (
            self.parameterAsOutputLayer(parameters, output_name, context)
            or QgsProcessingUtils.generateTempFilename(filename)
        )

    def _register_output_layer(self, context, path, output_name, label, style_mode=None):
        if not path:
            return

        details = QgsProcessingContext.LayerDetails(
            label,
            context.project(),
            output_name
        )
        details.setPostProcessor(_LayerNamePostProcessor.create(label, style_mode))
        context.addLayerToLoadOnCompletion(path, details)

    def processAlgorithm(self, parameters, context, feedback):
        feedback = QgsProcessingMultiStepFeedback(4, feedback)
        try:
            check_canceled(feedback)
        except InterruptedError as error:
            raise QgsProcessingException(str(error)) from error

        raster_layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        if raster_layer is None or not raster_layer.isValid() or raster_layer.bandCount() != 1:
            raise QgsProcessingException("Input raster must be a valid single-band DEM.")
        if not raster_layer.crs().isValid() or raster_layer.crs().isGeographic():
            raise QgsProcessingException(
                "Input DEM must use a valid projected CRS whose horizontal units match the elevation units."
            )

        raster_path = raster_layer.source()
        auto_normalize = self.parameterAsBool(parameters, self.AUTO_NORMALIZE, context)
        slope_path = self.parameterAsOutputLayer(parameters, self.OUT_SLOPE, context)
        diff_path = self.parameterAsOutputLayer(parameters, self.OUT_DIFF, context)

        slope_norm = None
        diff_norm = None

        slope_norm_path = None
        diff_norm_path = None
        if auto_normalize:
            slope_norm_path = self._normalized_output_path(
                parameters,
                self.OUT_SLOPE_NORM,
                context,
                "rrim_slope_norm.tif"
            )
            diff_norm_path = self._normalized_output_path(
                parameters,
                self.OUT_DIFF_NORM,
                context,
                "rrim_diff_norm.tif"
            )

        input_paths = [raster_path]
        from osgeo import gdal
        decoded = QgsProviderRegistry.instance().decodeUri(raster_layer.providerType(), raster_path)
        if decoded.get("path") and decoded["path"] not in input_paths:
            input_paths.append(decoded["path"])
        for candidate in tuple(input_paths):
            if os.path.isfile(candidate):
                original = gdal.Open(candidate)
                if original is not None:
                    input_paths.extend(original.GetFileList() or [])
                original = None
        try:
            validate_output_paths(input_paths, [slope_path, diff_path] +
                                  ([slope_norm_path, diff_norm_path] if auto_normalize else []))
        except ValueError as error:
            raise QgsProcessingException(str(error)) from error

        temp_dir = QgsProcessingUtils.tempFolder()
        uid = uuid.uuid4().hex
        op_path = os.path.join(temp_dir, f"rrim_op_{uid}.tif")
        on_path = os.path.join(temp_dir, f"rrim_on_{uid}.tif")
        materialized_input_path = None
        try:
            if not os.path.isfile(raster_path):
                materialized_input_path = os.path.join(temp_dir, f"rrim_input_{uid}.tif")
                raster_path = processing.run(
                    "gdal:translate", {"INPUT": raster_layer, "OUTPUT": materialized_input_path},
                    context=context, feedback=feedback, is_child_algorithm=True,
                )["OUTPUT"]
            require_north_up(raster_path)
            feedback.setCurrentStep(0)
            compute_openness_raster(
                raster_path,
                op_path,
                radius=10,
                num_directions=16,
                invert=False,
                feedback=feedback,
            )

            feedback.setCurrentStep(1)
            compute_openness_raster(
                raster_path,
                on_path,
                radius=10,
                num_directions=16,
                invert=True,
                feedback=feedback,
            )
            feedback.setCurrentStep(2)
            diff = raster_math(op_path, diff_path, second_path=on_path, feedback=feedback)
            if auto_normalize:
                diff_norm = raster_math(diff, diff_norm_path, limits=(-50.0, 50.0), feedback=feedback)

            feedback.setCurrentStep(3)
            with atomic_raster_output(slope_path, input_paths, feedback) as temporary_slope:
                processing.run(
                    "native:slope", {"INPUT": raster_layer, "Z_FACTOR": 1, "OUTPUT": temporary_slope},
                    context=context, feedback=feedback, is_child_algorithm=True,
                )
            slope = slope_path
            if auto_normalize:
                slope_norm = raster_math(slope, slope_norm_path, limits=(0.0, 90.0), feedback=feedback)
        except (InterruptedError, ValueError, OSError, RuntimeError) as error:
            raise QgsProcessingException(str(error)) from error
        finally:
            for temp_path in (op_path, on_path, materialized_input_path):
                try:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError:
                    feedback.pushInfo(f"Could not remove temporary file in use: {temp_path}")

        self._register_output_layer(context, slope, self.OUT_SLOPE, "Slope")
        self._register_output_layer(context, diff, self.OUT_DIFF, "Differential Openness")
        if auto_normalize:
            self._register_output_layer(
                context,
                slope_norm,
                self.OUT_SLOPE_NORM,
                "Normalized Slope",
                "slope_norm"
            )
            self._register_output_layer(
                context,
                diff_norm,
                self.OUT_DIFF_NORM,
                "Normalized Differential Openness",
                "diff_norm"
            )

        return {
            self.OUT_SLOPE: slope,
            self.OUT_DIFF: diff,
            self.OUT_SLOPE_NORM: slope_norm,
            self.OUT_DIFF_NORM: diff_norm,
        }

    def createInstance(self):
        return RRIMGenerator()
