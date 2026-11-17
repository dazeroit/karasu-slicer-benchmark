"""Closed, outward-oriented test solids with known exact properties.

Every generator returns a mesh standing on ``z = 0`` with its bounding box centred on the Z axis,
before ``float32`` quantisation (the model builder places and quantises bodies).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from kbench.geometry import GeometryError
from kbench.geometry.mesh import Mesh
from kbench.geometry.polygon import signed_area, triangulate


def regular_polygon(radius_mm: float, segments: int, phase_rad: float = 0.0) -> NDArray[np.float64]:
    """Counter-clockwise vertices of a regular polygon of circumradius ``radius_mm``.

    Vertex ``k`` lies at angle ``phase_rad + 2πk / segments``.
    """
    if segments < 3:
        raise GeometryError("a regular polygon needs at least three segments")
    if radius_mm <= 0.0:
        raise GeometryError("the radius must be positive")
    angles = phase_rad + 2.0 * math.pi * np.arange(segments) / segments
    return np.column_stack((radius_mm * np.cos(angles), radius_mm * np.sin(angles)))


def extrude(polygon: NDArray[np.float64], height_mm: float, *, convex: bool = False) -> Mesh:
    """A prism: the counter-clockwise simple ``polygon`` from ``z = 0`` to ``z = height_mm``.

    Caps are fans when ``convex`` is true, otherwise ear-clipped.
    """
    if height_mm <= 0.0:
        raise GeometryError("the height must be positive")
    polygon = np.asarray(polygon, dtype=np.float64)
    count = len(polygon)
    if count < 3 or signed_area(polygon) <= 0.0:
        raise GeometryError("the polygon must be counter-clockwise with at least three vertices")

    bottom = np.column_stack((polygon, np.zeros(count)))
    top = np.column_stack((polygon, np.full(count, height_mm)))
    vertices = np.concatenate((bottom, top))

    if convex:
        cap = np.column_stack(
            (np.zeros(count - 2, dtype=np.int64), np.arange(1, count - 1), np.arange(2, count))
        )
    else:
        cap = triangulate(polygon)
    top_cap = cap + count
    bottom_cap = cap[:, ::-1]  # Facing down.

    i = np.arange(count, dtype=np.int64)
    j = (i + 1) % count
    sides = np.concatenate(
        (np.column_stack((i, j, j + count)), np.column_stack((i, j + count, i + count)))
    )
    return Mesh(vertices, np.concatenate((bottom_cap, top_cap, sides)).astype(np.int64))


def box(size_mm: tuple[float, float, float]) -> Mesh:
    """An axis-aligned box ``size_mm = (x, y, z)``."""
    sx, sy, sz = size_mm
    rectangle = np.array(
        [[-sx / 2, -sy / 2], [sx / 2, -sy / 2], [sx / 2, sy / 2], [-sx / 2, sy / 2]],
        dtype=np.float64,
    )
    return extrude(rectangle, sz, convex=True)


def prism(radius_mm: float, segments: int, height_mm: float, phase_rad: float = 0.0) -> Mesh:
    """A regular prism, the faceted cylinder slicers receive from CAD exports."""
    return extrude(regular_polygon(radius_mm, segments, phase_rad), height_mm, convex=True)


def cone(radius_mm: float, segments: int, height_mm: float, phase_rad: float = 0.0) -> Mesh:
    """A regular pyramid: a regular polygon base at ``z = 0`` and its apex at ``height_mm``."""
    if height_mm <= 0.0:
        raise GeometryError("the height must be positive")
    base = regular_polygon(radius_mm, segments, phase_rad)
    vertices = np.concatenate(
        (np.column_stack((base, np.zeros(segments))), [[0.0, 0.0, height_mm]])
    )
    apex = segments
    i = np.arange(segments, dtype=np.int64)
    j = (i + 1) % segments
    base_cap = np.column_stack((np.zeros(segments - 2, dtype=np.int64), i[2:], i[1:-1]))
    sides = np.column_stack((i, j, np.full(segments, apex, dtype=np.int64)))
    return Mesh(vertices, np.concatenate((base_cap, sides)))


def icosphere(radius_mm: float, subdivisions: int) -> Mesh:
    """A sphere: an icosahedron split ``subdivisions`` times, vertices on the sphere.

    It has ``20 · 4^subdivisions`` triangles. It is translated so its lowest vertex lies on
    ``z = 0``.
    """
    if radius_mm <= 0.0:
        raise GeometryError("the radius must be positive")
    if not 0 <= subdivisions <= 10:
        raise GeometryError("subdivisions must be between 0 and 10")

    t = (1.0 + math.sqrt(5.0)) / 2.0
    vertices = np.array(
        [
            [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
            [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
            [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
        ],
        dtype=np.float64,
    )  # fmt: skip
    faces = np.array(
        [
            [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
            [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
            [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
            [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
        ],
        dtype=np.int64,
    )  # fmt: skip
    vertices /= np.linalg.norm(vertices, axis=1, keepdims=True)

    for _ in range(subdivisions):
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        edges = np.concatenate(
            (np.column_stack((a, b)), np.column_stack((b, c)), np.column_stack((c, a)))
        )
        edges.sort(axis=1)
        unique, inverse = np.unique(edges, axis=0, return_inverse=True)
        midpoints = (vertices[unique[:, 0]] + vertices[unique[:, 1]]) / 2.0
        midpoints /= np.linalg.norm(midpoints, axis=1, keepdims=True)
        first_new = len(vertices)
        vertices = np.concatenate((vertices, midpoints))
        count = len(faces)
        ab = first_new + inverse[:count]
        bc = first_new + inverse[count : 2 * count]
        ca = first_new + inverse[2 * count :]
        faces = np.concatenate(
            (
                np.column_stack((a, ab, ca)),
                np.column_stack((b, bc, ab)),
                np.column_stack((c, ca, bc)),
                np.column_stack((ab, bc, ca)),
            )
        )

    vertices = vertices * radius_mm
    vertices[:, 2] -= vertices[:, 2].min()
    return Mesh(vertices, faces.astype(np.int64))
