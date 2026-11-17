"""Defect injection: synthetic slicer outputs with known defects, and what the metrics report.

The "slicer" here renders the exact reference (independently checked against polygon clipping
in ``test_section_raster.py``) and then damages it in one known way per test.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from scipy import ndimage

from kbench.geometry.mesh import Mesh
from kbench.geometry.raster import Panel
from kbench.metrics import orientation as orient
from kbench.metrics.stack import AnalysisError, ArrayStack, analyze_stack, summarize
from kbench.models import BuiltModel, build_model, default_catalog_path, load_catalog
from kbench.reference import full_panel, model_window, reference_layer, uniform_schedule

PANEL = Panel(resolution_x=300, resolution_y=200, pitch_x_mm=0.2, pitch_y_mm=0.2)
LAYER_HEIGHT_MM = 0.25


@pytest.fixture(scope="module")
def plate() -> BuiltModel:
    specs = {spec.id: spec for spec in load_catalog(default_catalog_path())}
    return build_model(specs["accuracy-plate"])


@pytest.fixture(scope="module")
def layers(plate: BuiltModel):
    return uniform_schedule(float(plate.mesh.vertices[:, 2].max()), LAYER_HEIGHT_MM)


def render(
    model: BuiltModel,
    layers,
    *,
    sample_fraction: float = 0.5,
    mesh: Mesh | None = None,
    grey: Callable[[np.ndarray], np.ndarray] | None = None,
) -> list[np.ndarray]:
    """Full canonical 8-bit images; binary unless ``grey`` maps coverage to [0, 1]."""
    mesh = model.mesh if mesh is None else mesh
    window = model_window(mesh, PANEL)
    images = []
    for layer in layers:
        cover = full_panel(
            PANEL,
            window,
            reference_layer(mesh, PANEL, window, layer, sample_fraction=sample_fraction),
        )
        values = (cover >= 0.5).astype(np.float64) if grey is None else grey(cover)
        images.append(np.rint(values * 255.0).astype(np.uint8))
    return images


@pytest.fixture(scope="module")
def perfect_images(plate: BuiltModel, layers) -> list[np.ndarray]:
    return render(plate, layers)


@pytest.fixture(scope="module")
def perfect(plate: BuiltModel, layers, perfect_images) -> dict:
    return analyze_stack(plate, PANEL, ArrayStack(perfect_images, layers))


def body(result: dict, name: str) -> dict:
    return next(item for item in result["bodies"] if item["name"] == name)


def test_perfect_binary_slicer(perfect: dict, layers) -> None:
    assert perfect["kind"] == "stack_metrics"
    assert perfect["layer_count"] == len(layers)
    assert perfect["orientation"]["stored"] == "identity"
    assert not perfect["orientation"]["ambiguous"]
    dx_px, dy_px = perfect["placement"]["offset_px"]
    assert abs(dx_px) < 0.05
    assert abs(dy_px) < 0.05
    assert perfect["summary"]["iou"]["min"] > 0.98
    assert perfect["summary"]["boundary_max_mm"]["max"] <= PANEL.pitch_x_mm + 1e-9
    # Not zero: the cube's and the L's edges along X lie exactly on pixel centres here, and a
    # binary slicer that keeps coverage >= 0.5 adds that half pixel along all of them (+2 % of
    # those bodies' areas, about +0.9 % of the plate).
    assert 0.0 < perfect["volume"]["error_vs_reference_pct"] < 1.5
    assert perfect["summary"]["stray_area_mm2"]["max"] == 0.0
    assert perfect["height"]["error_mm"] == pytest.approx(0.0, abs=LAYER_HEIGHT_MM)
    assert body(perfect, "sphere")["z_phase"]["phase"] == pytest.approx(0.5, abs=0.1)
    # On a cone a Z shift and an outline offset add the same area: no phase (BD-023).
    cone = body(perfect, "cone")["z_phase"]
    assert cone["phase"] is None
    assert "outline offset" in cone["reason"]
    for name in ("cube", "cylinder", "l"):
        assert body(perfect, name)["z_phase"]["phase"] is None
    # Binary rounding moves outlines by well under half a pixel on average.
    for item in perfect["bodies"]:
        assert abs(item["z_phase"]["outline_offset_mm"]) < PANEL.pitch_x_mm / 2


@pytest.mark.parametrize("name", ["mirror_x", "mirror_y", "rotate_180"])
def test_stored_orientation_is_found_and_undone(
    plate, layers, perfect_images, perfect, name: str
) -> None:
    stored = [orient.apply(image, name).copy() for image in perfect_images]
    result = analyze_stack(plate, PANEL, ArrayStack(stored, layers))
    assert result["orientation"]["stored"] == name
    assert not result["orientation"]["ambiguous"]
    assert result["layers"]["iou"] == pytest.approx(perfect["layers"]["iou"], abs=1e-9)


def test_transposed_panel_limits_the_candidates(plate, layers, perfect_images) -> None:
    stored = [orient.apply(image, "rotate_90").copy() for image in perfect_images]
    result = analyze_stack(plate, PANEL, ArrayStack(stored, layers))
    assert result["orientation"]["stored"] == "rotate_90"
    assert result["orientation"]["candidates"] == [
        "rotate_90",
        "rotate_270",
        "transpose",
        "antitranspose",
    ]


def test_placement_offset_is_measured_and_removed(plate, layers, perfect_images, perfect) -> None:
    shifted = [np.roll(image, (-2, 3), axis=(0, 1)) for image in perfect_images]  # Up 2, right 3.
    result = analyze_stack(plate, PANEL, ArrayStack(shifted, layers))
    dx_mm, dy_mm = result["placement"]["offset_mm"]
    assert dx_mm == pytest.approx(0.6, abs=0.01)
    assert dy_mm == pytest.approx(0.4, abs=0.01)
    assert result["summary"]["iou"]["min"] == pytest.approx(
        perfect["summary"]["iou"]["min"], abs=0.01
    )


def test_one_pixel_growth(plate, layers, perfect_images, perfect) -> None:
    grown = [
        (ndimage.binary_dilation(image >= 128) * 255).astype(np.uint8) for image in perfect_images
    ]
    result = analyze_stack(plate, PANEL, ArrayStack(grown, layers))
    assert result["volume"]["error_vs_reference_pct"] > 5.0
    assert (
        result["summary"]["boundary_mean_mm"]["mean"]
        > perfect["summary"]["boundary_mean_mm"]["mean"] + 0.1
    )
    assert result["summary"]["width_error_mm"]["mean"] == pytest.approx(
        2 * PANEL.pitch_x_mm, abs=0.1
    )
    assert abs(result["placement"]["offset_px"][0]) < 0.1  # Symmetric growth does not move it.


def test_missing_layer(plate, layers, perfect_images, perfect) -> None:
    damaged = list(perfect_images)
    damaged[10] = np.zeros_like(damaged[10])
    result = analyze_stack(plate, PANEL, ArrayStack(damaged, layers))
    assert result["layers"]["iou"][10] == 0.0
    assert result["layers"]["area_error_mm2"][10] == pytest.approx(
        -result["layers"]["reference_area_mm2"][10]
    )
    assert result["summary"]["iou"]["worst_layer"] == 10
    lost = result["layers"]["measured_area_mm2"]
    assert perfect["layers"]["measured_area_mm2"][10] > 0
    assert lost[10] == 0.0


# Exactly 0 or 1 would put sampling planes on the L's top face, which the reference refuses as
# ambiguous; 0.02 and 0.98 sample next to the layer boundaries instead. 1.5 is a schedule one
# layer too high. Grey-level rendering tests the estimator itself.
@pytest.mark.parametrize("fraction", [0.02, 0.25, 0.98, 1.5])
def test_z_sampling_phase(plate, layers, fraction: float) -> None:
    images = render(plate, layers, sample_fraction=fraction, grey=lambda cover: cover)
    result = analyze_stack(plate, PANEL, ArrayStack(images, layers))
    sphere = body(result, "sphere")["z_phase"]
    assert sphere["phase"] == pytest.approx(fraction, abs=0.01)
    assert abs(sphere["outline_offset_mm"]) < 0.002
    assert body(result, "cone")["z_phase"]["phase"] is None


def test_z_sampling_phase_of_a_binary_slicer(plate, layers) -> None:
    # Binarisation at five pixels per millimetre adds area noise: a few hundredths of a layer.
    result = analyze_stack(
        plate, PANEL, ArrayStack(render(plate, layers, sample_fraction=0.25), layers)
    )
    assert body(result, "sphere")["z_phase"]["phase"] == pytest.approx(0.25, abs=0.08)


def test_xy_scale_error(plate, layers) -> None:
    scaled = Mesh(plate.mesh.vertices * [1.05, 1.05, 1.0], plate.mesh.triangles)
    # Grey-level rendering: no binarisation ties, so the area ratio is exactly 1.05².
    images = render(plate, layers, mesh=scaled, grey=lambda cover: cover)
    result = analyze_stack(plate, PANEL, ArrayStack(images, layers))
    assert result["volume"]["error_vs_reference_pct"] == pytest.approx(10.25, abs=0.1)


def test_outline_growth_is_measured_and_not_taken_for_a_z_shift(
    plate, layers, perfect_images, perfect
) -> None:
    exact = analyze_stack(plate, PANEL, ArrayStack(render(plate, layers, grey=lambda c: c), layers))
    for item in exact["bodies"]:
        assert abs(item["z_phase"]["outline_offset_mm"]) < 0.002  # Exact coverage: no offset.
    dilated = [
        (ndimage.binary_dilation(image >= 128) * 255).astype(np.uint8) for image in perfect_images
    ]
    result = analyze_stack(plate, PANEL, ArrayStack(dilated, layers))
    assert body(result, "sphere")["z_phase"]["phase"] == pytest.approx(0.5, abs=0.1)
    for name in ("cube", "cylinder", "sphere"):
        # One pixel (0.2 mm) more than the binary slicer it was grown from.
        grown = body(result, name)["z_phase"]["outline_offset_mm"]
        before = body(perfect, name)["z_phase"]["outline_offset_mm"]
        assert grown - before == pytest.approx(0.2, abs=0.02)


def test_anti_aliasing_fidelity(plate, layers, perfect) -> None:
    exact = analyze_stack(plate, PANEL, ArrayStack(render(plate, layers, grey=lambda c: c), layers))
    gamma = analyze_stack(plate, PANEL, ArrayStack(render(plate, layers, grey=np.sqrt), layers))
    exact_mae = exact["summary"]["edge_coverage_mae"]["mean"]
    assert exact_mae < 0.01  # 8-bit quantisation and sub-pixel registration only.
    assert perfect["summary"]["edge_coverage_mae"]["mean"] > 0.15  # Binary edges.
    assert gamma["summary"]["edge_coverage_mae"]["mean"] > 0.05
    assert abs(exact["volume"]["error_vs_reference_pct"]) < 0.1


def test_stray_material_is_reported(plate, layers, perfect_images) -> None:
    damaged = [image.copy() for image in perfect_images]
    damaged[3][2:4, 2:4] = 255  # A speck in a panel corner, far from the model.
    result = analyze_stack(plate, PANEL, ArrayStack(damaged, layers))
    assert result["layers"]["stray_area_mm2"][3] == pytest.approx(4 * PANEL.pixel_area_mm2)
    assert result["summary"]["stray_area_mm2"]["worst_layer"] == 3


def test_unusable_stacks_are_refused(plate, layers, perfect_images) -> None:
    with pytest.raises(AnalysisError, match="do not fit"):
        analyze_stack(plate, PANEL, ArrayStack([image[:, :-1] for image in perfect_images], layers))
    with pytest.raises(AnalysisError, match="no material"):
        analyze_stack(
            plate, PANEL, ArrayStack([np.zeros_like(image) for image in perfect_images], layers)
        )
    with pytest.raises(AnalysisError, match="no layers"):
        analyze_stack(plate, PANEL, ArrayStack([], []))


def test_summary() -> None:
    assert summarize("area_error_mm2", [1.0, None, -3.0, 2.0]) == {
        "count": 3,
        "mean": 0.0,
        "min": -3.0,
        "max": 2.0,
        "worst_layer": 2,
        "worst": -3.0,
    }
    assert summarize("iou", [0.9, 0.5, None])["worst_layer"] == 1
    assert summarize("iou", [None])["count"] == 0
