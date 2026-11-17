"""Analysis of a whole measured layer stack against the reference.

The steps, all deterministic:

1. **Stored pass.** Each measured layer (as stored by the slicer) adds to a union silhouette and
   to coverage-weighted centroid sums.
2. **Nominal reference.** The reference is rasterised at the nominal placement (the model's
   bounding box centred on the panel) for its silhouette and centroid.
3. **Orientation.** The orientation of the stored images is estimated from the silhouettes,
   among the orientations compatible with the stored image size.
4. **Placement.** One translation, from the whole stack's centroid, registers measurement and
   reference; it is reported as the placement offset, so per-layer drift is never absorbed.
5. **Comparison pass.** Each measured layer is brought to the canonical orientation and compared
   with the reference rasterised exactly at the registered placement, on a window around the
   model. Material outside the window is reported as stray area.
6. **Model and body metrics.** Volume, height, per-body areas and the Z sampling phase.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from kbench.geometry.mesh import Mesh
from kbench.geometry.raster import Panel, Window
from kbench.geometry.section import plane_segments, segments_area, segments_perimeter
from kbench.metrics import MATERIAL_THRESHOLD, features
from kbench.metrics import orientation as orient
from kbench.metrics.layers import LAYER_FIELDS, layer_metrics
from kbench.models import BuiltModel
from kbench.reference import Layer, model_window, reference_layer

# 2: z_phase fits an outline offset instead of an area scale (BD-023).
STACK_SCHEMA_VERSION = 2

# Z-phase search: candidate phases every 0.05 of a layer from one layer below the layer's bottom
# to one layer above its top (so an off-by-one-layer schedule shows as about -0.5 or 1.5), refined
# by a parabola through the best and its neighbours. The fit needs the body's area to vary over
# the fitted layers by at least this fraction of its largest value; below it, pixel noise decides
# the phase, not geometry.
PHASE_STEP = 0.05
PHASE_RANGE = (-1.0, 2.0)
PHASE_MIN_RELATIVE_VARIATION = 0.05
# The phase is reported only when at least this fraction of dA/dφ (relative norm over the fitted
# layers) is not proportional to the perimeter; on a cone it is about 1e-3 (facets), on a sphere
# about 1.
PHASE_MIN_SEPARATION = 0.05

# Registration: layers sampled for the least-squares fit (enough to average out per-layer
# rounding, few enough to keep re-rasterising cheap), the iteration cap, and the step size, in
# pixels, below which the estimate is considered stable (far below any reported precision).
REGISTRATION_LAYERS = 16
REGISTRATION_MAX_ITERATIONS = 20
REGISTRATION_TOLERANCE_PX = 1e-4


class AnalysisError(ValueError):
    """The measured stack cannot be compared with the reference."""


class LayerStack(Protocol):
    """Measured layers in the slicer's stored orientation, with their schedule."""

    @property
    def layers(self) -> Sequence[Layer]: ...

    @property
    def shape(self) -> tuple[int, int]: ...

    def image(self, index: int) -> NDArray[Any]:
        """Layer ``index`` as stored: 8-bit grey levels, or coverage in ``[0, 1]``."""
        ...


@dataclass(frozen=True)
class ArrayStack:
    """A stack held in memory (tests, small decoded stacks)."""

    images: Sequence[NDArray[Any]]
    layers: Sequence[Layer]

    @property
    def shape(self) -> tuple[int, int]:
        return self.images[0].shape if self.images else (0, 0)

    def image(self, index: int) -> NDArray[Any]:
        return self.images[index]


@dataclass(frozen=True)
class PngStack:
    """Decoded layers as 8-bit greyscale PNG files, one per layer, read when needed."""

    files: Sequence[Path]
    layers: Sequence[Layer]
    shape: tuple[int, int]

    @classmethod
    def open(cls, files: Sequence[Path], layers: Sequence[Layer]) -> PngStack:
        if len(files) != len(layers):
            raise AnalysisError(f"{len(files)} layer images for {len(layers)} layers")
        if not files:
            raise AnalysisError("the stack has no layers")
        with Image.open(files[0]) as first:
            shape = (first.height, first.width)
        return cls(tuple(files), tuple(layers), shape)

    def image(self, index: int) -> NDArray[Any]:
        with Image.open(self.files[index]) as picture:
            if picture.mode != "L":
                raise AnalysisError(
                    f"{self.files[index].name}: mode {picture.mode}, expected 8-bit grey"
                )
            if (picture.height, picture.width) != self.shape:
                raise AnalysisError(f"{self.files[index].name}: size differs from the first layer")
            return np.asarray(picture, dtype=np.uint8)


