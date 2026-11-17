"""Indexed triangle meshes in millimetres.

A :class:`Mesh` holds ``float64`` vertices whose values are all exactly representable as
``float32``: binary STL stores ``float32`` coordinates, so the suite computes its ground truth from
exactly the coordinates a slicer reads. Triangles are counter-clockwise seen from outside, so
their right-hand normals point out of the solid.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from kbench.geometry import GeometryError

FloatArray = NDArray[np.float64]
IndexArray = NDArray[np.int64]


@dataclass(frozen=True)
class Mesh:
    """Vertices ``(n, 3)`` and triangles ``(m, 3)`` indexing them."""

    vertices: FloatArray
    triangles: IndexArray

    def __post_init__(self) -> None:
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise GeometryError(f"vertices must have shape (n, 3), not {self.vertices.shape}")
        if self.triangles.ndim != 2 or self.triangles.shape[1] != 3:
            raise GeometryError(f"triangles must have shape (m, 3), not {self.triangles.shape}")
        if self.vertices.dtype != np.float64 or self.triangles.dtype != np.int64:
            raise GeometryError("vertices must be float64 and triangles int64")
        if self.triangles.size and (
            self.triangles.min() < 0 or self.triangles.max() >= len(self.vertices)
        ):
            raise GeometryError("a triangle indexes a vertex that does not exist")

    @property
    def triangle_vertices(self) -> FloatArray:
        """The corners of every triangle, shape ``(m, 3, 3)``."""
        return self.vertices[self.triangles]

    def bounds(self) -> tuple[FloatArray, FloatArray]:
        """The minimum and maximum corner of the vertices' bounding box."""
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def signed_volume(self) -> float:
        """The enclosed volume in mm³ (divergence theorem); negative when the mesh is inverted."""
        corners = self.triangle_vertices
        return float(
            np.einsum("ij,ij->i", corners[:, 0], np.cross(corners[:, 1], corners[:, 2])).sum() / 6.0
        )

    def translated(self, offset: Sequence[float]) -> Mesh:
        """A copy moved by ``offset`` (mm), quantised back to ``float32`` values."""
        moved = self.vertices + np.asarray(offset, dtype=np.float64)
        return Mesh(quantize_float32(moved), self.triangles.copy())


def quantize_float32(values: FloatArray) -> FloatArray:
    """Round to the nearest ``float32`` and return as ``float64``."""
    return np.asarray(values, dtype=np.float64).astype(np.float32).astype(np.float64)


def merge(meshes: Sequence[Mesh]) -> Mesh:
    """One mesh holding all of ``meshes``; triangle order follows the input order."""
    vertices: list[FloatArray] = []
    triangles: list[IndexArray] = []
    offset = 0
    for mesh in meshes:
        vertices.append(mesh.vertices)
        triangles.append(mesh.triangles + offset)
        offset += len(mesh.vertices)
    return Mesh(
        np.concatenate(vertices) if vertices else np.empty((0, 3)),
        np.concatenate(triangles) if triangles else np.empty((0, 3), dtype=np.int64),
    )


def weld(triangle_vertices: FloatArray) -> Mesh:
    """An indexed mesh from triangle corners ``(m, 3, 3)``, sharing exactly equal positions."""
    corners = np.asarray(triangle_vertices, dtype=np.float64).reshape(-1, 3)
    unique, inverse = np.unique(corners, axis=0, return_inverse=True)
    return Mesh(unique, inverse.reshape(-1, 3).astype(np.int64))


@dataclass(frozen=True)
class TopologyReport:
    """Counts that decide whether a mesh bounds a solid with outward orientation.

    ``closed_and_oriented`` holds when every directed edge occurs exactly once and its reverse
    occurs too: then every edge has exactly two triangles, traversed in opposite directions.
    """

    triangles: int
    degenerate_triangles: int
    repeated_directed_edges: int
    unmatched_directed_edges: int

    @property
    def closed_and_oriented(self) -> bool:
        return (
            self.degenerate_triangles == 0
            and self.repeated_directed_edges == 0
            and self.unmatched_directed_edges == 0
        )


def topology(mesh: Mesh) -> TopologyReport:
    """Edge-use counts of ``mesh``; see :class:`TopologyReport`."""
    tris = mesh.triangles
    degenerate = int(
        np.count_nonzero(
            (tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) | (tris[:, 2] == tris[:, 0])
        )
    )
    starts = tris.reshape(-1)
    ends = tris[:, [1, 2, 0]].reshape(-1)
    count = np.int64(len(mesh.vertices))
    keys = starts * count + ends
    unique, uses = np.unique(keys, return_counts=True)
    repeated = int(np.count_nonzero(uses > 1))
    reverse = ends * count + starts
    unmatched = int(np.count_nonzero(~np.isin(reverse, unique)))
    return TopologyReport(len(tris), degenerate, repeated, unmatched)
