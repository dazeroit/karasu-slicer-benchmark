"""Closed, outward-oriented test solids with known exact properties.

Every generator returns a mesh standing on ``z = 0`` with its bounding box centred on the Z axis,
before ``float32`` quantisation (the model builder places and quantises bodies).
"""

from __future__ import annotations

import itertools
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


def washer(size_mm: float, hole_radius_mm: float, segments: int, height_mm: float) -> Mesh:
    """A square plate of side ``size_mm`` with a regular-polygon hole through its centre.

    The hole has circumradius ``hole_radius_mm``; its first vertex is half a segment past the X
    axis. Each cap is split into one convex wedge per hole edge, between the hole edge and the
    square boundary seen along the same two rays from the centre (plus a corner of the square
    where one falls inside the wedge), so the triangulation is exact and needs no search.
    """
    half = size_mm / 2.0
    if not 0.0 < hole_radius_mm < half:
        raise GeometryError("the hole must lie inside the square")
    if height_mm <= 0.0:
        raise GeometryError("the height must be positive")
    inner = regular_polygon(hole_radius_mm, segments, math.pi / segments)
    width = 2.0 * math.pi / segments
    start = math.pi / segments
    corners = [math.pi / 4.0 + j * math.pi / 2.0 for j in range(4)]

    outer: list[tuple[float, float]] = []
    wedges: list[list[int]] = []  # Outer ring indices from O_k to O_{k+1}, corners between.
    for k in range(segments):
        angle = start + k * width
        c, s = math.cos(angle), math.sin(angle)
        scale = half / max(abs(c), abs(s))
        first = len(outer)
        outer.append((c * scale, s * scale))
        ring = [first]
        between = sorted(
            ((corner - angle) % (2.0 * math.pi), corner)
            for corner in corners
            if 1e-12 < (corner - angle) % (2.0 * math.pi) < width - 1e-12
        )
        for _, corner in between:
            outer.append(
                (
                    half * math.copysign(1.0, math.cos(corner)),
                    half * math.copysign(1.0, math.sin(corner)),
                )
            )
            ring.append(len(outer) - 1)
        wedges.append(ring)
    count_outer = len(outer)
    for k in range(segments):
        wedges[k].append(wedges[(k + 1) % segments][0])

    ring_xy = np.concatenate((inner, np.asarray(outer)))
    n = segments
    m = count_outer
    vertices = np.concatenate(
        (
            np.column_stack((ring_xy, np.zeros(n + m))),
            np.column_stack((ring_xy, np.full(n + m, height_mm))),
        )
    )
    top = n + m  # Index offset of the top layer.

    def inner_index(k: int) -> int:
        return k % n

    def outer_index(j: int) -> int:
        return n + j

    triangles: list[tuple[int, int, int]] = []
    for k in range(n):
        polygon = [inner_index(k), *(outer_index(j) for j in wedges[k]), inner_index(k + 1)]
        for a, b in itertools.pairwise(polygon[1:]):
            triangles.append((polygon[0] + top, a + top, b + top))  # Top cap, facing up.
            triangles.append((polygon[0], b, a))  # Bottom cap, facing down.
    for j in range(m):  # Outer walls, facing out.
        a, b = outer_index(j), outer_index((j + 1) % m)
        triangles += [(a, b, b + top), (a, b + top, a + top)]
    for k in range(n):  # Hole walls, facing the hole's axis.
        a, b = inner_index(k), inner_index(k + 1)
        triangles += [(b, a, a + top), (b, a + top, b + top)]
    return Mesh(vertices, np.asarray(triangles, dtype=np.int64))


def slotted(
    size_mm: tuple[float, float], slot_width_mm: float, slot_depth_mm: float, height_mm: float
) -> Mesh:
    """A block ``size_mm = (x, y)`` with a slot of ``slot_width_mm`` cut from its +Y side,
    centred in X, ``slot_depth_mm`` deep."""
    sx, sy = size_mm
    w, d = slot_width_mm, slot_depth_mm
    if not (0.0 < w < sx and 0.0 < d < sy):
        raise GeometryError("the slot must lie inside the block")
    polygon = np.array(
        [
            [-sx / 2, -sy / 2],
            [sx / 2, -sy / 2],
            [sx / 2, sy / 2],
            [w / 2, sy / 2],
            [w / 2, sy / 2 - d],
            [-w / 2, sy / 2 - d],
            [-w / 2, sy / 2],
            [-sx / 2, sy / 2],
        ],
        dtype=np.float64,
    )
    return extrude(polygon, height_mm)
