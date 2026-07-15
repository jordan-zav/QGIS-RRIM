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

import os
import uuid

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingUtils,
    QgsProject,
    QgsPrintLayout,
    QgsLayoutItemMap,
    QgsLayoutExporter,
    QgsLayoutSize,
    QgsUnitTypes,
    QgsRasterShader,
    QgsColorRampShader,
    QgsSingleBandPseudoColorRenderer,
    QgsRasterLayer
)

from qgis.PyQt.QtGui import QIcon
from PyQt5.QtGui import QColor, QPainter
from osgeo import gdal, osr


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


def _apply_rrim_style(slope_layer, do_layer, slope_max, do_min, do_max):
    slope_items = [
        (0.0, "#fff5f0", "0.0000"),
        (slope_max * 0.13, "#fee0d2", f"{slope_max * 0.13:.4f}"),
        (slope_max * 0.26, "#fcbba1", f"{slope_max * 0.26:.4f}"),
        (slope_max * 0.39, "#fc9272", f"{slope_max * 0.39:.4f}"),
        (slope_max * 0.52, "#fb6a4a", f"{slope_max * 0.52:.4f}"),
        (slope_max * 0.65, "#ef3b2c", f"{slope_max * 0.65:.4f}"),
        (slope_max * 0.78, "#cb181d", f"{slope_max * 0.78:.4f}"),
        (slope_max * 0.90, "#a50f15", f"{slope_max * 0.90:.4f}"),
        (slope_max, "#67000d", f"{slope_max:.4f}"),
    ]
    do_items = [
        (do_min, "#000000", f"{do_min:g}"),
        (do_max, "#ffffff", f"{do_max:g}"),
    ]

    do_layer.setRenderer(_build_renderer(do_layer, do_items, minimum=do_min, maximum=do_max))
    do_layer.triggerRepaint()

    slope_layer.setRenderer(_build_renderer(slope_layer, slope_items, minimum=0.0, maximum=slope_max))
    slope_layer.setBlendMode(QPainter.CompositionMode_Multiply)
    slope_layer.triggerRepaint()


def export_rrim_geotiff(slope_layer, do_layer, output_path, slope_max=90.0, do_min=-50.0, do_max=50.0):
    if slope_layer is None or not slope_layer.isValid():
        raise QgsProcessingException("Invalid slope layer for RRIM export.")

    if do_layer is None or not do_layer.isValid():
        raise QgsProcessingException("Invalid differential openness layer for RRIM export.")

    temp_dir = QgsProcessingUtils.tempFolder()
    uid = uuid.uuid4().hex

    temp_png = os.path.join(temp_dir, f"rrim_rgb_{uid}.png")

    width = do_layer.width()
    height = do_layer.height()
    extent = do_layer.extent()

    if width <= 0 or height <= 0:
        raise QgsProcessingException("Invalid raster dimensions for RRIM RGB export.")

    slope_renderer = slope_layer.renderer().clone() if slope_layer.renderer() else None
    do_renderer = do_layer.renderer().clone() if do_layer.renderer() else None
    slope_blend_mode = slope_layer.blendMode()

    try:
        _apply_rrim_style(slope_layer, do_layer, slope_max, do_min, do_max)

        layout = QgsPrintLayout(QgsProject.instance())
        layout.initializeDefaults()
        layout.setName("RRIM_RGB_Composer")

        page = layout.pageCollection().page(0)
        page.attemptResize(QgsLayoutSize(width, height, QgsUnitTypes.LayoutPixels))

        map_item = QgsLayoutItemMap(layout)
        map_item.attemptResize(QgsLayoutSize(width, height, QgsUnitTypes.LayoutPixels))
        map_item.setPos(0, 0)
        map_item.setExtent(extent)
        map_item.setLayers([slope_layer, do_layer])
        map_item.setFrameEnabled(False)
        map_item.setBackgroundColor(QColor("white"))
        layout.addLayoutItem(map_item)

        exporter = QgsLayoutExporter(layout)
        image_settings = QgsLayoutExporter.ImageExportSettings()
        image_settings.cropToContents = False
        result = exporter.exportToImage(temp_png, image_settings)
        if result != QgsLayoutExporter.Success:
            raise QgsProcessingException("Failed to render RRIM RGB image.")

        ds_src = gdal.Open(temp_png)
        if ds_src is None:
            raise QgsProcessingException("Failed to open temporary RRIM RGB image.")

        driver = gdal.GetDriverByName("GTiff")
        ds_dst = driver.CreateCopy(output_path, ds_src, 0, options=["COMPRESS=LZW"])
        if ds_dst is None:
            ds_src = None
            raise QgsProcessingException("Failed to create RRIM RGB GeoTIFF.")

        px_w = extent.width() / width
        px_h = extent.height() / height

        ds_dst.SetGeoTransform([
            extent.xMinimum(), px_w, 0,
            extent.yMaximum(), 0, -px_h
        ])

        projection_wkt = None
        source_ds = gdal.Open(do_layer.source())
        if source_ds is not None:
            projection_wkt = source_ds.GetProjection()
            source_ds = None

        if not projection_wkt:
            projection_wkt = do_layer.crs().toWkt()

        if projection_wkt:
            ds_dst.SetProjection(projection_wkt)

        ds_src = None
        ds_dst = None
    finally:
        if slope_renderer is not None:
            slope_layer.setRenderer(slope_renderer)
        if do_renderer is not None:
            do_layer.setRenderer(do_renderer)
        slope_layer.setBlendMode(slope_blend_mode)
        slope_layer.triggerRepaint()
        do_layer.triggerRepaint()

        try:
            if os.path.exists(temp_png):
                os.remove(temp_png)
        except Exception:
            pass

    return output_path


