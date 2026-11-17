from __future__ import annotations

from pathlib import Path

from support import MakeScript, posix_only

from kbench.provenance import sha256_file
from kbench.tools import ToolSpec, inspect, resolve

FAKE = ToolSpec(
    name="fake-tool",
    role="test double",
    required=True,
    env_var="KBENCH_FAKE_TOOL",
    executable="fake-tool",
    version_args=("--version",),
)


@posix_only
def test_environment_variable_wins_over_path(make_script: MakeScript, tmp_path: Path) -> None:
    on_path = make_script("fake-tool", "echo path")
    configured = tmp_path / "configured-tool"
    configured.write_text("#!/bin/sh\necho configured\n", encoding="utf-8")
    configured.chmod(0o755)
    environ = {"KBENCH_FAKE_TOOL": str(configured), "PATH": str(on_path.parent)}
    resolution = resolve(FAKE, environ)
    assert resolution.status == "found"
    assert resolution.source == "env:KBENCH_FAKE_TOOL"
    assert resolution.path == configured


@posix_only
def test_invalid_variable_does_not_fall_back_to_path(
    make_script: MakeScript, tmp_path: Path
) -> None:
    on_path = make_script("fake-tool", "echo path")
    environ = {"KBENCH_FAKE_TOOL": str(tmp_path / "missing"), "PATH": str(on_path.parent)}
    resolution = resolve(FAKE, environ)
    assert resolution.status == "invalid"
    assert resolution.path == tmp_path / "missing"
    assert resolution.error == "KBENCH_FAKE_TOOL does not name a file"


@posix_only
def test_variable_naming_a_non_executable_file_is_invalid(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.write_text("not a program", encoding="utf-8")
    plain.chmod(0o644)
    resolution = resolve(FAKE, {"KBENCH_FAKE_TOOL": str(plain)})
    assert resolution.status == "invalid"
    assert resolution.error == "KBENCH_FAKE_TOOL names a file that is not executable"


@posix_only
def test_empty_variable_means_unset(make_script: MakeScript) -> None:
    on_path = make_script("fake-tool", "echo path")
    resolution = resolve(FAKE, {"KBENCH_FAKE_TOOL": "", "PATH": str(on_path.parent)})
    assert resolution.status == "found"
    assert resolution.source == "PATH"
    assert resolution.path == on_path


def test_missing_tool(tmp_path: Path) -> None:
    resolution = resolve(FAKE, {"PATH": str(tmp_path)})
    assert resolution.status == "missing"
    assert resolution.path is None
    assert resolution.error == "set KBENCH_FAKE_TOOL or put fake-tool on PATH"


@posix_only
def test_inspect_records_hash_and_version(make_script: MakeScript) -> None:
    tool = make_script("fake-tool", 'echo ""; echo "fake-tool 1.2.3"; echo "extra"')
    record = inspect(FAKE, {"PATH": str(tool.parent)})
    assert record["ok"] is True
    assert record["status"] == "found"
    assert record["version"] == "fake-tool 1.2.3"
    assert record["sha256"] == sha256_file(tool)
    assert record["resolved_path"] == str(tool.resolve())
    assert record["version_probe"]["argv"] == ["fake-tool", "--version"]
    assert record["version_probe"]["exit_status"] == 0
    assert record["error"] is None


@posix_only
def test_inspect_resolves_symlinks_for_the_hash(make_script: MakeScript, tmp_path: Path) -> None:
    target = make_script("real-tool", 'echo "real 2.0"')
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    (link_dir / "fake-tool").symlink_to(target)
    record = inspect(FAKE, {"PATH": str(link_dir)})
    assert record["path"] == str(link_dir / "fake-tool")
    assert record["resolved_path"] == str(target.resolve())
    assert record["sha256"] == sha256_file(target)


@posix_only
def test_failed_version_query_is_not_ok(make_script: MakeScript) -> None:
    tool = make_script("fake-tool", 'echo "unknown option" >&2; exit 2')
    record = inspect(FAKE, {"PATH": str(tool.parent)})
    assert record["status"] == "found"
    assert record["ok"] is False
    assert record["version"] is None
    assert record["version_probe"]["exit_status"] == 2
    assert record["version_probe"]["first_line"] == "unknown option"
    assert record["error"] == "the version query failed"


def test_inspect_missing_tool(tmp_path: Path) -> None:
    record = inspect(FAKE, {"PATH": str(tmp_path)})
    assert record["ok"] is False
    assert record["status"] == "missing"
    assert record["sha256"] is None
    assert record["version_probe"] is None