def to_coverage(image: NDArray[Any]) -> NDArray[np.float64]:
    """8-bit grey levels as ``grey / 255``; floating-point images must already be in ``[0, 1]``."""
    if image.dtype == np.uint8:
        return image.astype(np.float64) / 255.0
    values = image.astype(np.float64)
    if values.size and (values.min() < 0.0 or values.max() > 1.0):
        raise AnalysisError("floating-point layer values must lie in [0, 1]")
    return values


def take_padded(image: NDArray[Any], window: Window) -> NDArray[Any]:
    """``window`` of ``image`` (same type), with zeros where the window leaves the image."""
    out = np.zeros((window.rows, window.cols), dtype=image.dtype)
    r0, c0 = max(window.row0, 0), max(window.col0, 0)
    r1 = min(window.row0 + window.rows, image.shape[0])
    c1 = min(window.col0 + window.cols, image.shape[1])
    if r1 > r0 and c1 > c0:
        out[r0 - window.row0 : r1 - window.row0, c0 - window.col0 : c1 - window.col0] = image[
            r0:r1, c0:c1
        ]
    return out


def _full_scale(image: NDArray[Any]) -> float:
    return 255.0 if image.dtype == np.uint8 else 1.0


def _material(image: NDArray[Any]) -> NDArray[np.bool_]:
    """Material pixels: coverage ≥ 0.5, which for 8-bit grey is grey ≥ 128."""
    return image >= 128 if image.dtype == np.uint8 else image >= MATERIAL_THRESHOLD


def _weighted_sums(image: NDArray[Any]) -> tuple[float, float, float]:
    """Total coverage and its first moments along rows and columns (pixel centres)."""
    scale = _full_scale(image)
    by_row = image.sum(axis=1, dtype=np.float64) / scale
    by_col = image.sum(axis=0, dtype=np.float64) / scale
    rows = np.arange(image.shape[0]) + 0.5
    cols = np.arange(image.shape[1]) + 0.5
    return float(by_row.sum()), float(by_row @ rows), float(by_col @ cols)


