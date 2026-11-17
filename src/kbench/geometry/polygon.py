"""Simple planar polygons: area and triangulation."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from kbench.geometry import GeometryError


def signed_area(polygon: NDArray[np.float64]) -> float:
    """Shoelace area of a closed polygon ``(k, 2)``: positive when counter-clockwise."""
    x, y = polygon[:, 0], polygon[:, 1]
    return float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2.0)


def triangulate(polygon: NDArray[np.float64]) -> NDArray[np.int64]:
    """Triangles ``(k - 2, 3)`` covering a simple counter-clockwise polygon, by ear clipping.

    Each triangle is counter-clockwise. A polygon that is not counter-clockwise, or that no ear
    can be cut from (self-intersecting or with repeated vertices), is refused.
    """
    count = len(polygon)
    if count < 3:
        raise GeometryError("a polygon needs at least three vertices")
    if signed_area(polygon) <= 0.0:
        raise GeometryError("the polygon is not counter-clockwise")

    remaining = list(range(count))
    triangles: list[tuple[int, int, int]] = []
    while len(remaining) > 3:
        for position in range(len(remaining)):
            previous = remaining[position - 1]
            current = remaining[position]
            following = remaining[(position + 1) % len(remaining)]
            if _is_ear(polygon, remaining, previous, current, following):
                triangles.append((previous, current, following))
                del remaining[position]
                break
        else:
            raise GeometryError("no ear found: the polygon is not simple")
    triangles.append((remaining[0], remaining[1], remaining[2]))
    return np.asarray(triangles, dtype=np.int64)


def _cross(o: NDArray[np.float64], a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def _is_ear(
    polygon: NDArray[np.float64], remaining: list[int], previous: int, current: int, following: int
) -> bool:
    a, b, c = polygon[previous], polygon[current], polygon[following]
    if _cross(a, b, c) <= 0.0:  # Reflex or collinear corner.
        return False
    for index in remaining:
        if index in (previous, current, following):
            continue
        point = polygon[index]
        # Inside or on the boundary of the candidate ear: cutting it would cross the polygon.
        if _cross(a, b, point) >= 0.0 and _cross(b, c, point) >= 0.0 and _cross(c, a, point) >= 0.0:
            return False
    return True
