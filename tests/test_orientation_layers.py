from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from kbench.geometry.raster import Panel
from kbench.metrics import orientation as orient
from kbench.metrics.layers import LAYER_FIELDS, boundary_distances, layer_metrics

PANEL = Panel(100, 80, 0.05, 0.05)


def l_mask() -> np.ndarray:
    mask = np.zeros((40, 30), dtype=bool)
    mask[5:35, 5:11] = True  # Long vertical arm.
    mask[29:35, 5:20] = True  # Short foot to the right.
    return mask


# Orientation ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", orient.ORIENTATIONS)
def test_inverse_undoes_and_shape_matches(name: str) -> None:
    image = np.arange(35.0).reshape(5, 7)
    transformed = orient.apply(image, name)
    assert transformed.shape == orient.transformed_shape(image.shape, name)
    assert np.array_equal(orient.apply(transformed, orient.inverse(name)), image)


@pytest.mark.parametrize("name", orient.ORIENTATIONS)
def test_map_point_follows_the_pixels(name: str) -> None:
    rng = np.random.default_rng(3)
    image = rng.uniform(0.0, 1.0, (6, 9))
    transformed = orient.apply(image, name)

    def centroid(a: np.ndarray) -> tuple[float, float]:
        rows = np.arange(a.shape[0]) + 0.5
        cols = np.arange(a.shape[1]) + 0.5
        return float(a.sum(axis=1) @ rows / a.sum()), float(a.sum(axis=0) @ cols / a.sum())

    mapped = orient.map_point(*centroid(image), image.shape, name)
    assert mapped == pytest.approx(centroid(transformed), abs=1e-12)


@pytest.mark.parametrize("name", orient.ORIENTATIONS)
def test_estimate_finds_each_orientation_of_a_chiral_shape(name: str) -> None:
    reference = np.zeros((60, 60), dtype=bool)
    reference[10:50, 15:45] = l_mask()
    stored = np.zeros((80, 70), dtype=bool)
    turned = orient.apply(l_mask(), name)
    stored[20 : 20 + turned.shape[0], 25 : 25 + turned.shape[1]] = turned
    result = orient.estimate(reference, stored)
    assert result["best"] == name
    assert result["iou"] == pytest.approx(1.0)
    assert not result["ambiguous"]


def test_estimate_reports_symmetric_shapes_as_ambiguous() -> None:
    square = np.zeros((30, 30), dtype=bool)
    square[5:25, 5:25] = True
    assert orient.estimate(square, square)["ambiguous"]


def test_aligned_iou_of_empty_masks_is_zero() -> None:
    assert orient.aligned_iou(np.zeros((3, 3), dtype=bool), l_mask()) == 0.0


# Layer metrics ----------------------------------------------------------------------------


def disc(shape: tuple[int, int], centre: tuple[float, float], radius: float) -> np.ndarray:
    rows, cols = np.indices(shape) + 0.5
    return ((rows - centre[0]) ** 2 + (cols - centre[1]) ** 2 <= radius**2).astype(np.float64)


def test_identical_layers_have_no_error() -> None:
    reference = disc((60, 60), (30, 30), 20)
    result = layer_metrics(reference.copy(), reference, PANEL)
    assert set(result) == set(LAYER_FIELDS)
    assert result["area_error_mm2"] == 0.0
    assert result["iou"] == 1.0
    assert result["xor_area_mm2"] == 0.0
    assert result["boundary_max_mm"] == 0.0
    assert result["centroid_dx_mm"] == 0.0
    assert result["width_error_mm"] == 0.0
    assert result["edge_coverage_mae"] is None  # Binary images have no partial pixels.


def test_shift_moves_the_centroid_but_not_the_size() -> None:
    reference = disc((60, 60), (30, 30), 15)
    measured = np.roll(reference, (-3, 2), axis=(0, 1))  # Three rows up (+Y), two columns right.
    result = layer_metrics(measured, reference, PANEL)
    assert result["centroid_dx_mm"] == pytest.approx(0.10)
    assert result["centroid_dy_mm"] == pytest.approx(0.15)
    assert result["width_error_mm"] == 0.0
    assert result["depth_error_mm"] == 0.0
    assert result["area_error_mm2"] == 0.0
    assert result["iou"] < 1.0


def test_one_pixel_dilation() -> None:
    reference = np.zeros((60, 60))
    reference[20:40, 15:45] = 1.0
    measured = ndimage.binary_dilation(reference > 0.5).astype(np.float64)
    result = layer_metrics(measured, reference, PANEL)
    # The cross-shaped dilation moves every edge one pixel out and leaves the corners notched.
    assert result["boundary_max_mm"] == pytest.approx(0.05)
    assert result["boundary_mean_mm"] == pytest.approx(0.05)
    assert result["width_error_mm"] == pytest.approx(0.10)
    assert result["area_error_mm2"] == pytest.approx((2 * 20 + 2 * 30) * 0.0025)


def test_anisotropic_pitch_scales_distances() -> None:
    panel = Panel(100, 80, 0.05, 0.1)
    reference = np.zeros((40, 40), dtype=bool)
    reference[10:30, 10:30] = True
    measured = np.roll(reference, 1, axis=0)
    assert boundary_distances(measured, reference, panel)["boundary_max_mm"] == pytest.approx(0.1)
    measured = np.roll(reference, 1, axis=1)
    assert boundary_distances(measured, reference, panel)["boundary_max_mm"] == pytest.approx(0.05)


def test_empty_layers() -> None:
    reference = disc((40, 40), (20, 20), 10)
    empty = np.zeros_like(reference)
    missing = layer_metrics(empty, reference, PANEL)
    assert missing["iou"] == 0.0
    assert missing["boundary_max_mm"] is None
    assert missing["centroid_dx_mm"] is None
    assert missing["area_error_mm2"] == pytest.approx(-reference.sum() * 0.0025)
    both = layer_metrics(empty, empty, PANEL)
    assert both["iou"] is None
    assert both["boundary_max_mm"] == 0.0


def test_edge_coverage_error() -> None:
    rng = np.random.default_rng(5)
    reference = np.clip(disc((40, 40), (20, 20), 10) + rng.uniform(-0.3, 0.3, (40, 40)), 0, 1)
    assert layer_metrics(reference, reference, PANEL)["edge_coverage_mae"] == 0.0
    binary = (reference >= 0.5).astype(np.float64)
    assert layer_metrics(binary, reference, PANEL)["edge_coverage_mae"] > 0.05


def test_shapes_must_match() -> None:
    with pytest.raises(ValueError, match="shapes differ"):
        layer_metrics(np.zeros((3, 3)), np.zeros((3, 4)), PANEL)