def analyze_stack(model: BuiltModel, panel: Panel, stack: LayerStack) -> dict[str, Any]:
    """Every stack metric of ``stack`` against ``model`` on ``panel`` (docs/METRICS.md)."""
    mesh = model.mesh
    layers = list(stack.layers)
    if not layers:
        raise AnalysisError("the stack has no layers")
    canonical_shape = (panel.resolution_y, panel.resolution_x)
    candidates = [
        name
        for name in orient.ORIENTATIONS
        if orient.transformed_shape(canonical_shape, name) == tuple(stack.shape)
    ]
    if not candidates:
        raise AnalysisError(
            f"stored images of {stack.shape} do not fit a panel of {canonical_shape}"
        )
    pixel = panel.pixel_area_mm2

    # 1. Stored pass.
    stored_silhouette = np.zeros(stack.shape, dtype=bool)
    stored_total = stored_rows = stored_cols = 0.0
    measured_full_area: list[float] = []
    for index in range(len(layers)):
        image = stack.image(index)
        if image.shape != tuple(stack.shape):
            raise AnalysisError(f"layer {index} has size {image.shape}, not {stack.shape}")
        if image.dtype != np.uint8:
            image = to_coverage(image)
        stored_silhouette |= _material(image)
        total, rows, cols = _weighted_sums(image)
        stored_total, stored_rows, stored_cols = (
            stored_total + total,
            stored_rows + rows,
            stored_cols + cols,
        )
        measured_full_area.append(total * pixel)
    if stored_total == 0.0:
        raise AnalysisError("the measured stack holds no material")

    # 2. Nominal reference.
    nominal = model_window(mesh, panel)
    reference_silhouette = np.zeros((nominal.rows, nominal.cols), dtype=bool)
    ref_total = ref_rows = ref_cols = 0.0
    nominal_area: list[float] = []
    for layer in layers:
        image = reference_layer(mesh, panel, nominal, layer)
        reference_silhouette |= image >= MATERIAL_THRESHOLD
        total, rows, cols = _weighted_sums(image)
        ref_total, ref_rows, ref_cols = ref_total + total, ref_rows + rows, ref_cols + cols
        nominal_area.append(total)
    if ref_total == 0.0:
        raise AnalysisError("the reference holds no material in these layers")

    # 3. Orientation, among the orientations that fit the stored size.
    estimate = orient.estimate(reference_silhouette, stored_silhouette)
    best = max(
        candidates, key=lambda name: (estimate["scores"][name], -orient.ORIENTATIONS.index(name))
    )
    ranked = sorted((estimate["scores"][name] for name in candidates), reverse=True)
    margin = ranked[0] - ranked[1] if len(ranked) > 1 else 1.0
    orientation = {
        "stored": best,
        "iou": estimate["scores"][best],
        "margin": margin,
        "ambiguous": margin < orient.AMBIGUITY_MARGIN,
        "candidates": candidates,
        "scores": estimate["scores"],
    }
    to_canonical = orient.inverse(best)

    # 4. Placement: the centroid gives a start, least squares on the edges gives the answer.
    measured_centroid = orient.map_point(
        stored_rows / stored_total, stored_cols / stored_total, stack.shape, to_canonical
    )
    reference_centroid = (nominal.row0 + ref_rows / ref_total, nominal.col0 + ref_cols / ref_total)
    start_row = measured_centroid[0] - reference_centroid[0]
    start_col = measured_centroid[1] - reference_centroid[1]
    window = nominal.shifted(round(start_row), round(start_col))
    sample = _registration_layers(nominal_area)
    measured_sample = [
        to_coverage(take_padded(orient.apply(stack.image(index), to_canonical), window))
        for index in sample
    ]
    registration = register_translation(
        mesh,
        panel,
        window,
        [layers[index] for index in sample],
        measured_sample,
        (start_col * panel.pitch_x_mm, -start_row * panel.pitch_y_mm),
    )
    offset_mm = (registration["offset_mm"][0], registration["offset_mm"][1])
    d_col = offset_mm[0] / panel.pitch_x_mm
    d_row = -offset_mm[1] / panel.pitch_y_mm
    window = nominal.shifted(round(d_row), round(d_col))

    # 5. Comparison pass, with per-body areas.
    labels = body_labels(model, panel, window, offset_mm).ravel()
    body_names = [body.name for body in model.bodies]
    per_layer: dict[str, list[Any]] = {field: [] for field in (*LAYER_FIELDS, "stray_area_mm2")}
    body_measured: dict[str, list[float]] = {name: [] for name in body_names}
    feature_windows = features.measuring_windows(model, panel, offset_mm)
    feature_kinds = {body.name: body.feature["kind"] for body in model.bodies if body.feature}
    window_values: dict[str, list[float]] = {name: [] for name in feature_windows}
    for index, layer in enumerate(layers):
        canonical = orient.apply(stack.image(index), to_canonical)
        measured = to_coverage(take_padded(canonical, window))
        reference = reference_layer(mesh, panel, window, layer, offset_mm=offset_mm)
        for field, value in layer_metrics(measured, reference, panel).items():
            per_layer[field].append(value)
        per_layer["stray_area_mm2"].append(
            measured_full_area[index] - float(measured.sum()) * pixel
        )
        sums = np.bincount(labels, weights=measured.ravel(), minlength=len(body_names))
        for name, total in zip(body_names, sums, strict=True):
            body_measured[name].append(float(total) * pixel)
        for name, feature_window in feature_windows.items():
            crop = to_coverage(take_padded(canonical, feature_window))
            if feature_kinds[name] == "hole":
                value = features.equivalent_diameter(features.hole_area_mm2(crop, panel))
            else:
                band_length_mm = feature_window.rows * panel.pitch_y_mm
                value = features.empty_area_mm2(crop, panel) / band_length_mm
            window_values[name].append(value)

    reference_area = per_layer["reference_area_mm2"]
    return {
        "schema_version": STACK_SCHEMA_VERSION,
        "kind": "stack_metrics",
        "model": model.spec.id,
        "panel": {
            "resolution": [panel.resolution_x, panel.resolution_y],
            "pitch_mm": [panel.pitch_x_mm, panel.pitch_y_mm],
        },
        "layer_count": len(layers),
        "orientation": orientation,
        "placement": {
            "offset_mm": list(offset_mm),
            "offset_px": [d_col, d_row],
            "centroid_offset_px": [start_col, start_row],
            "registration": {
                key: registration[key] for key in ("iterations", "converged", "layers")
            },
        },
        "volume": _volume(mesh, layers, measured_full_area, reference_area),
        "height": _height(mesh, layers, measured_full_area, pixel),
        "layers": per_layer,
        "summary": {field: summarize(field, values) for field, values in per_layer.items()},
        "features": (
            feature_results := features.summarize(model, layers, body_measured, window_values)
        ),
        "features_smallest_resolved": features.smallest_resolved(feature_results),
        "bodies": [_body_metrics(model, name, layers, body_measured[name]) for name in body_names],
    }


