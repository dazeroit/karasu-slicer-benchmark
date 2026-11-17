"""Parsers of UVtoolsCmd output, targets, suites, slicer commands and run helpers.

The UVTools samples below are written for the tests in the format observed with UVTools v7.1.2
(docs/SLICERS.md); their values are invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kbench.config import ConfigError, load_suite, load_target, load_targets, repository_path
from kbench.metrics.stack import AnalysisError
from kbench.run import conformity, schedule_from_layers
from kbench.slicers import karasu_job
from kbench.uvtools import parse_issues, parse_layer_properties, parse_properties

PROPERTIES = """\
Opening file sample.goo: Done in 0.10s
-------------------------
FileType: Binary
Header: Version: V3.0, LayerCount: 99, ResolutionX: 1
Version: 30
ResolutionX: 4098
ResolutionY: 2560
LayerHeight: 0.05
DisplayMirror: Vertically
MachineName: Sample Printer
PixelWidth: 0.035
PixelHeight: 0.035
LayerCount: 200
BottomLayerCount: 2
ExposureTime: 2.5
Volume: 12.5
ResolutionX: 1
-------------------------
"""

LAYERS = """\
Opening file sample.goo: Done in 0.10s
-------------------------
# Layer: 0
Index: 0
NonZeroPixelCount: 1200
PositionZ: 0.05
RelativePositionZ: 0.05
ExposureTime: 30
-------------------------
# Layer: 1
Index: 1
PositionZ: 0.1
RelativePositionZ: 0.05
ExposureTime: 2.5
"""

ISSUES = """\
Opening file sample.goo: Done in 0.10s
Detecting issues: Done in 0.10s
Issues: 3
Island, 80, 29584px², {X=2263,Y=1251,Width=172,Height=172}
Overhang, 80, 11921px², {X=2303,Y=1291,Width=132,Height=92}
Resin trap, 12, 4.5px², {X=10,Y=20,Width=3,Height=4}
Something new and unexpected
"""


def test_parse_properties_takes_the_first_occurrence() -> None:
    properties = parse_properties(PROPERTIES)
    assert properties["ResolutionX"] == 4098.0
    assert properties["ResolutionY"] == 2560.0
    assert properties["PixelWidth"] == 0.035
    assert properties["LayerCount"] == 200.0
    assert properties["DisplayMirror"] == "Vertically"
    assert properties["MachineName"] == "Sample Printer"
    assert properties["Version"] == "30"
    assert properties["AntiAliasing"] is None  # Absent.


def test_parse_layer_properties() -> None:
    layers = parse_layer_properties(LAYERS)
    assert [layer["block"] for layer in layers] == [0, 1]
    assert layers[0]["PositionZ"] == 0.05
    assert layers[1]["ExposureTime"] == 2.5
    assert layers[1]["NonZeroPixelCount"] is None


def test_parse_issues_keeps_unparsed_lines() -> None:
    issues = parse_issues(ISSUES)
    assert issues["declared_count"] == 3
    assert issues["count"] == 3
    assert issues["by_type"] == {"Island": 1, "Overhang": 1, "Resin trap": 1}
    assert issues["issues"][0] == {
        "type": "Island",
        "layer": 80,
        "area_px": 29584.0,
        "bounds_px": [2263, 1251, 172, 172],
    }
    assert issues["unparsed"] == ["Something new and unexpected"]


def test_schedule_from_layer_tops() -> None:
    layers = schedule_from_layers([{"PositionZ": 0.05}, {"PositionZ": 0.1}, {"PositionZ": 0.2}])
    assert [(layer.z_bottom_mm, layer.height_mm) for layer in layers] == [
        (0.0, 0.05),
        (0.05, 0.05),
        (0.1, pytest.approx(0.1)),
    ]
    with pytest.raises(AnalysisError, match="does not rise"):
        schedule_from_layers([{"PositionZ": 0.05}, {"PositionZ": 0.05}])
    with pytest.raises(AnalysisError, match="no PositionZ"):
        schedule_from_layers([{"PositionZ": None}])


def test_repository_targets_and_suites_load() -> None:
    targets = load_targets(repository_path("targets"))
    assert {"elegoo-mars-5", "anycubic-photon-mono-4k"} <= set(targets)
    mars = targets["elegoo-mars-5"]
    assert mars.panel.resolution_x == 4098
    assert mars.panel.pitch_x_mm == 0.035
    for path in sorted(repository_path("suites").glob("*.toml")):
        suite = load_suite(path)
        assert all(case.target in targets for case in suite.cases)


def test_target_validation(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        'id = "bad"\ndescription = "x"\n[panel]\nresolution_x = 10\n[source]\n[slicers.karasu]\n'
        'printer = "p"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing keys"):
        load_target(path)
    wrong_name = tmp_path / "other.toml"
    wrong_name.write_text(
        repository_path("targets", "elegoo-mars-5.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="file name"):
        load_target(wrong_name)


def test_suite_validation(tmp_path: Path) -> None:
    path = tmp_path / "suite.toml"
    path.write_text(
        'id = "s"\ndescription = "x"\n[timing]\nwarmup = 0\nrepetitions = 0\ntimeout_s = 5\n'
        '[[cases]]\nmodel = "cube-20"\ntarget = "t"\nslicers = ["karasu"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="repetitions"):
        load_suite(path)


def test_karasu_command() -> None:
    target = load_targets(repository_path("targets"))["elegoo-mars-5"]
    job = karasu_job(Path("/bin/karasu-cli"), Path("/m/plate.stl"), target, Path("/out/attempt-00"))
    assert job.output == Path("/out/attempt-00.goo")
    assert job.argv == [
        "/bin/karasu-cli",
        "slice",
        "--model",
        "/m/plate.stl",
        "--units",
        "mm",
        "--printer",
        "elegoo-mars-5",
        "--resin",
        "elegoo-standard-resin",
        "--format",
        "goo-v3",
        "--output",
        "/out/attempt-00.goo",
        "--center",
        "--no-progress",
    ]
    logged = karasu_job(Path("k"), Path("m"), target, Path("o"), log=Path("phases.log"))
    assert logged.argv[-2:] == ["--log", "phases.log"]


def test_conformity_flags_differences() -> None:
    target = load_targets(repository_path("targets"))["elegoo-mars-5"]
    layers = schedule_from_layers([{"PositionZ": 0.05 * (i + 1)} for i in range(200)])
    good = {
        "ResolutionX": 4098.0,
        "ResolutionY": 2560.0,
        "PixelWidth": 0.035,
        "PixelHeight": 0.035,
        "LayerHeight": 0.05,
        "LayerCount": 200.0,
    }
    checks = conformity(good, target, layers, 10.0)
    assert all(check["matches"] for check in checks.values())
    bad = dict(good, ResolutionX=2560.0, PixelWidth=0.05)
    checks = conformity(bad, target, layers[:-1], 10.0)
    assert not checks["resolution"]["matches"]
    assert not checks["pixel_pitch_mm"]["matches"]
    assert not checks["layer_count"]["matches"]
