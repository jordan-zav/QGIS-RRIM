import os

import pytest

from rrim_raster import validate_output_paths


def test_hardlink_output_cannot_alias_the_source(tmp_path):
    source = tmp_path / "dem.tif"
    source.write_bytes(b"existing DEM")
    alias = tmp_path / "alias.tif"
    try:
        os.link(source, alias)
    except OSError:
        pytest.skip("Filesystem does not support hardlinks")
    with pytest.raises(ValueError, match="differ"):
        validate_output_paths([source], [alias])
    assert source.read_bytes() == b"existing DEM"


def test_auxiliary_masks_are_preserved_and_require_another_output(tmp_path):
    output = tmp_path / "existing.tif"
    mask = tmp_path / "existing.tif.msk"
    output.write_bytes(b"existing raster")
    mask.write_bytes(b"existing mask")
    with pytest.raises(ValueError, match="sidecars"):
        validate_output_paths([], [output])
    assert output.read_bytes() == b"existing raster"
    assert mask.read_bytes() == b"existing mask"


def test_distinct_destinations_are_accepted(tmp_path):
    validate_output_paths([tmp_path / "dem.tif"], [tmp_path / "slope.tif", tmp_path / "openness.tif"])