def _registration_layers(nominal_area: Sequence[float]) -> list[int]:
    """Up to :data:`REGISTRATION_LAYERS` layers holding material, evenly spread."""
    occupied = [index for index, area in enumerate(nominal_area) if area > 0.0]
    if len(occupied) <= REGISTRATION_LAYERS:
        return occupied
    picks = np.rint(np.linspace(0, len(occupied) - 1, REGISTRATION_LAYERS)).astype(int)
    return sorted({occupied[pick] for pick in picks})


def register_translation(
    mesh: Mesh,
    panel: Panel,
    window: Window,
    layers: Sequence[Layer],
    measured: Sequence[NDArray[np.float64]],
    start_mm: tuple[float, float],
) -> dict[str, Any]:
    """The plate translation (mm) that best aligns the reference with the measured layers.

    It minimises the sum of squared coverage differences over ``layers`` by Gauss-Newton
    iterations (translation-only Lucas-Kanade), re-rasterising the reference exactly at each
    estimate. Unlike the centroid, this balances the misfit of every edge, so an area error that
    differs between bodies, or a rounding tie along one edge, does not pass for a displacement.
    """
    offset = np.array(start_mm, dtype=np.float64)
    pitch = np.array([panel.pitch_x_mm, panel.pitch_y_mm])
    converged = False
    iterations = 0
    while iterations < REGISTRATION_MAX_ITERATIONS:
        iterations += 1
        normal = np.zeros((2, 2))
        gradient = np.zeros(2)
        for layer, image in zip(layers, measured, strict=True):
            reference = reference_layer(
                mesh, panel, window, layer, offset_mm=(offset[0], offset[1])
            )
            d_row, d_col = np.gradient(reference)
            # Moving the model by +x mm moves the image right; by +y mm, up (towards row 0).
            jacobian = np.stack((-d_col.ravel() / pitch[0], d_row.ravel() / pitch[1]), axis=1)
            residual = (image - reference).ravel()
            normal += jacobian.T @ jacobian
            gradient += jacobian.T @ residual
        if np.linalg.det(normal) <= 0.0:
            break
        step = np.linalg.solve(normal, gradient)
        offset += step
        if np.all(np.abs(step / pitch) < REGISTRATION_TOLERANCE_PX):
            converged = True
            break
    return {
        "offset_mm": offset.tolist(),
        "iterations": iterations,
        "converged": converged,
        "layers": [layer.index for layer in layers],
    }


def body_labels(
    model: BuiltModel, panel: Panel, window: Window, offset_mm: tuple[float, float]
) -> NDArray[np.int64]:
    """For each pixel of ``window``, the index of the nearest body (by its XY bounding box).

    Measured material is attributed to the body it is nearest to, so a body that grows or moves
    keeps all its material; bodies are at least :data:`MIN_BODY_GAP_MM` apart, so the
    attribution of material that belongs to a body is never in doubt.
    """
    rows = window.row0 + np.arange(window.rows)[:, None] + 0.5
    cols = window.col0 + np.arange(window.cols)[None, :] + 0.5
    x_mm = (cols - panel.resolution_x / 2.0) * panel.pitch_x_mm
    y_mm = (panel.resolution_y / 2.0 - rows) * panel.pitch_y_mm
    distances = []
    for body in model.bodies:
        triangles = model.body_triangles(body.name)
        used = model.mesh.vertices[np.unique(model.mesh.triangles[triangles])]
        low = used.min(axis=0)[:2] + offset_mm
        high = used.max(axis=0)[:2] + offset_mm
        dx = np.maximum(np.maximum(low[0] - x_mm, x_mm - high[0]), 0.0)
        dy = np.maximum(np.maximum(low[1] - y_mm, y_mm - high[1]), 0.0)
        distances.append(np.hypot(dx, dy))
    return np.argmin(np.stack(distances), axis=0)


