from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
from support import MakeScript, posix_only

from kbench.config import Case, Suite, Timing, load_suite, load_targets, repository_path
from kbench.html_report import render_html
from kbench.install import InstallError, Pin, install
from kbench.models import default_catalog_path
from kbench.report import render
from kbench.run import RunError, import_print_file, run_suite


def make_zip(path: Path, members: dict[str, bytes], executable: str | None = None) -> Pin:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            if name == executable:
                info.external_attr = 0o100755 << 16
            bundle.writestr(info, data)
    data = path.read_bytes()
    return Pin(
        name="tool",
        version="v1",
        url="https://example.invalid/tool.zip",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        archive="zip",
        executable=executable or "tool",
        platform="linux-x64",
    )


def test_install_checks_and_extracts(tmp_path: Path) -> None:
    pin = make_zip(tmp_path / "tool.zip", {"tool": b"#!/bin/sh\n", "lib/data.txt": b"x"}, "tool")
    executable = install(pin, tmp_path / "work", archive=tmp_path / "tool.zip")
    assert executable == tmp_path / "work" / "tools" / "tool" / "v1" / "tool"
    assert os.access(executable, os.X_OK)
    assert (executable.parent / "lib" / "data.txt").read_bytes() == b"x"
    # A second call keeps the installation.
    assert install(pin, tmp_path / "work", archive=tmp_path / "missing.zip") == executable


def test_install_refuses_a_wrong_hash(tmp_path: Path) -> None:
    pin = make_zip(tmp_path / "tool.zip", {"tool": b"x"}, "tool")
    tampered = Pin(**{**pin.__dict__, "sha256": "0" * 64})
    with pytest.raises(InstallError, match="SHA-256"):
        install(tampered, tmp_path / "work", archive=tmp_path / "tool.zip")
    assert not (tmp_path / "work" / "tools" / "tool" / "v1").exists()


def test_install_refuses_escaping_members(tmp_path: Path) -> None:
    pin = make_zip(tmp_path / "tool.zip", {"../evil": b"x", "tool": b"y"}, "tool")
    with pytest.raises(InstallError, match="unsafe"):
        install(pin, tmp_path / "work", archive=tmp_path / "tool.zip")
    assert not (tmp_path / "work" / "tools" / "evil").exists()
    assert not (tmp_path / "work" / "tools" / "tool" / "v1").exists()


FAKE_KARASU = """
if [ "$1" = "--version" ]; then echo "karasu-slicer 9.9.9-fake"; exit 0; fi
output=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--output" ]; then output="$2"; fi
  shift
done
printf 'fake print file\\n' > "$output"
echo "Layers: 1"
"""


@posix_only
def test_timing_only_run_with_a_fake_slicer(make_script: MakeScript, tmp_path: Path) -> None:
    karasu = make_script("karasu-cli", FAKE_KARASU)
    suite = Suite(
        id="unit",
        description="Timing only.",
        timing=Timing(warmup=1, repetitions=3, timeout_s=30),
        cases=(Case("cube", "cube-20", "elegoo-mars-5", ("karasu",), analyze=False),),
        sha256="0" * 64,
    )
    environ = {"KBENCH_KARASU_CLI": str(karasu), "PATH": "/usr/bin:/bin"}
    targets = load_targets(repository_path("targets"))
    run_dir = run_suite(
        suite, targets, default_catalog_path(), tmp_path / "work", environ, progress=lambda _: None
    )

    run = json.loads((run_dir / "run.json").read_text())
    assert run["kind"] == "run"
    assert run["suite"]["timing"] == {"warmup": 1, "repetitions": 3, "timeout_s": 30}
    case = json.loads((run_dir / run["cases"][0]["record"]).read_text())
    assert [attempt["warmup"] for attempt in case["attempts"]] == [True, False, False, False]
    assert all(attempt["succeeded"] for attempt in case["attempts"])
    assert case["performance"]["wall_s"]["count"] == 3
    assert case["performance"]["failed_runs"] == 0
    assert len(case["determinism"]["distinct_sha256"]) == 1
    assert Path(case["print_file"]).read_text() == "fake print file\n"
    assert "--log" in case["attempts"][0]["argv"]  # The warm-up records the phases.
    assert "--log" not in case["attempts"][1]["argv"]
    assert "analysis" not in case
    report = render(run_dir)
    assert "| cube | karasu (karasu-slicer 9.9.9-fake) | all |" in report
    page = render_html(run_dir)
    assert page.startswith("<!doctype html>")
    assert "Median wall time" in page
    assert "## Failures\n\nNone." in report


