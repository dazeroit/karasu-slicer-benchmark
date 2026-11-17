from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.spatial import ConvexHull

from kbench.geometry import GeometryError
from kbench.geometry.mesh import merge
from kbench.geometry.primitives import box, cone, extrude, icosphere, prism
from kbench.geometry.raster import Panel, Window, coverage, window_around
from kbench.geometry.section import (
    DegenerateSectionError,
    area_profile,
    plane_segments,
    segments_area,
)


def regular_polygon_area(radius: float, segments: int) -> float:
    return segments / 2.0 * radius**2 * math.sin(2.0 * math.pi / segments)


def square_segments(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    """Counter-clockwise square as section segments."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return np.array([[*corners[i], *corners[(i + 1) % 4]] for i in range(4)], dtype=np.float64)


def clipped_area(
    polygon: list[tuple[float, float]], x0: float, y0: float, x1: float, y1: float
) -> float:
    """Area of a convex polygon inside an axis-aligned rectangle (Sutherland-Hodgman).

    An implementation independent of the rasterizer's accumulation method.
    """

    def clip(points: list[tuple[float, float]], inside, intersect) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for i, current in enumerate(points):
            previous = points[i - 1]
            if inside(current):
                if not inside(previous):
                    result.append(intersect(previous, current))
                result.append(current)
            elif inside(previous):
                result.append(intersect(previous, current))
        return result

    def at_x(x):
        return lambda p, q: (x, p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0]))

    def at_y(y):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]), y)

    points = polygon
    for inside, intersect in (
        (lambda p: p[0] >= x0, at_x(x0)),
        (lambda p: p[0] <= x1, at_x(x1)),
        (lambda p: p[1] >= y0, at_y(y0)),
        (lambda p: p[1] <= y1, at_y(y1)),
    ):
        if not points:
            return 0.0
        points = clip(points, inside, intersect)
    if len(points) < 3:
        return 0.0
    xs, ys = np.array(points).T
    return float((xs * np.roll(ys, -1) - np.roll(xs, -1) * ys).sum() / 2.0)


# Sections ---------------------------------------------------------------------------------


def test_box_section_is_counter_clockwise_with_exact_area() -> None:
    segments = plane_segments(box((20.0, 10.0, 5.0)), 2.5)
    assert len(segments) == 8  # Two triangles per side wall.
    assert segments_area(segments) == pytest.approx(200.0, rel=1e-15)


def test_prism_and_cone_sections() -> None:
    assert segments_area(plane_segments(prism(5.0, 64, 10.0), 3.3)) == pytest.approx(
        regular_polygon_area(5.0, 64), rel=1e-12
    )
    mesh = cone(8.0, 128, 16.0)
    for z in (0.5, 4.0, 12.25):
        expected = regular_polygon_area(8.0, 128) * (1.0 - z / 16.0) ** 2
        assert segments_area(plane_segments(mesh, z)) == pytest.approx(expected, rel=1e-12)


def test_sphere_section_is_close_to_the_circle() -> None:
    mesh = icosphere(10.0, 5)
    centre = (mesh.vertices[:, 2].min() + mesh.vertices[:, 2].max()) / 2.0
    for dz in (-6.0, 0.0, 4.5):
        circle = math.pi * (100.0 - dz * dz)
        assert segments_area(plane_segments(mesh, centre + dz)) == pytest.approx(circle, rel=6e-3)


def test_face_in_plane_is_refused_but_vertex_on_plane_is_not() -> None:
    mesh = box((2.0, 2.0, 2.0))
    with pytest.raises(DegenerateSectionError):
        plane_segments(mesh, 0.0)
    with pytest.raises(DegenerateSectionError):
        plane_segments(mesh, 2.0)
    apex = cone(3.0, 16, 4.0)
    assert segments_area(plane_segments(apex, 4.0)) == 0.0  # The apex alone: no area.
    sphere = icosphere(5.0, 2)
    assert segments_area(plane_segments(sphere, 0.0)) == 0.0  # Bottom vertices, no face.


def test_area_profile_matches_single_planes() -> None:
    mesh = merge([cone(8.0, 64, 16.0), icosphere(4.0, 3).translated((20.0, 0.0, 0.0))])
    heights = np.linspace(0.05, 15.95, 37)
    expected = [segments_area(plane_segments(mesh, float(z))) for z in heights]
    assert area_profile(mesh, heights) == pytest.approx(expected, rel=1e-12)


def test_triangle_subset_selects_a_body() -> None:
    first = prism(3.0, 32, 6.0)
    second = box((4.0, 4.0, 6.0)).translated((10.0, 0.0, 0.0))
    mesh = merge([first, second])
    subset = np.arange(len(first.triangles), len(mesh.triangles))
    assert segments_area(plane_segments(mesh, 2.0, subset)) == pytest.approx(16.0, rel=1e-15)


# Coverage ---------------------------------------------------------------------------------

PANEL = Panel(resolution_x=40, resolution_y=30, pitch_x_mm=0.1, pitch_y_mm=0.1)
FULL = Window(0, 0, 30, 40)


def test_pixel_aligned_square_covers_whole_pixels() -> None:
    # Columns 25..29 and rows 5..9 from the top: x from 0.5 to 1.0 mm, y from 0.5 to 1.0 mm.
    image = coverage(square_segments(0.5, 0.5, 1.0, 1.0), PANEL, FULL)
    expected = np.zeros((30, 40))
    expected[5:10, 25:30] = 1.0
    assert np.allclose(image, expected, atol=1e-12)


def test_quarter_pixel_offset_gives_exact_fractions() -> None:
    image = coverage(square_segments(0.025, 0.025, 0.225, 0.225), PANEL, FULL)
    # The square spans columns 20.25..22.25 and rows 12.75..14.75 (from the top).
    assert image.sum() == pytest.approx(4.0, abs=1e-12)
    assert image[12, 20] == pytest.approx(0.25 * 0.75, abs=1e-12)  # Top-left corner pixel.
    assert image[13, 21] == pytest.approx(1.0, abs=1e-12)
    assert image[14, 22] == pytest.approx(0.75 * 0.25, abs=1e-12)  # Bottom-right corner pixel.
    assert image[13, 20] == pytest.approx(0.75, abs=1e-12)


def test_canonical_image_has_back_right_at_top_right() -> None:
    image = coverage(square_segments(1.5, 1.0, 1.9, 1.4), PANEL, FULL)
    rows, cols = np.nonzero(image)
    assert rows.max() < 15  # +Y is up, towards row 0.
    assert cols.min() >= 20  # +X is right.


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_coverage_equals_polygon_clipping(seed: int) -> None:
    rng = np.random.default_rng(seed)
    angles = np.sort(rng.uniform(0.0, 2.0 * math.pi, 7))
    radii = rng.uniform(0.6, 1.2, 7)
    centre = rng.uniform(-0.3, 0.3, 2)
    polygon = [
        (centre[0] + r * math.cos(a), centre[1] + r * math.sin(a))
        for r, a in zip(radii, angles, strict=True)
    ]
    # Keep the convex hull so the independent clipper applies.
    hull = ConvexHull(np.array(polygon))
    polygon = [polygon[i] for i in hull.vertices]  # Counter-clockwise.
    segments = np.array(
        [[*polygon[i], *polygon[(i + 1) % len(polygon)]] for i in range(len(polygon))]
    )
    image = coverage(segments, PANEL, FULL)
    for row in range(30):
        for col in range(40):
            x0 = (col - 20) * 0.1
            y1 = (15 - row) * 0.1
            expected = clipped_area(polygon, x0, y1 - 0.1, x0 + 0.1, y1) / 0.01
            assert image[row, col] == pytest.approx(expected, abs=1e-9)


def test_total_coverage_equals_section_area() -> None:
    panel = Panel(400, 300, 0.05, 0.05)
    for mesh, z in (
        (prism(4.0, 64, 5.0), 2.0),
        (cone(5.0, 128, 8.0), 3.1),
        (icosphere(6.0, 4), 5.7),
    ):
        segments = plane_segments(mesh, z)
        low, high = mesh.bounds()
        window = window_around(panel, (low[0], low[1]), (high[0], high[1]), 2)
        assert coverage(segments, panel, window).sum() * panel.pixel_area_mm2 == pytest.approx(
            segments_area(segments), rel=1e-12
        )


def test_window_crop_and_offset() -> None:
    segments = plane_segments(prism(0.7, 32, 1.0), 0.5)
    full = coverage(segments, PANEL, FULL)
    part = Window(8, 12, 12, 15)
    assert np.allclose(coverage(segments, PANEL, part), part.take(full), atol=1e-12)
    moved = coverage(
        segments, PANEL, FULL, offset_mm=(0.2, -0.1)
    )  # Two columns right, one row down.
    assert np.allclose(moved[1:, 2:], full[:-1, :-2], atol=1e-12)


def test_inverted_or_overlapping_material_is_refused() -> None:
    segments = square_segments(0.0, 0.0, 0.5, 0.5)
    with pytest.raises(GeometryError, match="overlap or are inverted"):
        coverage(segments[:, [2, 3, 0, 1]], PANEL, FULL)
    with pytest.raises(GeometryError, match="overlap or are inverted"):
        coverage(np.concatenate((segments, segments)), PANEL, FULL)


def test_holes_are_subtracted() -> None:
    outer = square_segments(-1.0, -1.0, 1.0, 1.0)
    hole = square_segments(-0.5, -0.5, 0.5, 0.5)[:, [2, 3, 0, 1]][::-1]  # Clockwise.
    image = coverage(np.concatenate((outer, hole)), PANEL, FULL)
    assert image.sum() * 0.01 == pytest.approx(4.0 - 1.0, abs=1e-12)


def test_extruded_l_section_on_panel() -> None:
    l_shape = np.array([[0, 0], [12, 0], [12, 4], [4, 4], [4, 20], [0, 20]], dtype=np.float64) / 10
    mesh = extrude(l_shape - [0.6, 1.0], 0.5)
    image = coverage(plane_segments(mesh, 0.25), PANEL, FULL)
    assert image.sum() * 0.01 == pytest.approx(1.12, abs=1e-12)
