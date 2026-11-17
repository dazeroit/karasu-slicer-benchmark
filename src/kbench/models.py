"""The test-model catalog (``models/catalog.toml``) and the builder that writes STL files.

A built model is centred on the origin in X and Y and stands on ``z = 0``; its vertices are
``float32`` values, exactly what the STL file stores. The manifest records, for each model and
each body, the triangle range, the exact volume and the bounds, so that every later metric can
refer to them without re-reading the catalog.
"""

from __future__ import annotations

import json
import math
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from kbench.geometry import GeometryError
from kbench.geometry.mesh import Mesh, merge, quantize_float32, topology
from kbench.geometry.primitives import box, cone, extrude, icosphere, prism
from kbench.geometry.stl import write_binary_stl
from kbench.provenance import sha256_file

# Changing any generator, the placement rules or the STL writer changes the files: raise this.
GENERATOR_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1

# Bodies closer than this could be bridged by a slicer's pixel rounding or compensation, and
# their per-body measurement windows (body bounds plus a margin) would overlap.
MIN_BODY_GAP_MM = 1.0

_SHAPE_KEYS: dict[str, set[str]] = {
    "box": {"size_mm"},
    "prism": {"radius_mm", "segments", "height_mm", "phase_deg"},
    "cone": {"radius_mm", "segments", "height_mm", "phase_deg"},
    "icosphere": {"radius_mm", "subdivisions"},
    "extrusion": {"polygon_mm", "height_mm"},
}
_OPTIONAL_KEYS = {"phase_deg"}
_BODY_KEYS = {"name", "shape", "at_mm"}
_MODEL_KEYS = {"id", "description", "bodies"}


class CatalogError(ValueError):
    """The catalog is malformed or describes an unusable model."""


@dataclass(frozen=True)
class BodySpec:
    name: str
    shape: str
    parameters: Mapping[str, Any]
    at_mm: tuple[float, float]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    description: str
    bodies: tuple[BodySpec, ...]


@dataclass(frozen=True)
class BuiltBody:
    name: str
    shape: str
    first_triangle: int
    triangle_count: int


@dataclass(frozen=True)
class BuiltModel:
    spec: ModelSpec
    mesh: Mesh
    bodies: tuple[BuiltBody, ...]

    def body_triangles(self, name: str) -> np.ndarray:
        """The triangle indices of the body called ``name``."""
        for body in self.bodies:
            if body.name == name:
                return np.arange(body.first_triangle, body.first_triangle + body.triangle_count)
        raise KeyError(name)


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "models" / "catalog.toml"


def load_catalog(path: Path) -> list[ModelSpec]:
    """Every model of the catalog, validated; unknown or missing keys are errors."""
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    unknown = set(document) - {"models"}
    if unknown:
        raise CatalogError(f"unknown top-level keys: {sorted(unknown)}")
    models = [_parse_model(entry) for entry in document.get("models", [])]
    ids = [model.id for model in models]
    duplicates = sorted({model_id for model_id in ids if ids.count(model_id) > 1})
    if duplicates:
        raise CatalogError(f"duplicate model ids: {duplicates}")
    return models


def _parse_model(entry: Mapping[str, Any]) -> ModelSpec:
    unknown = set(entry) - _MODEL_KEYS
    if unknown or not {"id", "bodies"} <= set(entry):
        raise CatalogError(f"model {entry.get('id')!r}: keys must be {sorted(_MODEL_KEYS)}")
    model_id = str(entry["id"])
    bodies = tuple(_parse_body(model_id, body) for body in entry["bodies"])
    if not bodies:
        raise CatalogError(f"model {model_id!r} has no bodies")
    names = [body.name for body in bodies]
    if len(set(names)) != len(names):
        raise CatalogError(f"model {model_id!r}: body names must be unique")
    return ModelSpec(model_id, str(entry.get("description", "")), bodies)


def _parse_body(model_id: str, entry: Mapping[str, Any]) -> BodySpec:
    shape = entry.get("shape")
    if shape not in _SHAPE_KEYS:
        raise CatalogError(f"model {model_id!r}: unknown shape {shape!r}")
    allowed = _SHAPE_KEYS[shape] | _BODY_KEYS
    unknown = set(entry) - allowed
    missing = (_SHAPE_KEYS[shape] - _OPTIONAL_KEYS) - set(entry)
    if unknown or missing or "name" not in entry:
        raise CatalogError(
            f"model {model_id!r}, body {entry.get('name')!r}: unknown {sorted(unknown)}, "
            f"missing {sorted(missing | ({'name'} - set(entry)))}"
        )
    at = entry.get("at_mm", [0.0, 0.0])
    if len(at) != 2:
        raise CatalogError(f"model {model_id!r}: at_mm must be [x, y]")
    parameters = {key: entry[key] for key in _SHAPE_KEYS[shape] if key in entry}
    return BodySpec(str(entry["name"]), shape, parameters, (float(at[0]), float(at[1])))


def build_body(spec: BodySpec) -> Mesh:
    """The body's mesh, before placement and quantisation."""
    p = spec.parameters
    phase = math.radians(float(p.get("phase_deg", 0.0)))
    if spec.shape == "box":
        size = tuple(float(value) for value in p["size_mm"])
        if len(size) != 3:
            raise CatalogError(f"body {spec.name!r}: size_mm must be [x, y, z]")
        return box((size[0], size[1], size[2]))
    if spec.shape == "prism":
        return prism(float(p["radius_mm"]), int(p["segments"]), float(p["height_mm"]), phase)
    if spec.shape == "cone":
        return cone(float(p["radius_mm"]), int(p["segments"]), float(p["height_mm"]), phase)
    if spec.shape == "icosphere":
        return icosphere(float(p["radius_mm"]), int(p["subdivisions"]))
    polygon = np.asarray(p["polygon_mm"], dtype=np.float64)
    return extrude(polygon, float(p["height_mm"]))