def _volume(
    mesh: Mesh,
    layers: Sequence[Layer],
    measured_area: Sequence[float],
    reference_area: Sequence[float],
) -> dict[str, Any]:
    heights = np.array([layer.height_mm for layer in layers])
    measured = float(np.dot(measured_area, heights))
    reference = float(np.dot(reference_area, heights))
    exact = mesh.signed_volume()
    return {
        "measured_mm3": measured,
        "reference_stack_mm3": reference,
        "mesh_mm3": exact,
        "error_vs_reference_mm3": measured - reference,
        "error_vs_reference_pct": 100.0 * (measured - reference) / reference if reference else None,
        "error_vs_mesh_pct": 100.0 * (measured - exact) / exact,
    }


def _height(
    mesh: Mesh, layers: Sequence[Layer], measured_area: Sequence[float], pixel_mm2: float
) -> dict[str, Any]:
    # A layer counts as holding material when it covers at least half a pixel in total.
    occupied = [index for index, area in enumerate(measured_area) if area >= pixel_mm2 / 2.0]
    top = float(mesh.vertices[:, 2].max())
    if not occupied:
        return {
            "measured_top_mm": None,
            "mesh_top_mm": top,
            "error_mm": None,
            "first_layer": None,
            "last_layer": None,
        }
    last = layers[occupied[-1]]
    measured_top = last.z_bottom_mm + last.height_mm
    return {
        "measured_top_mm": measured_top,
        "mesh_top_mm": top,
        "error_mm": measured_top - top,
        "first_layer": occupied[0],
        "last_layer": occupied[-1],
    }


def _body_metrics(
    model: BuiltModel, name: str, layers: Sequence[Layer], measured_area: Sequence[float]
) -> dict[str, Any]:
    triangles = model.body_triangles(name)
    mesh = model.mesh
    used_z = mesh.vertices[np.unique(mesh.triangles[triangles]), 2]
    exact_area = [
        segments_area(plane_segments(mesh, layer.plane_mm(), triangles)) for layer in layers
    ]
    heights = np.array([layer.height_mm for layer in layers])
    measured_volume = float(np.dot(measured_area, heights))
    reference_volume = float(np.dot(exact_area, heights))
    return {
        "name": name,
        "measured_volume_mm3": measured_volume,
        "reference_stack_volume_mm3": reference_volume,
        "volume_error_pct": 100.0 * (measured_volume - reference_volume) / reference_volume
        if reference_volume
        else None,
        "z_phase": z_phase(
            mesh, triangles, layers, measured_area, float(used_z.min()), float(used_z.max())
        ),
    }


