from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
from support import MakeScript, posix_only

from kbench.config import Case, Suite, Timing, load_suite, load_targets, repository_path
from kbench.install import InstallError, Pin, install
from kbench.models import default_catalog_path
from kbench.report import render
from kbench.run import RunError, run_suite


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
    assert "| cube | karasu |" in report
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
    assert "| cube | karasu | 0 | 4 | no |" in render(run_dir)


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
