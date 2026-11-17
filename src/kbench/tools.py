"""The external programs the suite depends on: where they are, what they are, which version.

Each tool is found through its environment variable when that variable is set and not empty,
otherwise on ``PATH``. A variable that names something unusable is reported as invalid; the
search never falls back to ``PATH`` behind the user's back, because measuring a different binary
than the one configured would silently change the results.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kbench.process import run_captured
from kbench.provenance import sha256_file

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


KARASU_CLI = ToolSpec(
    name="karasu-cli",
    role="slicer under test",
    required=True,
    env_var="KBENCH_KARASU_CLI",
    executable="karasu-cli",
    version_args=("--version",),
)
UVTOOLS_CMD = ToolSpec(
    name="UVtoolsCmd",
    role="decoder and file analysis",
    required=True,
    env_var="KBENCH_UVTOOLSCMD",
    executable="UVtoolsCmd",
    version_args=("--version",),
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

TOOLS: tuple[ToolSpec, ...] = (KARASU_CLI, UVTOOLS_CMD, GIT, CARGO)

ResolutionStatus = Literal["found", "missing", "invalid"]


@dataclass(frozen=True)
class Resolution:
    """Where a tool was found, or why it was not."""

    status: ResolutionStatus
    source: str | None
    path: Path | None
    error: str | None


def resolve(spec: ToolSpec, environ: Mapping[str, str]) -> Resolution:
    """Find ``spec`` through its environment variable, otherwise on ``environ``'s ``PATH``."""
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

    found = shutil.which(spec.executable, path=environ.get("PATH", os.defpath))
    if found is None:
        return Resolution(
            "missing",
            None,
            None,
            f"set {spec.env_var} or put {spec.executable} on PATH",
        )
    return Resolution("found", "PATH", Path(found).absolute(), None)


def inspect(spec: ToolSpec, environ: Mapping[str, str]) -> dict[str, Any]:
    """A record of one tool: resolution, resolved file, SHA-256 and version.

    ``ok`` means the tool was found and answered its version query with exit status 0, so a
    run can record which version it used.
    """
    resolution = resolve(spec, environ)
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
        record["ok"] = record["version"] is not None
    else:
        record["error"] = "the version query failed"
    return record


def inventory(environ: Mapping[str, str]) -> list[dict[str, Any]]:
    """Records of every tool in :data:`TOOLS`, in their fixed order."""
    return [inspect(spec, environ) for spec in TOOLS]
