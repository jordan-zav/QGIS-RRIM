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

import numpy as np
from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingParameterRasterLayer, QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
)
from qgis.PyQt.QtGui import QIcon
from osgeo import gdal

from .rrim_raster import require_north_up, atomic_raster_output, check_canceled, check_raster_write


def _compose_rgb(slope, openness, slope_max, do_min, do_max):
    """Interpolate the RRIM ramps and multiply colors without resampling."""
    stops = np.array([0, .13, .26, .39, .52, .65, .78, .90, 1]) * slope_max
    colors = np.array([
        [255,245,240], [254,224,210], [252,187,161], [252,146,114],
        [251,106,74], [239,59,44], [203,24,29], [165,15,21], [103,0,13],
    ])
    gray = np.clip((openness - do_min) / (do_max - do_min), 0, 1)
    return np.stack([
        np.rint(np.interp(slope, stops, colors[:, channel]) * gray).astype(np.uint8)
        for channel in range(3)
    ])


def export_rrim_geotiff(slope_layer, do_layer, output_path, slope_max=90.0, do_min=-50.0, do_max=50.0, feedback=None):
    check_canceled(feedback)
    if any(layer is None or not layer.isValid() or layer.bandCount() != 1
           for layer in (slope_layer, do_layer)):
        raise QgsProcessingException("RRIM requires two valid single-band rasters.")
    if not np.all(np.isfinite([slope_max, do_min, do_max])) or slope_max <= 0 or do_min >= do_max:
        raise QgsProcessingException("RRIM display ranges are invalid.")
    if not do_layer.crs().isValid() or slope_layer.crs() != do_layer.crs():
        raise QgsProcessingException("Inputs must have the same valid CRS.")
    try:
        require_north_up(slope_layer.source())
        require_north_up(do_layer.source())
    except ValueError as error:
        raise QgsProcessingException(str(error)) from error

    sources = [gdal.Open(layer.source()) for layer in (slope_layer, do_layer)]
    reference = sources[1]
    width, height = reference.RasterXSize, reference.RasterYSize
    transform = reference.GetGeoTransform()
    if any((ds.RasterXSize, ds.RasterYSize) != (width, height)
           or ds.GetGeoTransform() != transform for ds in sources):
        raise QgsProcessingException("Inputs must have identical pixel grids.")
    input_paths = [layer.source() for layer in (slope_layer, do_layer)]
    for source in sources:
        input_paths.extend(source.GetFileList() or [])
    with atomic_raster_output(output_path, input_paths, feedback) as temporary:
        output = mask_band = None
        try:
            output = gdal.GetDriverByName("GTiff").Create(
                temporary, width, height, 3, gdal.GDT_Byte,
                options=["COMPRESS=LZW", "TILED=YES", "PHOTOMETRIC=RGB"],
            )
            if output is None:
                raise QgsProcessingException("Could not create RGB GeoTIFF.")
            check_raster_write(output.SetGeoTransform(transform), "write RGB geotransform")
            check_raster_write(output.SetProjection(do_layer.crs().toWkt()), "write RGB projection")
            previous = gdal.GetThreadLocalConfigOption("GDAL_TIFF_INTERNAL_MASK")
            try:
                gdal.SetThreadLocalConfigOption("GDAL_TIFF_INTERNAL_MASK", "YES")
                if output.CreateMaskBand(gdal.GMF_PER_DATASET) != 0:
                    raise QgsProcessingException("Could not create RGB validity mask.")
            finally:
                gdal.SetThreadLocalConfigOption("GDAL_TIFF_INTERNAL_MASK", previous)
            mask_band = output.GetRasterBand(1).GetMaskBand()
            total = ((width + 511) // 512) * ((height + 511) // 512)
            completed = 0
            for y in range(0, height, 512):
                for x in range(0, width, 512):
                    check_canceled(feedback)
                    cols, rows = min(512, width-x), min(512, height-y)
                    valid = np.ones((rows, cols), dtype=bool)
                    arrays = []
                    for source in sources:
                        band = source.GetRasterBand(1)
                        values = band.ReadAsArray(x, y, cols, rows).astype(np.float64)
                        valid &= np.isfinite(values)
                        valid &= band.GetMaskBand().ReadAsArray(x, y, cols, rows) != 0
                        nodata = band.GetNoDataValue()
                        if nodata is not None:
                            valid &= values != nodata
                        arrays.append(values)
                    rgb = _compose_rgb(*(np.where(valid, values, 0) for values in arrays), slope_max, do_min, do_max)
                    rgb[:, ~valid] = 0
                    for channel in range(3):
                        check_raster_write(output.GetRasterBand(channel+1).WriteArray(rgb[channel], x, y), "write RGB block")
                    check_raster_write(mask_band.WriteArray(valid.astype(np.uint8) * 255, x, y), "write RGB validity mask")
                    completed += 1
                    if feedback is not None:
                        feedback.setProgress(int(completed * 100 / total))
            check_raster_write(output.FlushCache(), "flush RGB data")
        finally:
            mask_band = None
            output = None
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
            "Requires two single-band, north-up rasters with identical pixel grids and "
            "the same valid CRS. Pixels are composed without resampling; an internal mask "
            "preserves NoData and valid black pixels remain valid.<br><br>"
            "The output must differ from both inputs and their VRT dependencies. "
            "Choose a new filename when a destination has external masks, overviews or PAM sidecars. "
            "Cancellation or a failed write preserves the previous destination.<br><br>"
            "Workflow follows <a href='https://www.researchgate.net/publication/237517308_Red_relief_image_map_New_visualization_method_for_three_dimensional_data'>Chiba et al. (2008)</a>.<br><br>"
            "-----------------------------------------------------------<br>"
            "&copy; 2025 <a href='https://linkedin.com/in/jordan-zav'><b>Zavaleta, J.</b></a><br>"
            "<i>Geological Engineering Undergraduate Student at UNI</i><br>"
            "Released under the GNU GPLv3 License"
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

        try:
            export_rrim_geotiff(slope, do, output_path, slope_max=slope_max,
                               do_min=do_min, do_max=do_max, feedback=feedback)
        except (ValueError, InterruptedError, OSError, RuntimeError) as error:
            raise QgsProcessingException(str(error)) from error

        return {self.OUTPUT: output_path}

    def createInstance(self):
        return RRIMRGBComposer()