def z_phase(
    mesh: Mesh,
    triangles: NDArray[np.int64],
    layers: Sequence[Layer],
    measured_area: Sequence[float],
    z_min: float,
    z_max: float,
) -> dict[str, Any]:
    """Where inside each layer the slicer sampled the body, and how far its outline moved.

    The measured body areas ``a_i`` are fitted by ``A(z_i + φ·h_i) + g·P(z_i + φ·h_i)``: the exact
    section area ``A`` at the phase ``φ`` (0 = layer bottom, 1 = layer top) plus an outline
    offset ``g`` (mm, positive when the printed outline lies outside the exact one) times the
    exact perimeter ``P``. ``φ`` is searched over :data:`PHASE_RANGE`; layers whose candidate
    planes could reach the body's bottom or top are left out.

    ``φ`` is reported only where it can be told apart from ``g``: where the change of the area
    with height is not proportional to the perimeter. On a cone it is (moving the plane and
    offsetting the outline add the same area), and on a prism the area does not change at all;
    there ``phase`` is ``None`` with the reason, and ``g`` is fitted at mid-layer sampling.
    """
    below, above = -PHASE_RANGE[0], PHASE_RANGE[1] - 1.0
    fitted = [
        index
        for index, layer in enumerate(layers)
        if layer.z_bottom_mm - below * layer.height_mm > z_min
        and layer.z_bottom_mm + (1.0 + above) * layer.height_mm < z_max
    ]
    empty = {
        "phase": None,
        "outline_offset_mm": None,
        "outline_offset_basis": None,
        "rms_mm2": None,
        "reason": "fewer than three layers to fit",
    }
    if len(fitted) < 3:
        return empty
    observed = np.array([measured_area[index] for index in fitted])

    def sections(phase: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        areas, perimeters = [], []
        for index in fitted:
            segments = plane_segments(mesh, layers[index].plane_mm(phase), triangles)
            areas.append(segments_area(segments))
            perimeters.append(segments_perimeter(segments))
        return np.array(areas), np.array(perimeters)

    def fit(area: NDArray[np.float64], perimeter: NDArray[np.float64]) -> tuple[float, float]:
        weight = float(perimeter @ perimeter)
        offset = float((observed - area) @ perimeter / weight) if weight > 0.0 else 0.0
        return offset, float(((observed - area - offset * perimeter) ** 2).sum())

    middle_area, middle_perimeter = sections(0.5)

    def mid_plane(reason: str, basis: str) -> dict[str, Any]:
        offset, rss = fit(middle_area, middle_perimeter)
        return {
            "phase": None,
            "outline_offset_mm": offset,
            "outline_offset_basis": basis,
            "rms_mm2": math.sqrt(rss / len(fitted)),
            "reason": reason,
        }

    if (
        middle_area.max() <= 0.0
        or (middle_area.max() - middle_area.min()) / middle_area.max()
        < PHASE_MIN_RELATIVE_VARIATION
    ):
        return mid_plane("the area does not vary enough with height", "mid-layer sampling")

    # Separability: the part of dA/dφ that an outline offset cannot imitate.
    step = PHASE_STEP / 2.0
    derivative = (sections(0.5 + step)[0] - sections(0.5 - step)[0]) / (2.0 * step)
    projection = derivative @ middle_perimeter / (middle_perimeter @ middle_perimeter)
    residual = derivative - projection * middle_perimeter
    separation = float(np.linalg.norm(residual) / np.linalg.norm(derivative))
    if separation < PHASE_MIN_SEPARATION:
        return mid_plane(
            "the layer height cannot be told apart from an outline offset on this body",
            "mid-layer sampling assumed",
        ) | {"separation": separation}

    phases = np.round(np.arange(PHASE_RANGE[0], PHASE_RANGE[1] + PHASE_STEP / 2, PHASE_STEP), 10)
    residuals = []
    for phase in phases:
        area, perimeter = (
            (middle_area, middle_perimeter) if phase == 0.5 else sections(float(phase))
        )
        residuals.append(fit(area, perimeter)[1])
    best = int(np.argmin(residuals))
    phase = float(phases[best])
    if 0 < best < len(phases) - 1:
        r0, r1, r2 = residuals[best - 1], residuals[best], residuals[best + 1]
        curvature = r0 - 2 * r1 + r2
        if curvature > 0:
            phase += PHASE_STEP * 0.5 * (r0 - r2) / curvature
    offset, rss = fit(*sections(phase))
    return {
        "phase": phase,
        "outline_offset_mm": offset,
        "outline_offset_basis": "fitted phase",
        "rms_mm2": math.sqrt(rss / len(fitted)),
        "reason": None,
        "separation": separation,
    }


def summarize(field: str, values: Sequence[float | None]) -> dict[str, Any]:
    """Count, mean, minimum, maximum and the worst layer of a per-layer series.

    The worst layer is the lowest value for ``iou`` and the largest absolute value otherwise.
    """
    present = [(index, value) for index, value in enumerate(values) if value is not None]
    if not present:
        return {
            "count": 0,
            "mean": None,
            "min": None,
            "max": None,
            "worst_layer": None,
            "worst": None,
        }
    numbers = np.array([value for _, value in present], dtype=np.float64)
    worst_position = int(np.argmin(numbers) if field == "iou" else np.argmax(np.abs(numbers)))
    return {
        "count": len(present),
        "mean": float(numbers.mean()),
        "min": float(numbers.min()),
        "max": float(numbers.max()),
        "worst_layer": present[worst_position][0],
        "worst": float(numbers[worst_position]),
    }
