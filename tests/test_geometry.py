from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from kbench.geometry import GeometryError
from kbench.geometry.mesh import Mesh, merge, quantize_float32, topology, weld
from kbench.geometry.polygon import signed_area, triangulate
from kbench.geometry.primitives import box, cone, extrude, icosphere, prism, regular_polygon
from kbench.geometry.stl import read_binary_stl, write_binary_stl
from kbench.provenance import sha256_file

L_SHAPE = np.array([[0, 0], [12, 0], [12, 4], [4, 4], [4, 20], [0, 20]], dtype=np.float64)


def regular_polygon_area(radius: float, segments: int) -> float:
    return segments / 2.0 * radius**2 * math.sin(2.0 * math.pi / segments)


def test_box_is_closed_with_exact_volume() -> None:
    mesh = box((20.0, 10.0, 5.0))
    assert topology(mesh).closed_and_oriented
    assert mesh.signed_volume() == pytest.approx(1000.0, rel=1e-15)
    low, high = mesh.bounds()
    assert low.tolist() == [-10.0, -5.0, 0.0]
    assert high.tolist() == [10.0, 5.0, 5.0]


@pytest.mark.parametrize("segments", [3, 7, 64, 512])
def test_prism_volume(segments: int) -> None:
    mesh = prism(5.0, segments, 10.0)
    assert topology(mesh).closed_and_oriented
    assert mesh.signed_volume() == pytest.approx(
        regular_polygon_area(5.0, segments) * 10.0, rel=1e-12
    )


def test_cone_volume() -> None:
    mesh = cone(8.0, 128, 16.0)
    assert topology(mesh).closed_and_oriented
    assert mesh.signed_volume() == pytest.approx(
        regular_polygon_area(8.0, 128) * 16.0 / 3.0, rel=1e-12
    )


@pytest.mark.parametrize("subdivisions", [0, 1, 3, 5])
def test_icosphere(subdivisions: int) -> None:
    mesh = icosphere(10.0, subdivisions)
    assert len(mesh.triangles) == 20 * 4**subdivisions
    assert topology(mesh).closed_and_oriented
    assert mesh.vertices[:, 2].min() == 0.0
    centre = mesh.vertices.mean(axis=0)
    radii = np.linalg.norm(mesh.vertices - [0.0, 0.0, centre[2]], axis=1)
    assert radii == pytest.approx(10.0, rel=1e-12)
    # Inscribed polyhedra approach the sphere from below.
    assert 0.0 < mesh.signed_volume() < 4.0 / 3.0 * math.pi * 1000.0


def test_icosphere_converges_to_the_sphere() -> None:
    sphere = 4.0 / 3.0 * math.pi * 1000.0
    assert icosphere(10.0, 5).signed_volume() == pytest.approx(sphere, rel=2e-3)


def test_extruded_l_is_closed_with_exact_volume() -> None:
    mesh = extrude(L_SHAPE, 2.0)
    assert topology(mesh).closed_and_oriented
    assert mesh.signed_volume() == pytest.approx(112.0 * 2.0, rel=1e-15)


def test_triangulation_covers_the_polygon() -> None:
    triangles = triangulate(L_SHAPE)
    assert len(triangles) == len(L_SHAPE) - 2
    areas = [signed_area(L_SHAPE[tri]) for tri in triangles]
    assert all(area > 0 for area in areas)
    assert sum(areas) == pytest.approx(signed_area(L_SHAPE), rel=1e-15)


def test_triangulation_refuses_bad_polygons() -> None:
    with pytest.raises(GeometryError, match="counter-clockwise"):
        triangulate(L_SHAPE[::-1])
    bowtie = np.array([[0, 0], [2, 2], [2, 0], [0, 2]], dtype=np.float64)
    with pytest.raises(GeometryError):
        triangulate(np.concatenate((bowtie, [[1, 3]])))


def test_regular_polygon_rejects_invalid_parameters() -> None:
    with pytest.raises(GeometryError):
        regular_polygon(1.0, 2)
    with pytest.raises(GeometryError):
        regular_polygon(0.0, 8)


def test_topology_detects_open_and_inverted_meshes() -> None:
    mesh = box((1.0, 1.0, 1.0))
    opened = Mesh(mesh.vertices, mesh.triangles[1:])
    assert not topology(opened).closed_and_oriented
    assert topology(opened).unmatched_directed_edges == 3
    flipped_one = mesh.triangles.copy()
    flipped_one[0] = flipped_one[0, ::-1]
    report = topology(Mesh(mesh.vertices, flipped_one))
    assert not report.closed_and_oriented
    inverted = Mesh(mesh.vertices, mesh.triangles[:, ::-1].copy())
    assert topology(inverted).closed_and_oriented  # Consistent, but inside out:
    assert inverted.signed_volume() < 0.0


def test_merge_and_weld() -> None:
    a = box((1.0, 1.0, 1.0))
    b = a.translated((5.0, 0.0, 0.0))
    merged = merge([a, b])
    assert len(merged.triangles) == 24
    assert merged.signed_volume() == pytest.approx(2.0)
    welded = weld(merged.triangle_vertices)
    assert len(welded.vertices) == 16
    assert topology(welded).closed_and_oriented
    assert welded.signed_volume() == pytest.approx(2.0)


def test_quantize_gives_float32_values() -> None:
    values = np.array([0.1, 1.0 / 3.0, 12345.678])
    quantized = quantize_float32(values)
    assert np.array_equal(quantized.astype(np.float32).astype(np.float64), quantized)
    assert np.allclose(quantized, values, rtol=1e-7)


def test_mesh_validation() -> None:
    with pytest.raises(GeometryError):
        Mesh(np.zeros((3, 2)), np.zeros((1, 3), dtype=np.int64))
    with pytest.raises(GeometryError):
        Mesh(np.zeros((3, 3)), np.array([[0, 1, 3]], dtype=np.int64))


def test_stl_round_trip_is_exact_and_deterministic(tmp_path: Path) -> None:
    mesh = icosphere(7.5, 2).translated((1.0, -2.0, 0.0))
    first, second = tmp_path / "a.stl", tmp_path / "b.stl"
    write_binary_stl(first, mesh, "kbench test")
    write_binary_stl(second, mesh, "kbench test")
    assert sha256_file(first) == sha256_file(second)
    assert first.stat().st_size == 84 + 50 * len(mesh.triangles)
    corners = read_binary_stl(first)
    assert np.array_equal(corners, mesh.triangle_vertices)
    assert weld(corners).signed_volume() == pytest.approx(mesh.signed_volume(), rel=1e-12)


def test_stl_refuses_unquantised_vertices_and_long_headers(tmp_path: Path) -> None:
    mesh = box((1.0, 1.0, 1.0))
    unquantised = Mesh(mesh.vertices + 0.1, mesh.triangles)
    with pytest.raises(GeometryError, match="float32"):
        write_binary_stl(tmp_path / "x.stl", unquantised, "x")
    with pytest.raises(GeometryError, match="80 bytes"):
        write_binary_stl(tmp_path / "x.stl", mesh, "x" * 81)


def test_stl_reader_refuses_wrong_sizes(tmp_path: Path) -> None:
    path = tmp_path / "bad.stl"
    path.write_bytes(b"solid ascii\nfacet normal 0 0 1\n" + b" " * 60)
    with pytest.raises(GeometryError, match="ASCII"):
        read_binary_stl(path)
    path.write_bytes(b"\0" * 10)
    with pytest.raises(GeometryError, match="too short"):
        read_binary_stl(path)
