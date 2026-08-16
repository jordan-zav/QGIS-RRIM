"""
Internal openness calculation utilities for QGIS-RRIM.
"""

import math
import os

import numpy as np


def _direction_offsets(radius, num_directions, pixel_width, pixel_height):
    if radius < 1:
        raise ValueError("radius must be at least 1 pixel")
    if num_directions < 1:
        raise ValueError("num_directions must be positive")
    if pixel_width <= 0 or pixel_height <= 0:
        raise ValueError("pixel dimensions must be positive")

    radial_samples = [1.0 + sample / 3.0 for sample in range((radius - 1) * 3 + 1)]

    for index in range(num_directions):
        angle = (2.0 * math.pi * index) / num_directions
        offsets = {}

        for radial_distance in radial_samples:
            dx = int(round(math.cos(angle) * radial_distance))
            dy = int(round(math.sin(angle) * radial_distance))
            if dx == 0 and dy == 0:
                continue

            distance = math.hypot(dx * pixel_width, dy * pixel_height)
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


def _calculate_openness(dem_array, radius, num_directions, pixel_width, pixel_height):
    directions = list(_direction_offsets(radius, num_directions, pixel_width, pixel_height))
    openness_sum = np.zeros(dem_array.shape, dtype=np.float32)
    minimum_horizon = np.float32(np.degrees(np.arctan(-1000.0)))
    center_is_valid = ~np.isnan(dem_array)

    for offsets in directions:
        max_horizon = np.full(dem_array.shape, minimum_horizon, dtype=np.float32)

        for dy, dx, distance in offsets:
            shifted = _shift_array(dem_array, dy, dx)
            horizon_angle = np.degrees(np.arctan((shifted - dem_array) / distance))
            max_horizon = np.fmax(max_horizon, horizon_angle)

        openness_sum += 90.0 - max_horizon

    openness = (openness_sum / len(directions)).astype(np.float32)
    openness[~center_is_valid] = np.nan
    return openness


def compute_openness_raster(input_path, output_path, radius=10, num_directions=16, invert=False, feedback=None, block_size=512):
    from osgeo import gdal

    dataset = gdal.Open(input_path, gdal.GA_ReadOnly)
    if dataset is None:
        raise RuntimeError(f"Could not open DEM: {input_path}")

    band = dataset.GetRasterBand(1)
    nodata_value = band.GetNoDataValue()

    geotransform = dataset.GetGeoTransform()
    if geotransform:
        pixel_width = math.hypot(geotransform[1], geotransform[2])
        pixel_height = math.hypot(geotransform[4], geotransform[5])
    else:
        pixel_width = 1.0
        pixel_height = 1.0

    driver = gdal.GetDriverByName("GTiff")
    output = driver.Create(
        output_path,
        dataset.RasterXSize,
        dataset.RasterYSize,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=LZW", "TILED=YES"],
    )
    if output is None:
        raise RuntimeError(f"Could not create openness raster: {output_path}")

    output.SetGeoTransform(dataset.GetGeoTransform())
    output.SetProjection(dataset.GetProjection())
    out_band = output.GetRasterBand(1)
    out_band.SetNoDataValue(np.nan)

    x_size = dataset.RasterXSize
    y_size = dataset.RasterYSize
    total_blocks = max(math.ceil(x_size / block_size) * math.ceil(y_size / block_size), 1)
    processed_blocks = 0
    canceled = False

    for yoff in range(0, y_size, block_size):
        if feedback is not None and feedback.isCanceled():
            canceled = True
            break

        rows = min(block_size, y_size - yoff)
        for xoff in range(0, x_size, block_size):
            if feedback is not None and feedback.isCanceled():
                canceled = True
                break

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

            pad_top = max(0, radius - yoff)
            pad_left = max(0, radius - xoff)
            pad_bottom = max(0, yoff + rows + radius - y_size)
            pad_right = max(0, xoff + cols + radius - x_size)
            if any((pad_top, pad_bottom, pad_left, pad_right)):
                array = np.pad(
                    array,
                    ((pad_top, pad_bottom), (pad_left, pad_right)),
                    mode="reflect",
                )

            if invert:
                array *= -1.0

            openness = _calculate_openness(
                array,
                radius=radius,
                num_directions=num_directions,
                pixel_width=pixel_width,
                pixel_height=pixel_height,
            )

            crop_y = yoff - read_yoff + pad_top
            crop_x = xoff - read_xoff + pad_left
            out_band.WriteArray(openness[crop_y:crop_y + rows, crop_x:crop_x + cols], xoff, yoff)

            processed_blocks += 1
            if feedback is not None:
                feedback.setProgress(int(processed_blocks * 100 / total_blocks))

    out_band.FlushCache()

    output.FlushCache()
    output = None
    dataset = None

    if canceled:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        finally:
            raise InterruptedError("Openness calculation was canceled.")

    return output_path
