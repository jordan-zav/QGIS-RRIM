"""Pointwise raster operations which preserve the source pixel grid."""

from contextlib import contextmanager
import os
import posixpath
import uuid

import numpy as np


def validate_output_paths(input_paths, output_paths):
    """Reject source aliases and output collisions before any raster is created."""
    def same_path(first, second):
        if first.startswith("/vsi") or second.startswith("/vsi"):
            return posixpath.normpath(first) == posixpath.normpath(second)
        if os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second)):
            return True
        try:
            return os.path.samefile(first, second)
        except OSError:
            return False

    inputs = [os.fspath(path) for path in input_paths if path]
    outputs = []
    for path in output_paths:
        if not path:
            raise ValueError("An output raster path is required.")
        path = os.fspath(path)
        if any(same_path(path, other) for other in inputs + outputs):
            raise ValueError("Output rasters must differ from all inputs and from each other.")
        if path.startswith("/vsi"):
            from osgeo import gdal
            def exists(name):
                return gdal.VSIStatL(name) is not None
        else:
            exists = os.path.exists
        if any(exists(path + suffix) for suffix in (".msk", ".ovr", ".aux.xml")):
            raise ValueError("The output has existing raster sidecars. Choose a new output filename.")
        outputs.append(path)


def check_canceled(feedback):
    if feedback is not None and feedback.isCanceled():
        raise InterruptedError("RRIM processing was canceled.")


def check_raster_write(result, operation):
    # Older GDAL bindings return None on successful FlushCache; writes return 0.
    if result not in (None, 0):
        raise RuntimeError(f"Could not {operation}.")


@contextmanager
def atomic_raster_output(output_path, input_paths=(), feedback=None):
    """Stage a GeoTIFF, publishing by local atomic replace or GDAL VSI rename."""
    from osgeo import gdal

    output_path = os.fspath(output_path)
    validate_output_paths(input_paths, [output_path])
    virtual = output_path.startswith("/vsi")
    exists = (lambda path: gdal.VSIStatL(path) is not None) if virtual else os.path.exists
    temporary = output_path + "." + uuid.uuid4().hex + ".tmp.tif"
    try:
        check_canceled(feedback)
        yield temporary
        check_canceled(feedback)
        if virtual:
            if gdal.Rename(temporary, output_path) != 0:
                raise OSError("Could not publish the completed raster.")
        else:
            os.replace(temporary, output_path)
    finally:
        if exists(temporary):
            if virtual:
                gdal.Unlink(temporary)
            else:
                os.remove(temporary)


def require_north_up(path):
    from osgeo import gdal

    dataset = gdal.Open(path)
    if dataset is None:
        raise ValueError(f"Could not open raster: {path}")
    transform = dataset.GetGeoTransform()
    if not np.all(np.isfinite(transform)) or transform[2] != 0 or transform[4] != 0 or transform[1] <= 0 or transform[5] >= 0:
        raise ValueError("Slope and RGB require a north-up raster. Warp the DEM to a north-up grid first.")


def raster_math(source_path, output_path, second_path=None, limits=None, feedback=None):
    from osgeo import gdal

    check_canceled(feedback)
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
    datasets = [source, second] if second is not None else [source]
    inputs = [source_path, second_path]
    for dataset in datasets:
        inputs.extend(dataset.GetFileList() or [])
    with atomic_raster_output(output_path, inputs, feedback) as temporary:
        output = None
        try:
            output = gdal.GetDriverByName("GTiff").Create(
                temporary, source.RasterXSize, source.RasterYSize, 1, gdal.GDT_Float32,
                options=["COMPRESS=LZW", "TILED=YES"],
            )
            if output is None:
                raise RuntimeError(f"Could not create raster: {output_path}")
            check_raster_write(output.SetGeoTransform(source.GetGeoTransform()), "write raster geotransform")
            check_raster_write(output.SetProjection(source.GetProjection()), "write raster projection")
            check_raster_write(output.GetRasterBand(1).SetNoDataValue(float("nan")), "write raster NoData")
            total = ((source.RasterXSize + 511) // 512) * ((source.RasterYSize + 511) // 512)
            completed = 0
            for y in range(0, source.RasterYSize, 512):
                rows = min(512, source.RasterYSize - y)
                for x in range(0, source.RasterXSize, 512):
                    check_canceled(feedback)
                    cols = min(512, source.RasterXSize - x)
                    arrays = []
                    for dataset in datasets:
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
                    check_raster_write(output.GetRasterBand(1).WriteArray(result, x, y), "write raster block")
                    completed += 1
                    if feedback is not None:
                        feedback.setProgress(int(completed * 100 / total))
            check_raster_write(output.FlushCache(), "flush raster data")
        finally:
            output = None
    return output_path
