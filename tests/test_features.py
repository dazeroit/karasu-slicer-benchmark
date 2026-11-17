"""Feature metrics on synthetic slicer outputs of the feature plate (defect injection)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import ndimage

from kbench.geometry.mesh import topology
from kbench.geometry.primitives import slotted, washer
from kbench.geometry.raster import Panel
from kbench.metrics.features import equivalent_diameter, mid_layers, smallest_resolved
from kbench.metrics.stack import ArrayStack, analyze_stack
from kbench.models import CatalogError, build_model, default_catalog_path, load_catalog
from kbench.reference import Layer, full_panel, model_window, reference_layer, uniform_schedule

PANEL = Panel(resolution_x=1000, resolution_y=700, pitch_x_mm=0.05, pitch_y_mm=0.05)
LAYER_HEIGHT_MM = 0.25


@pytest.fixture(scope="module")
def plate():
    specs = {spec.id: spec for spec in load_catalog(default_catalog_path())}
    return build_model(specs["feature-plate"])


@pytest.fixture(scope="module")
def layers(plate):
    return uniform_schedule(float(plate.mesh.vertices[:, 2].max()), LAYER_HEIGHT_MM)


def render(plate, layers, grey: bool) -> list[np.ndarray]:
    window = model_window(plate.mesh, PANEL)
    images = []
    for layer in layers:
        cover = full_panel(PANEL, window, reference_layer(plate.mesh, PANEL, window, layer))
        values = cover if grey else (cover >= 0.5).astype(np.float64)
        images.append(np.rint(values * 255).astype(np.uint8))
    return images


def by_body(result) -> dict:
    return {feature["body"]: feature for feature in result["features"]}


def test_washer_and_slotted_are_closed_solids() -> None:
    for segments in (8, 16, 32, 7):
        mesh = washer(4.0, 0.5, segments, 2.0)
        assert topology(mesh).closed_and_oriented
        hole = segments / 2 * 0.25 * math.sin(2 * math.pi / segments)
        assert mesh.signed_volume() == pytest.approx((16.0 - hole) * 2.0, rel=1e-12)
    assert topology(slotted((4.0, 6.0), 0.2, 4.0, 2.0)).closed_and_oriented


def test_feature_metadata_is_in_model_coordinates(plate) -> None:
    features = {body.name: body.feature for body in plate.bodies}
    assert len(features) == 32
    pin = features["pin-0.50"]
    assert pin["kind"] == "pin"
    assert pin["nominal_mm"] == 0.5
    assert pin["reference_mm"] < 0.5  # The 32-gon is inside its circle.
    hole_centre = features["hole-1.00"]["centre_mm"]
    triangles = plate.body_triangles("hole-1.00")
    used = plate.mesh.vertices[np.unique(plate.mesh.triangles[triangles])]
    assert hole_centre == pytest.approx(((used.min(0) + used.max(0)) / 2)[:2].tolist(), abs=1e-5)


def test_exact_rendering_measures_the_reference(plate, layers) -> None:
    result = analyze_stack(plate, PANEL, ArrayStack(render(plate, layers, grey=True), layers))
    features = by_body(result)
    for name, feature in features.items():
        assert feature["layers"] >= 4  # 2 mm bodies: 8 layers of 0.25 mm, 2 left out at each end.
        if feature["kind"] in ("pin", "wall", "slot"):
            # Area-based sizes are exact up to 8-bit grey quantisation.
            assert feature["measured_mm"] == pytest.approx(feature["reference_mm"], abs=0.006), name
    # Holes count whole empty pixels: within a pixel of the reference once they are open.
    assert features["hole-1.00"]["measured_mm"] == pytest.approx(
        features["hole-1.00"]["reference_mm"], abs=0.05
    )


def test_binary_slicer_resolves_features_from_a_pixel_up(plate, layers) -> None:
    result = analyze_stack(plate, PANEL, ArrayStack(render(plate, layers, grey=False), layers))
    features = by_body(result)
    smallest = result["features_smallest_resolved"]
    # Features of two pixels and more print or stay open at 0.05 mm pixels.
    assert smallest["pin"] <= 0.1
    assert smallest["wall"] <= 0.1
    assert smallest["slot"] <= 0.1
    assert smallest["hole"] <= 0.15
    assert features["wall-0.50"]["measured_mm"] == pytest.approx(0.5, abs=0.05)


def test_one_pixel_growth_closes_small_gaps(plate, layers) -> None:
    images = [
        (ndimage.binary_dilation(image >= 128) * 255).astype(np.uint8)
        for image in render(plate, layers, grey=False)
    ]
    result = analyze_stack(plate, PANEL, ArrayStack(images, layers))
    features = by_body(result)
    # Positives grow by about two pixels, negatives shrink by about two.
    assert features["wall-0.50"]["error_mm"] == pytest.approx(0.1, abs=0.03)
    assert features["pin-1.00"]["error_mm"] == pytest.approx(0.1, abs=0.04)
    assert features["slot-1.00"]["error_mm"] == pytest.approx(-0.1, abs=0.03)
    assert features["hole-1.00"]["error_mm"] < -0.05
    assert not features["slot-0.05"]["resolved"]
    assert not features["hole-0.10"]["resolved"]


def test_helpers() -> None:
    assert equivalent_diameter(math.pi) == pytest.approx(2.0)
    assert equivalent_diameter(-1.0) == 0.0
    layers = [Layer(i, i * 0.5, 0.5) for i in range(10)]
    assert mid_layers(layers, 0.0, 3.0) == [2, 3]  # Six layers inside, two left out at each end.
    features = [
        {"kind": "pin", "nominal_mm": 0.1, "resolved": True},
        {"kind": "pin", "nominal_mm": 0.2, "resolved": False},
        {"kind": "pin", "nominal_mm": 0.3, "resolved": True},
    ]
    # 0.1 printed but 0.2 did not: the smallest size from which every larger one printed is 0.3.
    assert smallest_resolved(features) == {"pin": 0.3}


def test_feature_needs_its_shape(tmp_path) -> None:
    path = tmp_path / "catalog.toml"
    path.write_text(
        '[[models]]\nid = "a"\n'
        'bodies = [{ name = "b", feature = "pin", shape = "box", size_mm = [1, 1, 1] }]\n',
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="feature 'pin' needs shape 'prism'"):
        load_catalog(path)
