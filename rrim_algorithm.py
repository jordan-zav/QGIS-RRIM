"""
QGIS-RRIM
---------

Implements the Red Relief Image Map (RRIM) base layer generation
following Chiba, Kaneta & Suzuki (2008).
"""

import os
import uuid

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputRasterLayer,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingMultiStepFeedback,
    QgsProcessingException,
    QgsProcessingUtils,
    QgsRasterLayer,
    QgsProject,
    QgsRasterShader,
    QgsColorRampShader,
    QgsSingleBandPseudoColorRenderer,
)

from qgis.PyQt.QtGui import QIcon
from PyQt5.QtGui import QColor, QPainter
import processing


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
            "&bull; Differential Openness = (Positive &minus; Negative) / 2 (RVT)<br><br>"
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
            "Workflow follows <a href='https://www.researchgate.net/publication/237517308_Red_relief_image_map_New_visualization_method_for_three_dimensional_data'>Chiba et al. (2008)</a>.<br><br>"
            "-----------------------------------------------------------<br>"
            "&copy; 2025 <a href='https://linkedin.com/in/jordan-zav'><b>Zavaleta, J.</b></a><br>"
            "<i>Geological Engineering Undergraduate Student at UNI</i><br>"
            "Released under the MIT License"
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

        self.addOutput(
            QgsProcessingOutputRasterLayer(
                self.OUT_SLOPE_NORM,
                "Slope_Norm"
            )
        )

        self.addOutput(
            QgsProcessingOutputRasterLayer(
                self.OUT_DIFF_NORM,
                "Differential Openness_Norm"
            )
        )

    def _copy_output(self, source_path, layer_name, output_path, context, feedback):
        layer = QgsRasterLayer(source_path, layer_name)
        if not layer.isValid():
            raise QgsProcessingException(f"Failed to load {layer_name} for normalized copy.")

        try:
            provider = layer.dataProvider()
            extent = layer.extent()
            extent_str = (
                f"{extent.xMinimum()},{extent.xMaximum()},"
                f"{extent.yMinimum()},{extent.yMaximum()}"
            )
            cell_size = min(
                abs(layer.rasterUnitsPerPixelX()),
                abs(layer.rasterUnitsPerPixelY())
            )
            result = processing.run(
                "native:rastercalc",
                {
                    "LAYERS": [layer],
                    "EXPRESSION": f'"{layer_name}@1"',
                    "EXTENT": extent_str,
                    "CELL_SIZE": cell_size,
                    "CRS": layer.crs().authid() or source_path,
                    "OUTPUT": output_path
                },
                context=context,
                feedback=feedback,
                is_child_algorithm=True
            )["OUTPUT"]
        finally:
            del layer

        return result

    def _clamp_output(self, source_path, layer_name, expression, output_path, context, feedback):
        layer = QgsRasterLayer(source_path, layer_name)
        if not layer.isValid():
            raise QgsProcessingException(f"Failed to load {layer_name} for normalization.")

        try:
            extent = layer.extent()
            extent_str = (
                f"{extent.xMinimum()},{extent.xMaximum()},"
                f"{extent.yMinimum()},{extent.yMaximum()}"
            )
            cell_size = min(
                abs(layer.rasterUnitsPerPixelX()),
                abs(layer.rasterUnitsPerPixelY())
            )
            result = processing.run(
                "native:rastercalc",
                {
                    "LAYERS": [layer],
                    "EXPRESSION": expression,
                    "EXTENT": extent_str,
                    "CELL_SIZE": cell_size,
                    "CRS": layer.crs().authid() or source_path,
                    "OUTPUT": output_path
                },
                context=context,
                feedback=feedback,
                is_child_algorithm=True
            )["OUTPUT"]
        finally:
            del layer

        return result

    def _register_output_layer(self, context, path, output_name, label, style_mode=None):
        if not path:
            return

        details = QgsProcessingContext.LayerDetails(
            label,
            QgsProject.instance(),
            output_name
        )
        details.setPostProcessor(_LayerNamePostProcessor(label, style_mode))
        context.addLayerToLoadOnCompletion(path, details)

    def _add_styled_layer_to_project(self, path, label, style_mode):
        layer = QgsRasterLayer(path, label)
        if not layer.isValid():
            raise QgsProcessingException(f"Failed to load {label} into the project.")

        post_processor = _LayerNamePostProcessor(label, style_mode)
        post_processor.postProcessLayer(layer, None, None)
        QgsProject.instance().addMapLayer(layer)

    def processAlgorithm(self, parameters, context, feedback):
        feedback = QgsProcessingMultiStepFeedback(4, feedback)

        raster_layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        if raster_layer is None or raster_layer.bandCount() != 1:
            raise QgsProcessingException("Input raster must be a valid single-band DEM.")

        raster = parameters[self.INPUT_RASTER]
        auto_normalize = self.parameterAsBool(parameters, self.AUTO_NORMALIZE, context)

        slope_norm = None
        diff_norm = None

        temp_dir = QgsProcessingUtils.tempFolder()
        uid = uuid.uuid4().hex

        op_path = os.path.join(temp_dir, f"rrim_op_{uid}.tif")
        on_path = os.path.join(temp_dir, f"rrim_on_{uid}.tif")
        slope_norm_path = os.path.join(temp_dir, f"rrim_slope_norm_{uid}.tif")
        diff_norm_path = os.path.join(temp_dir, f"rrim_diff_norm_{uid}.tif")

        feedback.setCurrentStep(0)
        processing.run(
            "rvt:rvt_opns",
            {
                "INPUT": raster,
                "VE_FACTOR": 1,
                "RADIUS": 10,
                "NUM_DIRECTIONS": 16,
                "NOISE_REMOVE": 0,
                "OPNS_TYPE": 0,
                "SAVE_AS_8BIT": False,
                "OUTPUT": op_path
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        feedback.setCurrentStep(1)
        processing.run(
            "rvt:rvt_opns",
            {
                "INPUT": raster,
                "VE_FACTOR": 1,
                "RADIUS": 10,
                "NUM_DIRECTIONS": 16,
                "NOISE_REMOVE": 0,
                "OPNS_TYPE": 1,
                "SAVE_AS_8BIT": False,
                "OUTPUT": on_path
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        feedback.setCurrentStep(2)
        op_layer = QgsRasterLayer(op_path, "OP")
        on_layer = QgsRasterLayer(on_path, "ON")

        if not op_layer.isValid() or not on_layer.isValid():
            raise QgsProcessingException("Failed to load intermediate openness layers.")

        try:
            extent = raster_layer.extent()
            extent_str = (
                f"{extent.xMinimum()},{extent.xMaximum()},"
                f"{extent.yMinimum()},{extent.yMaximum()}"
            )
            cell_size = min(
                abs(raster_layer.rasterUnitsPerPixelX()),
                abs(raster_layer.rasterUnitsPerPixelY())
            )
            diff = processing.run(
                "native:rastercalc",
                {
                    "LAYERS": [op_layer, on_layer],
                    "EXPRESSION": '("OP@1" - "ON@1") / 2',
                    "EXTENT": extent_str,
                    "CELL_SIZE": cell_size,
                    "CRS": raster_layer.crs().authid() or parameters[self.INPUT_RASTER],
                    "OUTPUT": parameters[self.OUT_DIFF]
                },
                context=context,
                feedback=feedback,
                is_child_algorithm=True
            )["OUTPUT"]
        finally:
            del op_layer
            del on_layer

        if auto_normalize:
            diff_norm = self._clamp_output(
                diff,
                "Differential Openness",
                'if("Differential Openness@1" > 50, 50, if("Differential Openness@1" < -50, -50, "Differential Openness@1"))',
                diff_norm_path,
                context,
                feedback
            )

        feedback.setCurrentStep(3)
        slope = processing.run(
            "native:slope",
            {
                "INPUT": raster,
                "Z_FACTOR": 1,
                "OUTPUT": parameters[self.OUT_SLOPE]
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )["OUTPUT"]

        if auto_normalize:
            slope_norm = self._copy_output(
                slope,
                "Slope",
                slope_norm_path,
                context,
                feedback
            )

        for temp_path in (op_path, on_path):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except PermissionError:
                feedback.pushInfo(f"Could not remove temporary file in use: {temp_path}")

        self._register_output_layer(context, slope, self.OUT_SLOPE, "Slope")
        self._register_output_layer(context, diff, self.OUT_DIFF, "Differential Openness")
        if auto_normalize:
            self._add_styled_layer_to_project(
                slope_norm,
                "Normalized Slope",
                "slope_norm"
            )
            self._add_styled_layer_to_project(
                diff_norm,
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
