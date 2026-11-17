from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from kbench.cli import EXIT_OK, main
from kbench.geometry.mesh import topology, weld
from kbench.geometry.stl import read_binary_stl
from kbench.models import (
    CatalogError,
    build_catalog,
    build_model,
    default_catalog_path,
    load_catalog,
)
from kbench.provenance import sha256_file

# Models above this size are left to `kbench models build`; the tests stay fast.
MAX_TEST_TRIANGLES = 400_000


def catalog_specs():
    return [spec for spec in load_catalog(default_catalog_path()) if spec.id != "sphere-r20-s8"]


def regular_polygon_area(radius: float, segments: int) -> float:
    return segments / 2.0 * radius**2 * math.sin(2.0 * math.pi / segments)


@pytest.mark.parametrize("spec", catalog_specs(), ids=lambda spec: spec.id)
def test_every_catalog_model_builds_valid(spec) -> None:
    model = build_model(spec)
    mesh = model.mesh
    assert len(mesh.triangles) <= MAX_TEST_TRIANGLES
    low, high = mesh.bounds()
    assert low[2] == 0.0
    centre = (low + high) / 2.0
    # Centred up to the float32 rounding of the centring.
    assert abs(centre[0]) < 1e-5
    assert abs(centre[1]) < 1e-5
    assert np.array_equal(mesh.vertices.astype(np.float32).astype(np.float64), mesh.vertices)
    assert sum(body.triangle_count for body in model.bodies) == len(mesh.triangles)
    for body in model.bodies:
        part = type(mesh)(mesh.vertices, mesh.triangles[model.body_triangles(body.name)])
        assert topology(part).closed_and_oriented
        assert part.signed_volume() > 0.0


def test_known_volumes() -> None:
    specs = {spec.id: spec for spec in load_catalog(default_catalog_path())}
    assert build_model(specs["cube-20"]).mesh.signed_volume() == 8000.0
    assert build_model(specs["cylinder-r5-n64"]).mesh.signed_volume() == pytest.approx(
        regular_polygon_area(5.0, 64) * 10.0, rel=1e-6
    )
    assert build_model(specs["cone-r8-h16"]).mesh.signed_volume() == pytest.approx(
        regular_polygon_area(8.0, 128) * 16.0 / 3.0, rel=1e-6
    )
    plate = build_model(specs["accuracy-plate"])
    cube = type(plate.mesh)(plate.mesh.vertices, plate.mesh.triangles[plate.body_triangles("cube")])
    assert cube.signed_volume() == pytest.approx(1000.0, rel=1e-6)


def write_catalog(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "catalog.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_catalog_rejects_unknown_keys_and_shapes(tmp_path: Path) -> None:
    bad_key = write_catalog(
        tmp_path,
        '[[models]]\nid = "a"\n'
        'bodies = [{ name = "b", shape = "box", size_mm = [1, 1, 1], colour = 1 }]\n',
    )
    with pytest.raises(CatalogError, match="colour"):
        load_catalog(bad_key)
    bad_shape = write_catalog(
        tmp_path, '[[models]]\nid = "a"\nbodies = [{ name = "b", shape = "torus" }]\n'
    )
    with pytest.raises(CatalogError, match="torus"):
        load_catalog(bad_shape)
    missing = write_catalog(
        tmp_path,
        '[[models]]\nid = "a"\nbodies = [{ name = "b", shape = "prism", radius_mm = 1 }]\n',
    )
    with pytest.raises(CatalogError, match="missing"):
        load_catalog(missing)


def test_catalog_rejects_duplicates_and_close_bodies(tmp_path: Path) -> None:
    duplicate = write_catalog(
        tmp_path,
        '[[models]]\nid = "a"\nbodies = [{ name = "b", shape = "box", size_mm = [1, 1, 1] }]\n' * 2,
    )
    with pytest.raises(CatalogError, match="duplicate"):
        load_catalog(duplicate)
    close = write_catalog(
        tmp_path,
        '[[models]]\nid = "a"\nbodies = [\n'
        '  { name = "b", shape = "box", size_mm = [2, 2, 1] },\n'
        '  { name = "c", shape = "box", size_mm = [2, 2, 1], at_mm = [2.5, 0] },\n]\n',
    )
    with pytest.raises(CatalogError, match="closer than"):
        build_model(load_catalog(close)[0])


def test_build_writes_stl_and_manifest_deterministically(tmp_path: Path) -> None:
    first = build_catalog(default_catalog_path(), tmp_path / "a", ["cube-20", "accuracy-plate"])
    second = build_catalog(default_catalog_path(), tmp_path / "b", ["cube-20", "accuracy-plate"])
    assert first == second
    manifest = json.loads((tmp_path / "a" / "manifest.json").read_text())
    assert manifest == first
    assert manifest["kind"] == "model_manifest"
    plate = next(record for record in manifest["models"] if record["id"] == "accuracy-plate")
    path = tmp_path / "a" / plate["stl"]
    assert sha256_file(path) == plate["sha256"]
    corners = read_binary_stl(path)
    assert len(corners) == plate["triangle_count"]
    assert weld(corners).signed_volume() == pytest.approx(plate["volume_mm3"], rel=1e-12)
    assert [body["name"] for body in plate["bodies"]] == ["cube", "cylinder", "cone", "sphere", "l"]
    assert sum(body["volume_mm3"] for body in plate["bodies"]) == pytest.approx(
        plate["volume_mm3"], rel=1e-12
    )


def test_build_rejects_unknown_ids(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="nope"):
        build_catalog(default_catalog_path(), tmp_path, ["nope"])


def test_cli_models(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "list"]) == EXIT_OK
    assert "accuracy-plate" in capsys.readouterr().out
    assert main(["models", "build", "--out", str(tmp_path), "cube-20"]) == EXIT_OK
    assert (tmp_path / "cube-20.stl").is_file()
    assert main(["models", "build", "--out", str(tmp_path), "nope"]) == 1
