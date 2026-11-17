"""Reference layers: what an exact slicer would put on the panel.

Layer ``i`` occupies the slab ``[z_bottom, z_bottom + height]``. Its reference image is the exact
pixel coverage of the mesh's section at the slab's mid-height (``sample_fraction = 0.5``), the
plane that best represents the slab. Other fractions serve the Z-phase estimate.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import numpy as np

from kbench.geometry import GeometryError
from kbench.geometry.mesh import FloatArray, Mesh
from kbench.geometry.raster import Panel, Window, coverage, window_around
from kbench.geometry.section import plane_segments

MID_PLANE = 0.5

# Margin around a model's bounds in reference windows: room for slicer dilation, anti-aliasing
# fringes and small placement errors without cropping measured material.
WINDOW_MARGIN_PX = 8


@dataclass(frozen=True)
class Layer:
    """One slab of the schedule, in mm."""

    index: int
    z_bottom_mm: float
    height_mm: float

    def plane_mm(self, sample_fraction: float = MID_PLANE) -> float:
        return self.z_bottom_mm + sample_fraction * self.height_mm


def uniform_schedule(model_height_mm: float, layer_height_mm: float) -> list[Layer]:
    """Equal layers from ``z = 0`` until the model's top is covered.

    The count is ``ceil(model_height / layer_height)``, computed on the ratio rounded to nine
    decimals so that a height that is a whole number of layers in decimal (10 mm of 0.05 mm)
    does not gain a layer from binary rounding.
    """
    if model_height_mm <= 0.0 or layer_height_mm <= 0.0:
        raise GeometryError("heights must be positive")
    count = math.ceil(round(model_height_mm / layer_height_mm, 9))
    return [Layer(i, i * layer_height_mm, layer_height_mm) for i in range(count)]


def model_window(mesh: Mesh, panel: Panel, margin_px: int = WINDOW_MARGIN_PX) -> Window:
    """The canonical-image window around the model's XY bounds, plus ``margin_px``."""
    low, high = mesh.bounds()
    return window_around(panel, (low[0], low[1]), (high[0], high[1]), margin_px)


def reference_layer(
    mesh: Mesh,
    panel: Panel,
    window: Window,
    layer: Layer,
    *,
    offset_mm: tuple[float, float] = (0.0, 0.0),
    sample_fraction: float = MID_PLANE,
) -> FloatArray:
    """The exact coverage of ``layer`` in ``window``, the model moved by ``offset_mm``."""
    return coverage(plane_segments(mesh, layer.plane_mm(sample_fraction)), panel, window, offset_mm)


def reference_stack(
    mesh: Mesh,
    panel: Panel,
    window: Window,
    layers: Sequence[Layer],
    *,
    offset_mm: tuple[float, float] = (0.0, 0.0),
    sample_fraction: float = MID_PLANE,
) -> Iterator[FloatArray]:
    """Reference layers one at a time, in schedule order (bounded memory)."""
    for layer in layers:
        yield reference_layer(
            mesh, panel, window, layer, offset_mm=offset_mm, sample_fraction=sample_fraction
        )


def full_panel(panel: Panel, window: Window, values: FloatArray) -> FloatArray:
    """A full canonical image holding ``values`` at ``window`` and zero elsewhere.

    The part of the window outside the panel is dropped.
    """
    image = np.zeros((panel.resolution_y, panel.resolution_x))
    inside = window.clipped(panel)
    image[inside.row0 : inside.row0 + inside.rows, inside.col0 : inside.col0 + inside.cols] = (
        values[
            inside.row0 - window.row0 : inside.row0 - window.row0 + inside.rows,
            inside.col0 - window.col0 : inside.col0 - window.col0 + inside.cols,
        ]
    )
    return image