@posix_only
def test_failures_are_recorded(make_script: MakeScript, tmp_path: Path) -> None:
    karasu = make_script("karasu-cli", 'if [ "$1" = "--version" ]; then echo v; exit 0; fi\nexit 4')
    suite = Suite(
        "unit",
        "x",
        Timing(0, 2, 30),
        (Case("cube", "cube-20", "elegoo-mars-5", ("karasu",), False),),
        "0" * 64,
    )
    environ = {"KBENCH_KARASU_CLI": str(karasu), "PATH": "/usr/bin:/bin"}
    run_dir = run_suite(
        suite,
        load_targets(repository_path("targets")),
        default_catalog_path(),
        tmp_path / "w",
        environ,
        progress=lambda _: None,
    )
    case = json.loads((run_dir / "cases" / "cube" / "karasu" / "case.json").read_text())
    assert case["performance"]["failed_runs"] == 2
    assert [attempt["exit_status"] for attempt in case["attempts"]] == [4, 4]
    assert case["print_file"] is None
    assert "| cube | karasu (v) | 0 | 4 | no |" in render(run_dir)


def test_missing_tools_stop_the_run(tmp_path: Path) -> None:
    suite = load_suite(repository_path("suites", "smoke.toml"))
    with pytest.raises(RunError, match="tools not ready"):
        run_suite(
            suite,
            load_targets(repository_path("targets")),
            default_catalog_path(),
            tmp_path / "w",
            {"PATH": str(tmp_path)},
            progress=lambda _: None,
        )


def _use_selected_karasu(environ: dict[str, str]) -> None:
    """The tests run in a temporary work directory: point them at the selected build of the
    suite's own work directory, unless KBENCH_KARASU_CLI is set."""
    from kbench.karasu_build import selected_binary

    selected = selected_binary(repository_path("work"))
    if selected is not None:
        environ.setdefault("KBENCH_KARASU_CLI", str(selected))


@pytest.mark.integration
def test_smoke_suite_with_the_real_tools(tmp_path: Path) -> None:
    """Needs KBENCH_INTEGRATION=1, a karasu-cli (KBENCH_KARASU_CLI) and the pinned UVTools."""
    if os.environ.get("KBENCH_INTEGRATION") != "1":
        pytest.skip("set KBENCH_INTEGRATION=1 to run with the real tools")
    environ = dict(os.environ)
    environ.setdefault(
        "KBENCH_UVTOOLSCMD",
        str(repository_path("work", "tools", "uvtools", "v7.1.2", "UVtoolsCmd")),
    )
    _use_selected_karasu(environ)
    suite = load_suite(repository_path("suites", "smoke.toml"))
    run_dir = run_suite(
        suite,
        load_targets(repository_path("targets")),
        default_catalog_path(),
        tmp_path / "w",
        environ,
        progress=lambda _: None,
    )
    case = json.loads(
        (run_dir / "cases" / "accuracy-plate@elegoo-mars-5" / "karasu" / "case.json").read_text()
    )
    assert case["analysis"]["status"] == "analysed"
    assert all(check["matches"] for check in case["analysis"]["conformity"].values())
    metrics = json.loads(
        (run_dir / "cases" / "accuracy-plate@elegoo-mars-5" / "karasu" / "metrics.json").read_text()
    )
    assert metrics["summary"]["iou"]["min"] > 0.99


@posix_only
def test_import_refuses_a_different_model_file(make_script: MakeScript, tmp_path: Path) -> None:
    uvtools = make_script("UVtoolsCmd", 'echo "7.1.2"')
    other = tmp_path / "other.stl"
    other.write_bytes(b"not the suite's model")
    printed = tmp_path / "print.goo"
    printed.write_bytes(b"file")
    targets = load_targets(repository_path("targets"))
    with pytest.raises(RunError, match="not the model this suite generates"):
        import_print_file(
            printed,
            slicer="other",
            slicer_version="1.0",
            target=targets["elegoo-mars-5"],
            model_id="cube-20",
            stl=other,
            catalog_path=default_catalog_path(),
            work=tmp_path / "w",
            environ={"KBENCH_UVTOOLSCMD": str(uvtools), "PATH": "/usr/bin:/bin"},
            progress=lambda _: None,
        )
    assert not any((tmp_path / "w" / "runs").iterdir())  # Nothing half-written is left.


