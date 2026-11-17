"""Exact pixel coverage of sections on a printer panel.

**Canonical image.** The panel seen from above: ``resolution_x`` columns along +X and
``resolution_y`` rows along −Y, so row 0 is the back of the plate and the image reads like a
photograph of the plate taken from above. The plate origin (0, 0) is the panel centre. Pixel
``(row, column)`` covers ``[column, column + 1)`` horizontally in pixel units.

**Coverage.** The value of a pixel is the exact fraction of its area covered by material, in
``[0, 1]``. It is computed from the oriented section segments by accumulating, for every piece of
segment inside one pixel, the signed area between the piece and the pixel's right edge, and the
signed height of the piece for every pixel further right (the cumulative sum along each row). For
closed loops whose winding number is 0 or 1 the result is the exact covered area up to floating
point rounding; any other winding (overlapping or inverted solids) is refused.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from kbench.geometry import GeometryError
from kbench.geometry.mesh import FloatArray

# Coverage is a sum of terms of size ≤ 1 with rounding errors near 1e-16 times pixel coordinates
# (≤ about 2e4): a few 1e-12 at most. 1e-9 separates rounding from a real winding error (≥ 1e-3
# for any material overlap worth one-thousandth of a pixel).
COVERAGE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Panel:
    """A printer panel: its resolution and the pixel pitch on the plate, in mm."""

    resolution_x: int
    resolution_y: int
    pitch_x_mm: float
    pitch_y_mm: float

    def __post_init__(self) -> None:
        if self.resolution_x <= 0 or self.resolution_y <= 0:
            raise GeometryError("the panel resolution must be positive")
        if self.pitch_x_mm <= 0.0 or self.pitch_y_mm <= 0.0:
            raise GeometryError("the pixel pitch must be positive")

    @property
    def pixel_area_mm2(self) -> float:
        return self.pitch_x_mm * self.pitch_y_mm

    def column_of(self, x_mm: float) -> float:
        """The continuous column coordinate of plate X (pixel units, left edge 0)."""
        return x_mm / self.pitch_x_mm + self.resolution_x / 2.0

    def row_of(self, y_mm: float) -> float:
        """The continuous row coordinate of plate Y (pixel units, top edge 0)."""
        return self.resolution_y / 2.0 - y_mm / self.pitch_y_mm


@dataclass(frozen=True)
class Window:
    """A rectangle of the canonical image: rows ``[row0, row0 + rows)``, same for columns."""

    row0: int
    col0: int
    rows: int
    cols: int

    def shifted(self, rows: int, cols: int) -> Window:
        return Window(self.row0 + rows, self.col0 + cols, self.rows, self.cols)

    def clipped(self, panel: Panel) -> Window:
        """The part of this window inside the panel (possibly empty)."""
        row0 = min(max(self.row0, 0), panel.resolution_y)
        col0 = min(max(self.col0, 0), panel.resolution_x)
        row1 = min(max(self.row0 + self.rows, 0), panel.resolution_y)
        col1 = min(max(self.col0 + self.cols, 0), panel.resolution_x)
        return Window(row0, col0, row1 - row0, col1 - col0)

    def take(self, image: NDArray[np.generic]) -> NDArray[np.generic]:
        """This window of a full canonical image."""
        return image[self.row0 : self.row0 + self.rows, self.col0 : self.col0 + self.cols]


def window_around(
    panel: Panel, min_xy_mm: tuple[float, float], max_xy_mm: tuple[float, float], margin_px: int
) -> Window:
    """The window covering a plate rectangle plus ``margin_px`` pixels, not clipped."""
    col0 = math.floor(panel.column_of(min_xy_mm[0])) - margin_px
    col1 = math.ceil(panel.column_of(max_xy_mm[0])) + margin_px
    row0 = math.floor(panel.row_of(max_xy_mm[1])) - margin_px
    row1 = math.ceil(panel.row_of(min_xy_mm[1])) + margin_px
    return Window(row0, col0, row1 - row0, col1 - col0)


def coverage(
    segments_mm: FloatArray,
    panel: Panel,
    window: Window,
    offset_mm: tuple[float, float] = (0.0, 0.0),
) -> FloatArray:
    """The exact coverage ``(window.rows, window.cols)`` of the section, moved by ``offset_mm``."""
    result = np.zeros((window.rows, window.cols))
    if len(segments_mm) == 0 or window.rows == 0 or window.cols == 0:
        return result

    # Pixel space with the vertical axis pointing up, so that orientation is preserved:
    # u = column coordinate, w = rows counted upwards from the window's bottom edge.
    base = window.row0 + window.rows
    u_a = panel.column_of(0.0) + (segments_mm[:, 0] + offset_mm[0]) / panel.pitch_x_mm - window.col0
    u_b = panel.column_of(0.0) + (segments_mm[:, 2] + offset_mm[0]) / panel.pitch_x_mm - window.col0
    w_a = base - panel.row_of(segments_mm[:, 1] + offset_mm[1])
    w_b = base - panel.row_of(segments_mm[:, 3] + offset_mm[1])

    keep = w_a != w_b  # Horizontal pieces enclose no height: they contribute nothing.
    u_a, u_b, w_a, w_b = u_a[keep], u_b[keep], w_a[keep], w_b[keep]

    t_values, owners = _split_parameters(u_a, u_b, w_a, w_b)
    same = owners[1:] == owners[:-1]
    t0, t1, owner = t_values[:-1][same], t_values[1:][same], owners[:-1][same]
    nonempty = t1 > t0
    t0, t1, owner = t0[nonempty], t1[nonempty], owner[nonempty]

    du, dw = u_b - u_a, w_b - w_a
    pu0 = u_a[owner] + t0 * du[owner]
    pu1 = u_a[owner] + t1 * du[owner]
    pw0 = w_a[owner] + t0 * dw[owner]
    pw1 = w_a[owner] + t1 * dw[owner]

    column = np.floor((pu0 + pu1) / 2.0).astype(np.int64)
    level = np.floor((pw0 + pw1) / 2.0).astype(np.int64)
    height = pw1 - pw0
    # A downward piece adds +1 winding to everything at its right (counter-clockwise outer loops).
    weight = -height

    inside_rows = (level >= 0) & (level < window.rows)
    column, level, weight = column[inside_rows], level[inside_rows], weight[inside_rows]
    pu_mid = ((pu0 + pu1) / 2.0)[inside_rows]

    width = window.cols
    area = np.zeros(window.rows * width)
    cover = np.zeros(window.rows * (width + 1))

    left = column < 0
    np.add.at(cover, level[left] * (width + 1), weight[left])

    within = (column >= 0) & (column < width)
    c, r, wgt = column[within], level[within], weight[within]
    np.add.at(area, r * width + c, wgt * (c + 1 - pu_mid[within]))
    np.add.at(cover, r * (width + 1) + c + 1, wgt)

    totals = (
        area.reshape(window.rows, width)
        + np.cumsum(cover.reshape(window.rows, width + 1), axis=1)[:, :width]
    )
    low, high = float(totals.min()), float(totals.max())
    if low < -COVERAGE_TOLERANCE or high > 1.0 + COVERAGE_TOLERANCE:
        raise GeometryError(
            f"coverage outside [0, 1] ({low:.6g} to {high:.6g}): solids overlap or are inverted"
        )
    np.clip(totals, 0.0, 1.0, out=totals)
    return totals[::-1].copy()  # Rows counted upwards → image rows from the top.


def _split_parameters(
    u_a: FloatArray, u_b: FloatArray, w_a: FloatArray, w_b: FloatArray
) -> tuple[FloatArray, NDArray[np.int64]]:
    """Every segment's parameters ``t`` at 0, 1 and each integer column or row line it crosses,
    sorted by segment then ``t``."""
    count = len(u_a)
    parts_t = [np.zeros(count), np.ones(count)]
    parts_owner = [np.arange(count), np.arange(count)]
    for a, b in ((u_a, u_b), (w_a, w_b)):
        low, high = np.minimum(a, b), np.maximum(a, b)
        first = np.floor(low).astype(np.int64) + 1
        last = np.ceil(high).astype(np.int64) - 1
        crossings = np.maximum(last - first + 1, 0)
        owner = np.repeat(np.arange(count), crossings)
        if len(owner) == 0:
            continue
        starts = np.cumsum(crossings) - crossings
        lines = first[owner] + (np.arange(len(owner)) - starts[owner])
        delta = (b - a)[owner]
        parts_t.append((lines - a[owner]) / delta)
        parts_owner.append(owner)
    t = np.concatenate(parts_t)
    owner = np.concatenate(parts_owner)
    order = np.lexsort((t, owner))
    return t[order], owner[order]