class RRIMRGBComposer(QgsProcessingAlgorithm):

    INPUT_SLOPE = "INPUT_SLOPE"
    INPUT_DO = "INPUT_DO"
    SLOPE_MAX = "SLOPE_MAX"
    DO_MIN = "DO_MIN"
    DO_MAX = "DO_MAX"
    OUTPUT = "OUTPUT"

    def name(self):
        return "rrim_rgb_composer"

    def displayName(self):
        return "RRIM RGB Composer"

    def group(self):
        return "QGIS-RRIM"

    def groupId(self):
        return "qgis_rrim"

    def shortHelpString(self):
        return (
            "Generates a georeferenced RRIM RGB GeoTIFF from existing "
            "Slope and Differential Openness rasters.<br><br>"
            "The composer renders a single packed RGB raster using:<br>"
            "&bull; Slope as the red multiply layer<br>"
            "&bull; Differential Openness as the grayscale base layer<br><br>"
            "User-defined display ranges are supported.<br><br>"
            "Workflow follows <a href='https://www.researchgate.net/publication/237517308_Red_relief_image_map_New_visualization_method_for_three_dimensional_data'>Chiba et al. (2008)</a>.<br><br>"
            "-----------------------------------------------------------<br>"
            "&copy; 2025 <a href='https://linkedin.com/in/jordan-zav'><b>Zavaleta, J.</b></a><br>"
            "<i>Geological Engineering Undergraduate Student at UNI</i><br>"
            "Released under the MIT License"
        )

    def icon(self):
        return QIcon(
            os.path.join(os.path.dirname(__file__), "icon.png")
        )

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_SLOPE,
                "Slope raster"
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_DO,
                "Differential Openness raster"
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SLOPE_MAX,
                "Slope maximum (degrees)",
                QgsProcessingParameterNumber.Double,
                defaultValue=90
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.DO_MIN,
                "Differential Openness minimum",
                QgsProcessingParameterNumber.Double,
                defaultValue=-50
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.DO_MAX,
                "Differential Openness maximum",
                QgsProcessingParameterNumber.Double,
                defaultValue=50
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                "RRIM RGB GeoTIFF"
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        slope = self.parameterAsRasterLayer(parameters, self.INPUT_SLOPE, context)
        do = self.parameterAsRasterLayer(parameters, self.INPUT_DO, context)
        slope_max = self.parameterAsDouble(parameters, self.SLOPE_MAX, context)
        do_min = self.parameterAsDouble(parameters, self.DO_MIN, context)
        do_max = self.parameterAsDouble(parameters, self.DO_MAX, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        export_rrim_geotiff(
            slope,
            do,
            output_path,
            slope_max=slope_max,
            do_min=do_min,
            do_max=do_max,
        )

        return {self.OUTPUT: output_path}

    def createInstance(self):
        return RRIMRGBComposer()