@pytest.mark.integration
def test_import_and_compare_with_the_real_tools(tmp_path: Path) -> None:
    """A karasu-cli file imported as a manual export, reported beside a suite run."""
    if os.environ.get("KBENCH_INTEGRATION") != "1":
        pytest.skip("set KBENCH_INTEGRATION=1 to run with the real tools")
    environ = dict(os.environ)
    environ.setdefault(
        "KBENCH_UVTOOLSCMD",
        str(repository_path("work", "tools", "uvtools", "v7.1.2", "UVtoolsCmd")),
    )
    _use_selected_karasu(environ)
    targets = load_targets(repository_path("targets"))
    suite = load_suite(repository_path("suites", "smoke.toml"))
    run_dir = run_suite(
        suite, targets, default_catalog_path(), tmp_path / "w", environ, progress=lambda _: None
    )
    case = json.loads(
        (run_dir / "cases" / "accuracy-plate@elegoo-mars-5" / "karasu" / "case.json").read_text()
    )
    imported = import_print_file(
        Path(case["print_file"]),
        slicer="karasu-by-hand",
        slicer_version="0.2.0-dev",
        target=targets["elegoo-mars-5"],
        model_id="accuracy-plate",
        stl=run_dir / "models" / "accuracy-plate.stl",
        catalog_path=default_catalog_path(),
        work=tmp_path / "w",
        environ=environ,
        note="test",
        progress=lambda _: None,
    )
    record = json.loads(
        (
            imported / "cases" / "accuracy-plate@elegoo-mars-5" / "karasu-by-hand" / "case.json"
        ).read_text()
    )
    assert record["analysis"]["status"] == "analysed"
    report = render([run_dir, imported])
    assert "karasu-by-hand 0.2.0-dev (manual)" in report
    assert "Manual export: no timing." in report


@posix_only
def test_differing_outputs_are_kept_up_to_the_limit(
    make_script: MakeScript, tmp_path: Path
) -> None:
    # Every run writes different bytes (a counter), as a slicer stamping its creation time does.
    karasu = make_script(
        "karasu-cli",
        'if [ "$1" = "--version" ]; then echo v; exit 0; fi\n'
        'out=""; while [ $# -gt 0 ]; do [ "$1" = "--output" ] && out="$2"; shift; done\n'
        'date +%s%N > "$out"',
    )
    suite = Suite(
        "unit",
        "x",
        Timing(1, 4, 30),
        (Case("cube", "cube-20", "elegoo-mars-5", ("karasu",), False),),
        "0" * 64,
    )
    environ = {"KBENCH_KARASU_CLI": str(karasu), "PATH": "/usr/bin:/bin"}
    run_dir = run_suite(
        suite,
        load_targets(repository_path("targets")),
        default_catalog_path(),
        tmp_path / "w",
        environ,
        progress=lambda _: None,
    )
    case = json.loads((run_dir / "cases" / "cube" / "karasu" / "case.json").read_text())
    assert len(case["determinism"]["distinct_sha256"]) == 5
    assert len(case["distinct_files"]) == 2
    assert all(Path(path).is_file() for path in case["distinct_files"])


def test_scrub_removes_local_paths() -> None:
    from kbench.publish import scrub

    text = "failed: /home/user/work/runs/x/print.goo and C:\\Users\\me\\a.goo, see /tmp/k/log.txt"
    assert scrub(text) == "failed: print.goo and a.goo, see log.txt"
    assert scrub("ratio 1/2 and https://example.org/a/b") == "ratio 1/2 and https://example.org/a/b"


@posix_only
def test_publish_summarises_without_paths(make_script: MakeScript, tmp_path: Path) -> None:
    from kbench.publish import PublishError, publish

    karasu = make_script("karasu-cli", FAKE_KARASU)
    suite = Suite(
        "unit",
        "Timing only.",
        Timing(0, 2, 30),
        (Case("cube", "cube-20", "elegoo-mars-5", ("karasu",), False),),
        "0" * 64,
    )
    environ = {"KBENCH_KARASU_CLI": str(karasu), "PATH": "/usr/bin:/bin"}
    run_dir = run_suite(
        suite,
        load_targets(repository_path("targets")),
        default_catalog_path(),
        tmp_path / "w",
        environ,
        progress=lambda _: None,
    )
    run_path = run_dir / "run.json"
    record = json.loads(run_path.read_text())
    record["environment_before"]["suite"]["git_dirty"] = True
    run_path.write_text(json.dumps(record))
    with pytest.raises(PublishError, match="uncommitted"):
        publish([run_dir], tmp_path / "results", "unit", "Unit")
    record["environment_before"]["suite"]["git_dirty"] = False
    run_path.write_text(json.dumps(record))

    md_path, json_path = publish([run_dir], tmp_path / "results", "unit", "Unit test summary")
    text = md_path.read_text() + json_path.read_text()
    assert str(tmp_path) not in text
    assert "/home/" not in text
    summary = json.loads(json_path.read_text())
    assert summary["kind"] == "published_summary"
    case = summary["runs"][0]["cases"][0]
    assert case["performance"]["timed_runs"] == 2
    assert case["model"]["id"] == "cube-20"
    assert "hostname" not in json.dumps(summary)
    assert md_path.read_text().startswith("# Unit test summary")
