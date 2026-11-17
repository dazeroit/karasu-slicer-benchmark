from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import MakeScript, posix_only

from kbench import __version__
from kbench.cli import EXIT_NOT_READY, EXIT_OK, EXIT_USAGE, main
from kbench.tools import TOOLS


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"kbench {__version__}"


def test_no_command_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_USAGE
    assert "usage: kbench" in capsys.readouterr().err


def test_env_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["env", "--json"]) == EXIT_OK
    record = json.loads(capsys.readouterr().out)
    assert record["kind"] == "environment"


def test_env_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["env"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "\ncpu.logical_cpus: " in out
    assert "\nsuite.version: " in out


def _isolate_tools(monkeypatch: pytest.MonkeyPatch, path_dir: Path) -> None:
    for spec in TOOLS:
        monkeypatch.delenv(spec.env_var, raising=False)
    monkeypatch.setenv("PATH", str(path_dir))


@posix_only
def test_doctor_ready_when_required_tools_answer(
    make_script: MakeScript,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    _isolate_tools(monkeypatch, empty)
    karasu = make_script("karasu", 'echo "karasu-slicer 9.9.9"')
    uvtools = make_script("uvtools", 'echo "9.9.9"')
    monkeypatch.setenv("KBENCH_KARASU_CLI", str(karasu))
    monkeypatch.setenv("KBENCH_UVTOOLSCMD", str(uvtools))

    assert main(["doctor", "--json"]) == EXIT_OK
    record = json.loads(capsys.readouterr().out)
    assert record["kind"] == "tool_inventory"
    by_name = {tool["name"]: tool for tool in record["tools"]}
    assert by_name["karasu-cli"]["version"] == "karasu-slicer 9.9.9"
    assert by_name["UVtoolsCmd"]["ok"] is True
    assert by_name["git"]["status"] == "missing"  # Optional: does not block readiness.


def test_doctor_not_ready_without_required_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _isolate_tools(monkeypatch, tmp_path)
    assert main(["doctor"]) == EXIT_NOT_READY
    out = capsys.readouterr().out
    assert "set KBENCH_KARASU_CLI or put karasu-cli on PATH" in out
    assert "Required tools ready: 0 of 2." in out
