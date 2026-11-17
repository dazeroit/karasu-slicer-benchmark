"""The external programs the suite depends on: where they are, what they are, which version.

Each tool is found through its environment variable when that variable is set and not empty,
then in its pinned installation under the work directory (``kbench install``), then on
``PATH``. A variable that names something unusable is reported as invalid; the search never
falls back behind the user's back, because measuring a different binary than the one configured
would silently change the results (BD-006).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kbench.install import default_pins_path, load_pins
from kbench.process import run_captured
from kbench.provenance import sha256_file
from kbench.source_build import default_sources_path, load_sources

# A version query does no work, but the first start of a .NET program such as UVtoolsCmd can take
# several seconds on a cold cache; 30 s leaves a wide margin and still bounds a hung program.
VERSION_PROBE_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ToolSpec:
    """How to find and identify one external program."""

    name: str
    role: str
    required: bool
    env_var: str
    executable: str
    version_args: tuple[str, ...]
    # Path of a pinned installation, relative to the work directory.
    work_path: str | None = None
    # A program with no version option, built by the suite: its version is read from the
    # build.json two directories above the binary (BD-022).
    version_from_build: bool = False


KARASU_CLI = ToolSpec(
    name="karasu-cli",
    role="slicer under test",
    required=True,
    env_var="KBENCH_KARASU_CLI",
    executable="karasu-cli",
    version_args=("--version",),
)


def _pinned_path(name: str) -> str | None:
    pins = load_pins(default_pins_path())
    if name not in pins:
        return None
    pin = pins[name]
    return f"tools/{pin.name}/{pin.version}/{pin.executable}"


UVTOOLS_CMD = ToolSpec(
    name="UVtoolsCmd",
    role="decoder and file analysis",
    required=True,
    env_var="KBENCH_UVTOOLSCMD",
    executable="UVtoolsCmd",
    # `--version` reports the command-line front end's own version; `--core-version` reports the
    # UVTools release (observed with UVTools v7.1.2).
    version_args=("--core-version",),
    work_path=_pinned_path("uvtools"),
)
GIT = ToolSpec(
    name="git",
    role="exports karasu-slicer refs; records the suite's commit",
    required=False,
    env_var="KBENCH_GIT",
    executable="git",
    version_args=("--version",),
)
CARGO = ToolSpec(
    name="cargo",
    role="builds karasu-cli from a ref",
    required=False,
    env_var="KBENCH_CARGO",
    executable="cargo",
    version_args=("--version",),
)

PRUSASLICER = ToolSpec(
    name="PrusaSlicer",
    role="compared slicer (command line)",
    required=False,
    env_var="KBENCH_PRUSASLICER",
    executable="prusa-slicer",
    # PrusaSlicer has no version option; the first line of its help names the build (observed
    # with 2.8.1).
    version_args=("--help",),
    work_path=_pinned_path("prusaslicer"),
)


def _source_path(name: str) -> str | None:
    pins = load_sources(default_sources_path())
    if name not in pins:
        return None
    pin = pins[name]
    return f"{pin.name}/{pin.commit}/{pin.executable}"


DRAGONFRUIT_CLI = ToolSpec(
    name="dragonfruit-cli",
    role="compared slicer (command line, built from source)",
    required=False,
    env_var="KBENCH_DRAGONFRUIT_CLI",
    executable="dragonfruit-cli",
    version_args=("info",),
    work_path=_source_path("dragonfruit"),
    version_from_build=True,
)
NPM = ToolSpec(
    name="npm",
    role="builds compared slicers from source",
    required=False,
    env_var="KBENCH_NPM",
    executable="npm",
    version_args=("--version",),
)

TOOLS: tuple[ToolSpec, ...] = (
    KARASU_CLI,
    UVTOOLS_CMD,
    PRUSASLICER,
    DRAGONFRUIT_CLI,
    GIT,
    CARGO,
    NPM,
)

ResolutionStatus = Literal["found", "missing", "invalid"]


@dataclass(frozen=True)
class Resolution:
    """Where a tool was found, or why it was not."""

    status: ResolutionStatus
    source: str | None
    path: Path | None
    error: str | None


def resolve(spec: ToolSpec, environ: Mapping[str, str], work: Path | None = None) -> Resolution:
    """Find ``spec`` through its environment variable, its pinned installation under ``work``,
    or ``environ``'s ``PATH``, in that order."""
    configured = environ.get(spec.env_var, "")
    if configured:
        path = Path(configured).expanduser().absolute()
        source = f"env:{spec.env_var}"
        if not path.is_file():
            return Resolution("invalid", source, path, f"{spec.env_var} does not name a file")
        if not os.access(path, os.X_OK):
            return Resolution(
                "invalid", source, path, f"{spec.env_var} names a file that is not executable"
            )
        return Resolution("found", source, path, None)

    if work is not None and spec.work_path is not None:
        pinned = (work / spec.work_path).absolute()
        if pinned.is_file() and os.access(pinned, os.X_OK):
            return Resolution("found", "work", pinned, None)

    found = shutil.which(spec.executable, path=environ.get("PATH", os.defpath))
    if found is None:
        return Resolution(
            "missing",
            None,
            None,
            f"set {spec.env_var} or put {spec.executable} on PATH",
        )
    return Resolution("found", "PATH", Path(found).absolute(), None)


def inspect(spec: ToolSpec, environ: Mapping[str, str], work: Path | None = None) -> dict[str, Any]:
    """A record of one tool: resolution, resolved file, SHA-256 and version.

    ``ok`` means the tool was found and answered its version query with exit status 0, so a
    run can record which version it used.
    """
    resolution = resolve(spec, environ, work)
    record: dict[str, Any] = {
        "name": spec.name,
        "role": spec.role,
        "required": spec.required,
        "env_var": spec.env_var,
        "status": resolution.status,
        "source": resolution.source,
        "path": str(resolution.path) if resolution.path is not None else None,
        "resolved_path": None,
        "sha256": None,
        "version": None,
        "version_probe": None,
        "error": resolution.error,
        "ok": False,
    }
    if resolution.status != "found" or resolution.path is None:
        return record

    resolved = resolution.path.resolve()
    record["resolved_path"] = str(resolved)
    record["sha256"] = sha256_file(resolved)

    probe = run_captured([str(resolution.path), *spec.version_args], VERSION_PROBE_TIMEOUT_S)
    record["version_probe"] = {
        "argv": [spec.executable, *spec.version_args],
        "exit_status": probe.exit_status,
        "timed_out": probe.timed_out,
        "start_error": probe.start_error,
        "first_line": probe.first_line(),
    }
    if probe.exit_status == 0:
        record["version"] = probe.first_line()
        if spec.version_from_build:
            record["version"] = _build_version(resolved) or record["version"]
        record["ok"] = record["version"] is not None
    else:
        record["error"] = "the version query failed"
    return record


def inventory(environ: Mapping[str, str], work: Path | None = None) -> list[dict[str, Any]]:
    """Records of every tool in :data:`TOOLS`, in their fixed order."""
    return [inspect(spec, environ, work) for spec in TOOLS]


def _build_version(binary: Path) -> str | None:
    """``<name> <version> (<commit>)`` from the build record beside a suite-built binary."""
    parents = binary.parents
    if len(parents) < 3:
        return None
    path = parents[2] / "build.json"
    if not path.is_file():
        return None
    import json

    record = json.loads(path.read_text(encoding="utf-8"))
    return f"{binary.name} {record.get('version')} ({str(record.get('commit', ''))[:7]})"
