"""
Internal openness calculation utilities for QGIS-RRIM.
"""

import math
import operator

import numpy as np

if __package__:
    from .rrim_raster import atomic_raster_output, check_canceled, check_raster_write
else:
    from rrim_raster import atomic_raster_output, check_canceled, check_raster_write


def _direction_offsets(radius, num_directions, pixel_width, pixel_height, geotransform=None):
    try:
        radius = operator.index(radius)
        num_directions = operator.index(num_directions)
    except TypeError as error:
        raise ValueError("radius and num_directions must be integers") from error
    if radius < 1:
        raise ValueError("radius must be at least 1 pixel")
    if num_directions < 1:
        raise ValueError("num_directions must be positive")
    if not all(math.isfinite(value) and value > 0 for value in (pixel_width, pixel_height)):
        raise ValueError("pixel dimensions must be positive")
    if geotransform is not None and (
        len(geotransform) != 6 or not all(math.isfinite(value) for value in geotransform)
        or geotransform[1] * geotransform[5] - geotransform[2] * geotransform[4] == 0
    ):
        raise ValueError("Raster geotransform must be finite and invertible")

    radial_samples = [1.0 + sample / 3.0 for sample in range((radius - 1) * 3 + 1)]

    for index in range(num_directions):
        angle = (2.0 * math.pi * index) / num_directions
        offsets = {}

        for radial_distance in radial_samples:
            dx = int(round(math.cos(angle) * radial_distance))
            dy = int(round(math.sin(angle) * radial_distance))
            if dx == 0 and dy == 0:
                continue

            distance = (math.hypot(
                dx * geotransform[1] + dy * geotransform[2],
                dx * geotransform[4] + dy * geotransform[5],
            ) if geotransform is not None else
                math.hypot(dx * pixel_width, dy * pixel_height))
            if distance == 0:
                continue

            offsets[(dy, dx)] = distance

        if offsets:
            yield sorted(
                ((dy, dx, distance) for (dy, dx), distance in offsets.items()),
                key=lambda item: item[2],
            )


def _shift_array(array, dy, dx):
    shifted = np.full(array.shape, np.nan, dtype=np.float32)

    src_row_start = max(0, -dy)
    src_row_end = array.shape[0] - max(0, dy)
    src_col_start = max(0, -dx)
    src_col_end = array.shape[1] - max(0, dx)

    if src_row_start >= src_row_end or src_col_start >= src_col_end:
        return shifted

    dst_row_start = max(0, dy)
    dst_row_end = dst_row_start + (src_row_end - src_row_start)
    dst_col_start = max(0, dx)
    dst_col_end = dst_col_start + (src_col_end - src_col_start)

    shifted[dst_row_start:dst_row_end, dst_col_start:dst_col_end] = array[src_row_start:src_row_end, src_col_start:src_col_end]
    return shifted


def _calculate_openness(dem_array, radius, num_directions, pixel_width, pixel_height, geotransform=None):
    dem_array = np.where(np.isfinite(dem_array), dem_array, np.nan)
    directions = list(_direction_offsets(radius, num_directions, pixel_width, pixel_height, geotransform))
    openness_sum = np.zeros(dem_array.shape, dtype=np.float32)
    valid_directions = np.zeros(dem_array.shape, dtype=np.int32)
    center_is_valid = ~np.isnan(dem_array)

    for offsets in directions:
        max_horizon = np.full(dem_array.shape, np.nan, dtype=np.float32)

        for dy, dx, distance in offsets:
            shifted = _shift_array(dem_array, dy, dx)
            horizon_angle = np.degrees(np.arctan((shifted - dem_array) / distance))
            max_horizon = np.fmax(max_horizon, horizon_angle)

        valid = np.isfinite(max_horizon)
        openness_sum[valid] += 90.0 - max_horizon[valid]
        valid_directions += valid

    openness = np.full(dem_array.shape, np.nan, dtype=np.float32)
    np.divide(openness_sum, valid_directions, out=openness, where=valid_directions > 0)
    openness[~center_is_valid] = np.nan
    return openness


