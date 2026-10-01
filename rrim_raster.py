"""Pointwise raster operations which preserve the source pixel grid."""

import numpy as np


def require_north_up(path):
    from osgeo import gdal

    dataset = gdal.Open(path)
    if dataset is None:
        raise ValueError(f"Could not open raster: {path}")
    transform = dataset.GetGeoTransform()
    if transform[2] != 0 or transform[4] != 0 or transform[1] <= 0 or transform[5] >= 0:
        raise ValueError("Slope and RGB require a north-up raster. Warp the DEM to a north-up grid first.")


def raster_math(source_path, output_path, second_path=None, limits=None, feedback=None):
    from osgeo import gdal

    source = gdal.Open(source_path)
    second = gdal.Open(second_path) if second_path else None
    if source is None or (second_path and second is None):
        raise ValueError("Could not open raster calculation inputs.")
    if second is not None and (
        source.RasterXSize != second.RasterXSize
        or source.RasterYSize != second.RasterYSize
        or source.GetGeoTransform() != second.GetGeoTransform()
        or source.GetProjection() != second.GetProjection()
    ):
        raise ValueError("Raster calculation inputs must have identical grids and CRS.")
    output = gdal.GetDriverByName("GTiff").Create(
        output_path, source.RasterXSize, source.RasterYSize, 1, gdal.GDT_Float32,
        options=["COMPRESS=LZW", "TILED=YES"],
    )
    if output is None:
        raise RuntimeError(f"Could not create raster: {output_path}")
    try:
        output.SetGeoTransform(source.GetGeoTransform())
        output.SetProjection(source.GetProjection())
        output.GetRasterBand(1).SetNoDataValue(float("nan"))
        for y in range(0, source.RasterYSize, 512):
            if feedback is not None and feedback.isCanceled():
                raise InterruptedError("Raster calculation was canceled.")
            rows = min(512, source.RasterYSize - y)
            for x in range(0, source.RasterXSize, 512):
                cols = min(512, source.RasterXSize - x)
                arrays = []
                for dataset in ([source, second] if second is not None else [source]):
                    band = dataset.GetRasterBand(1)
                    array = band.ReadAsArray(x, y, cols, rows).astype(np.float32)
                    nodata = band.GetNoDataValue()
                    mask = band.GetMaskBand().ReadAsArray(x, y, cols, rows) == 0
                    if nodata is not None:
                        mask |= array == nodata
                    array[mask | ~np.isfinite(array)] = np.nan
                    arrays.append(array)
                result = (arrays[0] - arrays[1]) / 2 if second is not None else arrays[0]
                if limits is not None:
                    result = np.clip(result, *limits)
                output.GetRasterBand(1).WriteArray(result, x, y)
        output.FlushCache()
    finally:
        output = None
        source = None
        second = None
    return output_path