def build_model(spec: ModelSpec) -> BuiltModel:
    """Place, merge, centre and quantise the bodies of ``spec``, and check the result."""
    placed: list[Mesh] = []
    for body in spec.bodies:
        mesh = build_body(body)
        low, high = mesh.bounds()
        centre = (low + high) / 2.0
        placed.append(
            Mesh(
                mesh.vertices
                + np.array([body.at_mm[0] - centre[0], body.at_mm[1] - centre[1], -low[2]]),
                mesh.triangles,
            )
        )

    _check_separation(spec, placed)
    merged = merge(placed)
    low, high = merged.bounds()
    centre = (low + high) / 2.0
    vertices = quantize_float32(merged.vertices - [centre[0], centre[1], low[2]])
    mesh = Mesh(vertices, merged.triangles)

    bodies: list[BuiltBody] = []
    first = 0
    for body, body_mesh in zip(spec.bodies, placed, strict=True):
        bodies.append(BuiltBody(body.name, body.shape, first, len(body_mesh.triangles)))
        first += len(body_mesh.triangles)
    built = BuiltModel(spec, mesh, tuple(bodies))
    _check_built(built)
    return built


def _check_separation(spec: ModelSpec, placed: Sequence[Mesh]) -> None:
    boxes = [mesh.bounds() for mesh in placed]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (low_i, high_i), (low_j, high_j) = boxes[i], boxes[j]
            gap_x = max(low_j[0] - high_i[0], low_i[0] - high_j[0])
            gap_y = max(low_j[1] - high_i[1], low_i[1] - high_j[1])
            if max(gap_x, gap_y) < MIN_BODY_GAP_MM:
                raise CatalogError(
                    f"model {spec.id!r}: bodies {spec.bodies[i].name!r} and "
                    f"{spec.bodies[j].name!r} are closer than {MIN_BODY_GAP_MM} mm"
                )


def _check_built(model: BuiltModel) -> None:
    mesh = model.mesh
    if mesh.vertices[:, 2].min() != 0.0:
        raise GeometryError(f"model {model.spec.id!r} does not stand exactly on z = 0")
    corners = mesh.triangle_vertices
    doubled_areas = np.linalg.norm(
        np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1
    )
    if np.any(doubled_areas == 0.0):
        raise GeometryError(f"model {model.spec.id!r} has zero-area triangles after quantisation")
    for body in model.bodies:
        part = Mesh(
            mesh.vertices,
            mesh.triangles[body.first_triangle : body.first_triangle + body.triangle_count],
        )
        report = topology(part)
        if not report.closed_and_oriented:
            raise GeometryError(f"model {model.spec.id!r}, body {body.name!r}: {report}")
        if part.signed_volume() <= 0.0:
            raise GeometryError(f"model {model.spec.id!r}, body {body.name!r} is inverted")


def model_record(model: BuiltModel, stl_name: str, stl_sha256: str) -> dict[str, Any]:
    """The manifest entry of a built model."""
    low, high = model.mesh.bounds()
    bodies = []
    for body in model.bodies:
        triangles = model.mesh.triangles[
            body.first_triangle : body.first_triangle + body.triangle_count
        ]
        part = Mesh(model.mesh.vertices, triangles)
        used = model.mesh.vertices[np.unique(triangles)]
        bodies.append(
            {
                "name": body.name,
                "shape": body.shape,
                "first_triangle": body.first_triangle,
                "triangle_count": body.triangle_count,
                "volume_mm3": part.signed_volume(),
                "bounds_mm": {"min": used.min(axis=0).tolist(), "max": used.max(axis=0).tolist()},
            }
        )
    return {
        "id": model.spec.id,
        "description": model.spec.description,
        "stl": stl_name,
        "sha256": stl_sha256,
        "triangle_count": len(model.mesh.triangles),
        "vertex_count": len(model.mesh.vertices),
        "volume_mm3": model.mesh.signed_volume(),
        "bounds_mm": {"min": low.tolist(), "max": high.tolist()},
        "bodies": bodies,
    }


def build_catalog(catalog_path: Path, out_dir: Path, only: Sequence[str] = ()) -> dict[str, Any]:
    """Build the catalog's models (or ``only`` those ids) into ``out_dir`` and write the manifest.

    Returns the manifest. Existing STL files of the same name are replaced: they are build
    products, identified by their hash in the manifest.
    """
    specs = load_catalog(catalog_path)
    if only:
        known = {spec.id for spec in specs}
        unknown = sorted(set(only) - known)
        if unknown:
            raise CatalogError(f"unknown model ids: {unknown}")
        specs = [spec for spec in specs if spec.id in set(only)]

    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for spec in specs:
        model = build_model(spec)
        stl_name = f"{spec.id}.stl"
        write_binary_stl(
            out_dir / stl_name, model.mesh, f"kbench model {spec.id} generator {GENERATOR_VERSION}"
        )
        records.append(model_record(model, stl_name, sha256_file(out_dir / stl_name)))

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": "model_manifest",
        "generator_version": GENERATOR_VERSION,
        "catalog_sha256": sha256_file(catalog_path),
        "units": "mm",
        "models": records,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
