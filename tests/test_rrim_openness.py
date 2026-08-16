import numpy as np

from rrim_openness import _calculate_openness, _direction_offsets


def _rvt_reference_openness(dem, radius=10, num_directions=16):
    height = np.pad(dem.astype(np.float32), radius, mode="reflect")
    openness_sum = height * 0
    angles = (2 * np.pi / num_directions) * np.arange(num_directions)
    radii = np.arange((radius - 1) * 3 + 1) / 3 + 1

    for angle in angles:
        x_offsets = np.round(np.cos(angle) * radii).astype(int)
        y_offsets = np.round(np.sin(angle) * radii).astype(int)
        offsets = np.unique(np.column_stack([x_offsets, y_offsets]), axis=0)
        distances = np.sqrt(np.sum(offsets**2, axis=1))
        offsets = offsets[np.argsort(distances)]

        max_slope = np.zeros(height.shape, dtype=np.float32) - 1000
        for dx, dy in offsets:
            distance = np.hypot(dx, dy)
            shifted = np.roll(height, (dx, dy), axis=(0, 1))
            max_slope = np.fmax(max_slope, (shifted - height) / distance)

        openness_sum += np.arctan(max_slope)

    return np.rad2deg(
        np.pi / 2
        - openness_sum[radius:-radius, radius:-radius] / num_directions
    )


def test_flat_surface_has_ninety_degree_openness():
    dem = np.zeros((32, 32), dtype=np.float32)

    openness = _calculate_openness(dem, 10, 16, 1.0, 1.0)

    np.testing.assert_allclose(openness[10:-10, 10:-10], 90.0, atol=1e-6)


def test_uniform_plane_has_zero_differential_openness_away_from_edges():
    y, x = np.mgrid[:48, :48]
    dem = (0.25 * x + 0.1 * y).astype(np.float32)

    positive = _calculate_openness(dem, 10, 16, 1.0, 1.0)
    negative = _calculate_openness(-dem, 10, 16, 1.0, 1.0)

    np.testing.assert_allclose(
        ((positive - negative) / 2)[10:-10, 10:-10],
        0.0,
        atol=2e-5,
    )


def test_sampling_matches_rvt_reference_away_from_edges():
    rng = np.random.default_rng(42)
    dem = rng.normal(size=(64, 64)).astype(np.float32)

    actual = _calculate_openness(dem, 10, 16, 1.0, 1.0)
    expected = _rvt_reference_openness(dem)

    np.testing.assert_allclose(
        actual[10:-10, 10:-10],
        expected[10:-10, 10:-10],
        atol=3e-5,
    )


def test_fractional_radial_sampling_includes_diagonal_transition_cells():
    directions = list(_direction_offsets(10, 16, 1.0, 1.0))
    first_oblique_direction = {(dy, dx) for dy, dx, _ in directions[1]}

    assert (1, 1) in first_oblique_direction
