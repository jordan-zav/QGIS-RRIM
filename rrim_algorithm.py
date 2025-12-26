"""
QGIS-RRIM
---------

Implements the Red Relief Image Map (RRIM) base layer generation
following Chiba, Kaneta & Suzuki (2007).

This algorithm computes:
- Slope
- Differential Openness = (Positive Openness - Negative Openness) / 2

Author: Jordan Zavaleta
License: MIT
Year: 2025

Mandatory citation:
Chiba, T., Kaneta, S., & Suzuki, Y. (2007).
Red relief image map: New visualization method for three dimensional data.
ISPRS Journal of Photogrammetry and Remote Sensing, 62(2), 107–116.
"""

import os
import uuid

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterRasterDestination,
    QgsProcessingMultiStepFeedback,
    QgsProcessingException,
    QgsProcessingUtils,
    QgsRasterLayer
)

from qgis.PyQt.QtGui import QIcon
import processing


class RRIMAlgorithm(QgsProcessingAlgorithm):

    INPUT_RASTER = "INPUT_RASTER"
    OUT_SLOPE = "OUT_SLOPE"
    OUT_DIFF = "OUT_DIFF"

    # --------------------------------------------------
    # Metadata
    # --------------------------------------------------
    def name(self):
        return "rrim_base_layers"

    def displayName(self):
        return "RRIM Base Layers (Slope & Differential Openness)"

    def group(self):
        return "QGIS-RRIM"

    def groupId(self):
        return "qgis_rrim"

    def shortHelpString(self):
        return (
            "Generates base layers for Red Relief Image Map (RRIM):<br><br>"
            "&bull; Slope (native QGIS)<br>"
            "&bull; Differential Openness = (Positive &minus; Negative) / 2 (RVT)<br><br>"
            "Intermediate rasters are written to the system TEMP directory "
            "and removed after processing.<br><br>"
            "<b>VISUALIZATION NOTE:</b><br>"
            "For the Slope output, specify <b>Single band reds</b> "
            "(Singleband pseudocolor) and set the <b>Blending Mode to Multiply</b>.<br><br>"
            "Workflow follows Chiba et al. (2007).<br><br>"
            "-----------------------------------------------------------<br>"
            "&copy; 2025 <a href='https://linkedin.com/in/jordan-zav'><b>Zavaleta, J.</b></a><br>"
            "<i>Geological Engineering Undergraduate Student at UNI</i><br>"
            "Released under the MIT License"
        )

    def icon(self):
        return QIcon(
            os.path.join(
                os.path.dirname(__file__),
                "icon.png"
            )
        )

    # --------------------------------------------------
    # Parameters
    # --------------------------------------------------
    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_RASTER,
                "Input raster surface (DEM or equivalent)"
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

    # --------------------------------------------------
    # Algorithm
    # --------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):

        feedback = QgsProcessingMultiStepFeedback(4, feedback)

        raster_layer = self.parameterAsRasterLayer(
            parameters, self.INPUT_RASTER, context
        )

        if raster_layer is None:
            raise QgsProcessingException("Invalid input raster.")

        if raster_layer.bandCount() != 1:
            raise QgsProcessingException(
                "Input raster must be a single-band surface."
            )

        raster = parameters[self.INPUT_RASTER]

        # --------------------------------------------------
        # TEMP FILES
        # --------------------------------------------------
        temp_dir = QgsProcessingUtils.tempFolder()
        uid = uuid.uuid4().hex

        op_path = os.path.join(temp_dir, f"rrim_openness_positive_{uid}.tif")
        on_path = os.path.join(temp_dir, f"rrim_openness_negative_{uid}.tif")

        # --------------------------------------------------
        # STEP 1 — Positive Openness
        # --------------------------------------------------
        if feedback.isCanceled():
            return {}

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
            feedback=feedback
        )

        # --------------------------------------------------
        # STEP 2 — Negative Openness
        # --------------------------------------------------
        if feedback.isCanceled():
            return {}

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
            feedback=feedback
        )

        # --------------------------------------------------
        # STEP 3 — Differential Openness
        # --------------------------------------------------
        if feedback.isCanceled():
            return {}

        feedback.setCurrentStep(2)

        op_layer = QgsRasterLayer(op_path, "POS")
        on_layer = QgsRasterLayer(on_path, "NEG")

        if not op_layer.isValid() or not on_layer.isValid():
            raise QgsProcessingException(
                "Failed to load intermediate openness layers."
            )

        diff_result = processing.run(
            "native:rastercalc",
            {
                "LAYERS": [op_layer, on_layer],
                "EXPRESSION": '("POS@1" - "NEG@1") / 2',
                "OUTPUT": parameters[self.OUT_DIFF]
            },
            context=context,
            feedback=feedback
        )

        diff = diff_result["OUTPUT"]

        # --------------------------------------------------
        # STEP 4 — Slope
        # --------------------------------------------------
        if feedback.isCanceled():
            return {}

        feedback.setCurrentStep(3)
        slope_result = processing.run(
            "native:slope",
            {
                "INPUT": raster,
                "Z_FACTOR": 1,
                "OUTPUT": parameters[self.OUT_SLOPE]
            },
            context=context,
            feedback=feedback
        )

        slope = slope_result["OUTPUT"]

        # --------------------------------------------------
        # CLEANUP
        # --------------------------------------------------
        del op_layer
        del on_layer

        try:
            if os.path.exists(op_path):
                os.remove(op_path)
            if os.path.exists(on_path):
                os.remove(on_path)
        except Exception:
            pass

        return {
            self.OUT_SLOPE: slope,
            self.OUT_DIFF: diff
        }

    def createInstance(self):
        return RRIMAlgorithm()
