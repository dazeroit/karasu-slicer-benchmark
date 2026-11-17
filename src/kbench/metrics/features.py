"""Fine-feature metrics: the printed size of pins, holes, slots and walls (docs/METRICS.md).

Each feature body carries its nominal size and its measuring geometry from the model
(``models.feature_geometry``). It is measured on the layers away from its bottom and top, and
the median over those layers is reported, so a single noisy layer does not decide.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

from kbench.geometry.raster import Panel, Window, window_around
from kbench.metrics import MATERIAL_THRESHOLD
from kbench.models import BuiltModel
from kbench.reference import Layer

# Layers left out at each end of a feature body: its bottom and top layers carry the slicer's
# first-layer and last-layer behaviour, not the feature's size.
END_LAYERS = 2
# Pixels added around a hole's or slot's measuring window, so that a hole or slot printed
# slightly larger still lies inside it.
WINDOW_MARGIN_PX = 3


def mid_layers(layers: Sequence[Layer], z_min: float, z_max: float) -> list[int]:
    """Indices of the layers inside ``[z_min, z_max]`` with :data:`END_LAYERS` left out at
    each end."""
    inside = [
        layer.index
        for layer in layers
        if layer.z_bottom_mm >= z_min - 1e-9 and layer.z_bottom_mm + layer.height_mm <= z_max + 1e-9
    ]
    return inside[END_LAYERS : len(inside) - END_LAYERS]


def equivalent_diameter(area_mm2: float) -> float:
    """The diameter of the circle of ``area_mm2``."""
    return 2.0 * math.sqrt(max(area_mm2, 0.0) / math.pi)


def hole_area_mm2(coverage: NDArray[np.float64], panel: Panel) -> float:
    """The area enclosed by material and not covered by it: the empty pixels the material
    surrounds (4-connected fill), counted whole. Zero when the hole closed."""
    material = coverage >= MATERIAL_THRESHOLD
    filled = ndimage.binary_fill_holes(material)
    return float(np.count_nonzero(filled & ~material)) * panel.pixel_area_mm2


def empty_area_mm2(coverage: NDArray[np.float64], panel: Panel) -> float:
    """The uncovered area of a window: the sum of ``1 - coverage``."""
    return float((1.0 - coverage).sum()) * panel.pixel_area_mm2


def measuring_windows(
    model: BuiltModel, panel: Panel, offset_mm: tuple[float, float]
) -> dict[str, Window]:
    """The canonical-image window where each hole or slot is measured."""
    windows = {}
    for body in model.bodies:
        feature = body.feature
        if feature is None or feature["kind"] not in ("hole", "slot"):
            continue
        if feature["kind"] == "slot":
            band = feature["band_mm"]
            low = (band["x"][0] + offset_mm[0], band["y"][0] + offset_mm[1])
            high = (band["x"][1] + offset_mm[0], band["y"][1] + offset_mm[1])
            # The band spans the slot's width plus the margin, and only its measured length.
            window = window_around(panel, low, high, 0)
            windows[body.name] = Window(
                window.row0,
                window.col0 - WINDOW_MARGIN_PX,
                window.rows,
                window.cols + 2 * WINDOW_MARGIN_PX,
            )
        else:
            triangles = model.body_triangles(body.name)
            used = model.mesh.vertices[np.unique(model.mesh.triangles[triangles])]
            low = (used[:, 0].min() + offset_mm[0], used[:, 1].min() + offset_mm[1])
            high = (used[:, 0].max() + offset_mm[0], used[:, 1].max() + offset_mm[1])
            windows[body.name] = window_around(panel, low, high, WINDOW_MARGIN_PX)
    return windows


def summarize(
    model: BuiltModel,
    layers: Sequence[Layer],
    body_areas: Mapping[str, Sequence[float]],
    window_values: Mapping[str, Sequence[float]],
) -> list[dict[str, Any]]:
    """One record per feature body: nominal, reference and measured size, and whether it
    printed (pins and walls) or stayed open (holes and slots)."""
    results = []
    for body in model.bodies:
        feature = body.feature
        if feature is None:
            continue
        triangles = model.body_triangles(body.name)
        heights = model.mesh.vertices[np.unique(model.mesh.triangles[triangles]), 2]
        used = mid_layers(layers, float(heights.min()), float(heights.max()))
        kind = feature["kind"]
        if kind == "pin":
            values = [equivalent_diameter(body_areas[body.name][index]) for index in used]
        elif kind == "wall":
            values = [body_areas[body.name][index] / feature["length_mm"] for index in used]
        else:
            values = [window_values[body.name][index] for index in used]
        measured = float(np.median(values)) if values else None
        results.append(
            {
                "body": body.name,
                "kind": kind,
                "nominal_mm": feature["nominal_mm"],
                "reference_mm": feature["reference_mm"],
                "measured_mm": measured,
                "error_mm": measured - feature["reference_mm"] if measured is not None else None,
                "resolved": measured is not None and measured > 0.0,
                "layers": len(used),
            }
        )
    return results


def smallest_resolved(features: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """Per kind, the smallest nominal size that printed (pins, walls) or stayed open (holes,
    slots), counting only sizes at or above which every feature of that kind resolved."""
    result: dict[str, float | None] = {}
    for kind in ("pin", "wall", "hole", "slot"):
        items = sorted((f for f in features if f["kind"] == kind), key=lambda f: f["nominal_mm"])
        if not items:
            continue
        smallest = None
        for item in reversed(items):
            if not item["resolved"]:
                break
            smallest = item["nominal_mm"]
        result[kind] = smallest
    return result
