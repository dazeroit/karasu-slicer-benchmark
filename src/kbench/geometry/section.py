"""Exact sections of a mesh by horizontal planes.

A section is a set of oriented segments ``(x_a, y_a, x_b, y_b)`` in millimetres with the material
on their left, so outer contours run counter-clockwise and holes clockwise. The segments of a
closed, outward-oriented mesh form closed loops; they need not be chained to compute areas or
pixel coverage.

**Plane through a vertex.** A vertex exactly on the plane counts as above it. The section is then
the limit of sections taken just below the plane, which is continuous wherever the section area
is continuous. A triangle lying in the plane (all three corners on it) makes the section
ambiguous, because the area jumps there; it is refused with :class:`DegenerateSectionError`.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from kbench.geometry import GeometryError
from kbench.geometry.mesh import FloatArray, Mesh


class DegenerateSectionError(GeometryError):
    """The plane contains a face of the mesh, so the section is not well defined."""


def plane_segments(
    mesh: Mesh, z_mm: float, triangle_subset: NDArray[np.int64] | None = None
) -> FloatArray:
    """The oriented section segments ``(k, 4)`` of ``mesh`` at height ``z_mm``.

    ``triangle_subset`` limits the cut to those triangle indices (a body of a model).
    """
    triangles = mesh.triangles if triangle_subset is None else mesh.triangles[triangle_subset]
    if len(triangles) == 0:
        return np.empty((0, 4))
    heights = mesh.vertices[triangles, 2]
    above = heights >= z_mm
    in_plane = heights == z_mm
    if np.any(in_plane.all(axis=1)):
        raise DegenerateSectionError(f"a face lies in the plane z = {z_mm!r} mm")
    above_count = above.sum(axis=1)
    crossing = (above_count == 1) | (above_count == 2)
    triangles, above = triangles[crossing], above[crossing]
    if len(triangles) == 0:
        return np.empty((0, 4))

    start_edge = np.full(len(triangles), -1)
    end_edge = np.full(len(triangles), -1)
    for edge in range(3):
        here, there = above[:, edge], above[:, (edge + 1) % 3]
        start_edge = np.where(here & ~there, edge, start_edge)  # Going down: the loop starts.
        end_edge = np.where(~here & there, edge, end_edge)  # Going up: the loop ends.

    start = _edge_point(mesh.vertices, triangles, start_edge, z_mm)
    end = _edge_point(mesh.vertices, triangles, end_edge, z_mm)
    return np.column_stack((start, end))


def _edge_point(
    vertices: FloatArray, triangles: NDArray[np.int64], edge: NDArray[np.int64], z_mm: float
) -> FloatArray:
    rows = np.arange(len(triangles))
    first = triangles[rows, edge]
    second = triangles[rows, (edge + 1) % 3]
    # Interpolate from the lower vertex index, so both triangles of an edge get the same point.
    low = np.minimum(first, second)
    high = np.maximum(first, second)
    p, q = vertices[low], vertices[high]
    t = (z_mm - p[:, 2]) / (q[:, 2] - p[:, 2])
    return p[:, :2] + t[:, None] * (q[:, :2] - p[:, :2])


def segments_area(segments: FloatArray) -> float:
    """The area in mm² enclosed by closed oriented segments (shoelace, no chaining needed)."""
    xa, ya, xb, yb = segments.T
    return float((xa * yb - xb * ya).sum() / 2.0)


def segments_perimeter(segments: FloatArray) -> float:
    """The total length in mm of the section's boundary (outer contours and holes)."""
    return float(np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1]).sum())


def area_profile(
    mesh: Mesh,
    heights_mm: Sequence[float] | FloatArray,
    triangle_subset: NDArray[np.int64] | None = None,
) -> FloatArray:
    """Section areas in mm² at each of ``heights_mm``.

    Triangles are pre-selected by their height range so that each plane only cuts the
    triangles that can reach it.
    """
    subset = np.arange(len(mesh.triangles)) if triangle_subset is None else triangle_subset
    heights = mesh.vertices[mesh.triangles[subset], 2]
    low, high = heights.min(axis=1), heights.max(axis=1)
    order = np.argsort(low, kind="stable")
    subset, low, high = subset[order], low[order], high[order]
    areas = np.empty(len(heights_mm))
    for index, z in enumerate(np.asarray(heights_mm, dtype=np.float64)):
        reach = subset[: np.searchsorted(low, z, side="right")]
        reach = reach[high[: len(reach)] >= z]
        areas[index] = segments_area(plane_segments(mesh, float(z), reach))
    return areas