def compute_openness_raster(input_path, output_path, radius=10, num_directions=16, invert=False, feedback=None, block_size=512):
    from osgeo import gdal

    check_canceled(feedback)
    try:
        radius = operator.index(radius)
        num_directions = operator.index(num_directions)
        block_size = operator.index(block_size)
    except TypeError as error:
        raise ValueError("Sampling and block sizes must be integers") from error
    if radius < 1 or num_directions < 1 or block_size < 1:
        raise ValueError("Sampling and block sizes must be positive")
    dataset = gdal.Open(input_path, gdal.GA_ReadOnly)
    if dataset is None:
        raise RuntimeError(f"Could not open DEM: {input_path}")

    band = dataset.GetRasterBand(1)
    nodata_value = band.GetNoDataValue()

    geotransform = dataset.GetGeoTransform()
    if geotransform:
        pixel_width = math.hypot(geotransform[1], geotransform[4])
        pixel_height = math.hypot(geotransform[2], geotransform[5])
    else:
        pixel_width = 1.0
        pixel_height = 1.0

    x_size = dataset.RasterXSize
    y_size = dataset.RasterYSize
    total_blocks = max(math.ceil(x_size / block_size) * math.ceil(y_size / block_size), 1)
    processed_blocks = 0
    inputs = [input_path, *(dataset.GetFileList() or [])]
    with atomic_raster_output(output_path, inputs, feedback) as temporary:
        output = out_band = None
        try:
            output = gdal.GetDriverByName("GTiff").Create(
                temporary, x_size, y_size, 1, gdal.GDT_Float32,
                options=["COMPRESS=LZW", "TILED=YES"],
            )
            if output is None:
                raise RuntimeError(f"Could not create openness raster: {output_path}")
            check_raster_write(output.SetGeoTransform(geotransform), "write openness geotransform")
            check_raster_write(output.SetProjection(dataset.GetProjection()), "write openness projection")
            out_band = output.GetRasterBand(1)
            check_raster_write(out_band.SetNoDataValue(np.nan), "write openness NoData")
            for yoff in range(0, y_size, block_size):
                rows = min(block_size, y_size - yoff)
                for xoff in range(0, x_size, block_size):
                    check_canceled(feedback)
                    cols = min(block_size, x_size - xoff)
                    read_xoff = max(0, xoff - radius)
                    read_yoff = max(0, yoff - radius)
                    read_xend = min(x_size, xoff + cols + radius)
                    read_yend = min(y_size, yoff + rows + radius)
                    read_cols = read_xend - read_xoff
                    read_rows = read_yend - read_yoff
                    array = band.ReadAsArray(read_xoff, read_yoff, read_cols, read_rows).astype(np.float32)
                    if nodata_value is not None:
                        array[array == nodata_value] = np.nan
                    valid_mask = band.GetMaskBand().ReadAsArray(read_xoff, read_yoff, read_cols, read_rows)
                    array[(valid_mask == 0) | ~np.isfinite(array)] = np.nan
                    pad_top = max(0, radius - yoff)
                    pad_left = max(0, radius - xoff)
                    pad_bottom = max(0, yoff + rows + radius - y_size)
                    pad_right = max(0, xoff + cols + radius - x_size)
                    if any((pad_top, pad_bottom, pad_left, pad_right)):
                        array = np.pad(array, ((pad_top, pad_bottom), (pad_left, pad_right)), mode="reflect")
                    if invert:
                        array *= -1.0
                    openness = _calculate_openness(array, radius, num_directions, pixel_width, pixel_height, geotransform)
                    crop_y = yoff - read_yoff + pad_top
                    crop_x = xoff - read_xoff + pad_left
                    check_raster_write(out_band.WriteArray(openness[crop_y:crop_y + rows, crop_x:crop_x + cols], xoff, yoff),
                                       "write openness block")
                    processed_blocks += 1
                    if feedback is not None:
                        feedback.setProgress(int(processed_blocks * 100 / total_blocks))
            check_raster_write(out_band.FlushCache(), "flush openness band")
            check_raster_write(output.FlushCache(), "flush openness data")
        finally:
            out_band = None
            output = None

    return output_path
