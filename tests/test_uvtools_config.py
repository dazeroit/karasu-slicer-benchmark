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


def test_prusaslicer_command() -> None:
    from kbench.slicers import ADAPTERS

    target = load_targets(repository_path("targets"))["prusa-sl1s"]
    job = ADAPTERS["prusaslicer"].job(Path("/ps/AppRun"), Path("/m/cube.stl"), target, Path("/o/a"))
    assert job.output == Path("/o/a.sl1s")
    argv = job.argv
    assert argv[:2] == ["/ps/AppRun", "--export-sla"]
    assert argv[-1] == "/m/cube.stl"
    options = dict(zip(argv[2:-1:2], argv[3:-1:2], strict=False))
    assert argv[argv.index("--display-pixels-x") + 1] == "2560"
    assert argv[argv.index("--display-orientation") + 1] == "portrait"
    assert argv[argv.index("--bed-shape") + 1] == "0x0,128x0,128x81,0x81"
    assert argv[argv.index("--center") + 1] == "64,40.5"
    assert argv[argv.index("--layer-height") + 1] == "0.05"
    assert argv[argv.index("--gamma-correction") + 1] == "0"
    for flag in ("--no-supports-enable", "--no-pad-enable", "--no-hollowing-enable"):
        assert flag in argv
    assert options  # Every option has its value.


def test_karasu_profile_files_resolve_to_the_repository() -> None:
    target = load_targets(repository_path("targets"))["prusa-sl1s"]
    job = karasu_job(Path("k"), Path("m.stl"), target, Path("o"))
    printer = Path(job.argv[job.argv.index("--printer") + 1])
    assert printer.is_absolute()
    assert printer == repository_path("targets", "profiles", "karasu", "prusa-sl1s-printer.json")
    assert printer.is_file()


def test_conformity_accepts_a_portrait_declaration() -> None:
    target = load_targets(repository_path("targets"))["prusa-sl1s"]
    layers = schedule_from_layers([{"PositionZ": 0.05 * (i + 1)} for i in range(200)])
    portrait = {
        "ResolutionX": 1620.0,
        "ResolutionY": 2560.0,
        "PixelWidth": 0.05,
        "PixelHeight": 0.05,
        "LayerHeight": 0.05,
    }
    checks = conformity(portrait, target, layers, 10.0)
    assert checks["resolution"]["transposed"]
    assert checks["resolution"]["matches"]
    assert checks["pixel_pitch_mm"]["matches"]


def write_sl1(path: Path, count: int, job: str = "job", extra: dict | None = None) -> None:
    import zipfile

    import numpy as np
    from PIL import Image

    with zipfile.ZipFile(path, "w") as bundle:
        config = (
            f"jobDir = {job}\nlayerHeight = 0.05\nnumFast = {count}\nnumSlow = 0\nexpTime = 2\n"
        )
        bundle.writestr("config.ini", config)
        for index in range(count):
            image = np.zeros((4, 6), dtype=np.uint8)
            image[1, index % 6] = 255
            target = path.parent / f"tmp{index}.png"
            Image.fromarray(image).save(target)
            bundle.write(target, f"{job}{index:05d}.png")
        for name, data in (extra or {}).items():
            bundle.writestr(name, data)


def test_sl1_reader(tmp_path: Path) -> None:
    from kbench.sl1 import layers_digest, read_sl1

    path = tmp_path / "file.sl1s"
    write_sl1(path, 3, extra={"thumbnail/thumbnail.png": b"x"})
    files, config, layers = read_sl1(path, tmp_path / "layers")
    assert [file.name for file in files] == ["layer00000.png", "layer00001.png", "layer00002.png"]
    assert config["jobDir"] == "job"
    assert [(layer.z_bottom_mm, layer.height_mm) for layer in layers] == [
        (0.0, 0.05),
        (0.05, 0.05),
        (0.1, 0.05),
    ]
    digest = layers_digest(path)
    # Different metadata, same layers: same digest.
    other = tmp_path / "other.sl1s"
    write_sl1(other, 3, extra={"prusaslicer.ini": b"created = now"})
    assert layers_digest(other) == digest
    assert layers_digest(tmp_path / "x.goo") is None


def test_sl1_reader_refuses_incomplete_archives(tmp_path: Path) -> None:
    import zipfile

    from kbench.sl1 import SL1Error, read_sl1

    path = tmp_path / "bad.sl1"
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("config.ini", "jobDir = j\nlayerHeight = 0.05\nnumFast = 2\nnumSlow = 0\n")
        bundle.writestr("j00000.png", b"")
    with pytest.raises(SL1Error, match="missing"):
        read_sl1(path, tmp_path / "out")
    (tmp_path / "plain.sl1").write_bytes(b"not a zip")
    with pytest.raises(SL1Error, match="not a ZIP"):
        read_sl1(tmp_path / "plain.sl1", tmp_path / "out")


def test_dragonfruit_command() -> None:
    from kbench.slicers import ADAPTERS

    target = load_targets(repository_path("targets"))["elegoo-saturn-4-ultra-16k"]
    job = ADAPTERS["dragonfruit"].job(
        Path("/df/dragonfruit-cli"), Path("/m/a.stl"), target, Path("/o/a")
    )
    assert job.output == Path("/o/a.goo")
    argv = job.argv
    assert argv[:4] == ["/df/dragonfruit-cli", "slice", "run", "/m/a.stl"]
    assert argv[argv.index("--build-width-mm") + 1] == "211.68"
    assert argv[argv.index("--build-depth-mm") + 1] == "118.37"
    assert argv[argv.index("--source-width-px") + 1] == "15120"
    assert argv[argv.index("--source-height-px") + 1] == "6230"
    assert argv[argv.index("--anti-aliasing") + 1] == "Off"
    assert argv[argv.index("--layer-height") + 1] == "0.05"


def test_source_pins_and_build_versions(tmp_path: Path) -> None:
    import json

    from kbench.source_build import default_sources_path, load_sources
    from kbench.tools import _build_version

    pin = load_sources(default_sources_path())["dragonfruit"]
    assert pin.version == "v0.2.2"
    assert len(pin.commit) == 40
    binary = tmp_path / "commit" / "target" / "release" / "tool"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    assert _build_version(binary) is None
    (tmp_path / "commit" / "build.json").write_text(
        json.dumps({"version": "v1.2", "commit": "abcdef0123"})
    )
    assert _build_version(binary) == "tool v1.2 (abcdef0)"


def test_decoded_determinism_tells_metadata_from_layers(tmp_path: Path) -> None:
    from kbench.run import _decoded_determinism
    from kbench.sl1 import read_sl1
    from kbench.uvtools import UVTools

    first, same, other = (
        tmp_path / "a" / "p.sl1s",
        tmp_path / "b" / "p.sl1s",
        tmp_path / "c" / "p.sl1s",
    )
    for path in (first, same, other):
        path.parent.mkdir()
    write_sl1(first, 3)
    write_sl1(same, 3, extra={"prusaslicer.ini": b"created = later"})  # Other bytes, same layers.
    write_sl1(other, 4)  # Other layers.
    files = read_sl1(first, tmp_path / "layers")[0]
    unused = UVTools(Path("/nonexistent"))  # SL1 archives never reach UVTools.
    record = {"distinct_files": [str(same)]}
    assert _decoded_determinism(record, files, unused, tmp_path)["distinct"] == 1
    record = {"distinct_files": [str(same), str(other)]}
    result = _decoded_determinism(record, files, unused, tmp_path)
    assert result["files"] == 3
    assert result["distinct"] == 2
