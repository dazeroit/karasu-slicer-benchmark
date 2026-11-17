"""Metrics of one layer: a measured coverage image against the reference on the same window."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

from kbench.geometry.raster import Panel
from kbench.metrics import MATERIAL_THRESHOLD

LAYER_FIELDS: tuple[str, ...] = (
    "measured_area_mm2",
    "reference_area_mm2",
    "area_error_mm2",
    "iou",
    "xor_area_mm2",
    "boundary_mean_mm",
    "boundary_p95_mm",
    "boundary_max_mm",
    "centroid_dx_mm",
    "centroid_dy_mm",
    "width_error_mm",
    "depth_error_mm",
    "edge_coverage_mae",
)


def layer_metrics(
    measured: NDArray[np.float64], reference: NDArray[np.float64], panel: Panel
) -> dict[str, Any]:
    """Every metric of :data:`LAYER_FIELDS` for one layer (``None`` where undefined).

    Both images are coverage in ``[0, 1]`` on the same window of the canonical image.
    """
    if measured.shape != reference.shape:
        raise ValueError(f"shapes differ: {measured.shape} and {reference.shape}")
    pixel = panel.pixel_area_mm2
    measured_mask = measured >= MATERIAL_THRESHOLD
    reference_mask = reference >= MATERIAL_THRESHOLD
    union = np.count_nonzero(measured_mask | reference_mask)
    intersection = np.count_nonzero(measured_mask & reference_mask)

    measured_area = float(measured.sum()) * pixel
    reference_area = float(reference.sum()) * pixel
    result: dict[str, Any] = {
        "measured_area_mm2": measured_area,
        "reference_area_mm2": reference_area,
        "area_error_mm2": measured_area - reference_area,
        "iou": intersection / union if union else None,
        "xor_area_mm2": (union - intersection) * pixel,
    }
    result.update(boundary_distances(measured_mask, reference_mask, panel))
    result.update(_centroid_offset(measured, reference, panel))
    result.update(_extent_errors(measured_mask, reference_mask, panel))

    edge = ((reference > 0.0) & (reference < 1.0)) | ((measured > 0.0) & (measured < 1.0))
    result["edge_coverage_mae"] = (
        float(np.abs(measured[edge] - reference[edge]).mean()) if edge.any() else None
    )
    return result


def boundary_pixels(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Material pixels with an empty pixel among their four neighbours (outside is empty)."""
    return mask & ~ndimage.binary_erosion(mask, border_value=0)


def boundary_distances(
    measured_mask: NDArray[np.bool_], reference_mask: NDArray[np.bool_], panel: Panel
) -> dict[str, float | None]:
    """Distances in mm between the boundary pixels of the two masks, in both directions.

    Every boundary pixel of either mask contributes its distance (between pixel centres, with the
    panel's pitch) to the nearest boundary pixel of the other. The maximum is the Hausdorff
    distance of the boundaries. Identical masks give zeros; ``None`` when one mask is empty and the
    other is not (no finite distance), zeros when both are empty.
    """
    fields = ("boundary_mean_mm", "boundary_p95_mm", "boundary_max_mm")
    has_measured, has_reference = measured_mask.any(), reference_mask.any()
    if not has_measured and not has_reference:
        return dict.fromkeys(fields, 0.0)
    if has_measured != has_reference:
        return dict.fromkeys(fields, None)

    measured_edge = boundary_pixels(measured_mask)
    reference_edge = boundary_pixels(reference_mask)
    if np.array_equal(measured_edge, reference_edge):
        return dict.fromkeys(fields, 0.0)

    rows = np.flatnonzero((measured_edge | reference_edge).any(axis=1))
    cols = np.flatnonzero((measured_edge | reference_edge).any(axis=0))
    crop = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
    sampling = (panel.pitch_y_mm, panel.pitch_x_mm)
    to_reference = ndimage.distance_transform_edt(~reference_edge[crop], sampling=sampling)
    to_measured = ndimage.distance_transform_edt(~measured_edge[crop], sampling=sampling)
    distances = np.concatenate(
        (to_reference[measured_edge[crop]], to_measured[reference_edge[crop]])
    )
    return {
        "boundary_mean_mm": float(distances.mean()),
        "boundary_p95_mm": float(np.percentile(distances, 95)),
        "boundary_max_mm": float(distances.max()),
    }


def _centroid(image: NDArray[np.float64]) -> tuple[float, float] | None:
    total = image.sum()
    if total <= 0.0:
        return None
    rows = np.arange(image.shape[0]) + 0.5
    cols = np.arange(image.shape[1]) + 0.5
    return float(image.sum(axis=1) @ rows / total), float(image.sum(axis=0) @ cols / total)


def _centroid_offset(
    measured: NDArray[np.float64], reference: NDArray[np.float64], panel: Panel
) -> dict[str, float | None]:
    a, b = _centroid(measured), _centroid(reference)
    if a is None or b is None:
        return {"centroid_dx_mm": None, "centroid_dy_mm": None}
    return {
        "centroid_dx_mm": (a[1] - b[1]) * panel.pitch_x_mm,
        "centroid_dy_mm": -(a[0] - b[0]) * panel.pitch_y_mm,  # Rows grow towards −Y.
    }


def _extent(mask: NDArray[np.bool_]) -> tuple[int, int] | None:
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if len(rows) == 0:
        return None
    return cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1


def _extent_errors(
    measured_mask: NDArray[np.bool_], reference_mask: NDArray[np.bool_], panel: Panel
) -> dict[str, float | None]:
    a, b = _extent(measured_mask), _extent(reference_mask)
    if a is None or b is None:
        return {"width_error_mm": None, "depth_error_mm": None}
    return {
        "width_error_mm": (a[0] - b[0]) * panel.pitch_x_mm,
        "depth_error_mm": (a[1] - b[1]) * panel.pitch_y_mm,
    }
