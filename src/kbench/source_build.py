"""Building a compared slicer's command line from a pinned source commit (BD-022).

Only the commands the slicer's own documentation gives are run, in a directory of their own
under ``work/``; the sources are never opened or searched, and compiler warnings are turned off
so that build logs carry no source excerpts. ``build.json`` records the commit, the toolchains
and the binary's SHA-256.
"""

from __future__ import annotations

import json
import os
import shutil
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kbench.process import run_captured
from kbench.provenance import sha256_file, utc_timestamp

# Cloning with submodules and installing JavaScript packages download hundreds of megabytes;
# a release build of a Rust workspace from a cold cache takes many minutes.
CLONE_TIMEOUT_S = 1800.0
BUILD_TIMEOUT_S = 3600.0


class SourceBuildError(RuntimeError):
    """The pinned source could not be fetched or built."""


@dataclass(frozen=True)
class SourcePin:
    name: str
    version: str
    repository: str
    commit: str
    executable: str
    crate: str


def default_sources_path() -> Path:
    return Path(__file__).resolve().parents[2] / "tools" / "sources.toml"


def load_sources(path: Path) -> dict[str, SourcePin]:
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    pins = {}
    for name, entry in document.items():
        try:
            pins[name] = SourcePin(
                name=name,
                version=str(entry["version"]),
                repository=str(entry["repository"]),
                commit=str(entry["commit"]),
                executable=str(entry["executable"]),
                crate=str(entry["crate"]),
            )
        except KeyError as missing:
            raise SourceBuildError(f"source pin {name!r} lacks {missing}") from None
    return pins


def build_directory(work: Path, pin: SourcePin) -> Path:
    return work / pin.name / pin.commit


def built_executable(work: Path, pin: SourcePin) -> Path:
    return build_directory(work, pin) / pin.executable


def _run(
    argv: Sequence[str],
    log: Path,
    timeout_s: float,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    result = run_captured(list(argv), timeout_s, cwd=cwd, env=env)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(
            f"$ {' '.join(argv)}\n{result.stdout}{result.stderr}\nexit {result.exit_status}\n"
        )
    if result.exit_status != 0:
        raise SourceBuildError(
            f"{argv[0]} {argv[1] if len(argv) > 1 else ''} failed (status {result.exit_status}, "
            f"timed out {result.timed_out}); the log is {log}"
        )


def build_from_source(
    pin: SourcePin, work: Path, git: Path, cargo: Path, npm: Path
) -> dict[str, Any]:
    """Clone ``pin`` at its commit, generate what its build needs and build its command line."""
    directory = build_directory(work, pin).resolve()
    record_path = directory / "build.json"
    if record_path.is_file():
        record: dict[str, Any] = json.loads(record_path.read_text(encoding="utf-8"))
        binary = Path(record["binary"])
        if binary.is_file() and sha256_file(binary) == record["binary_sha256"]:
            return record

    directory.mkdir(parents=True, exist_ok=True)
    log = directory / "build.log"
    log.write_text("", encoding="utf-8")
    source = directory / "src"
    if source.exists():
        shutil.rmtree(source)
    _run(
        [
            str(git),
            "clone",
            "--quiet",
            "--branch",
            pin.version,
            "--depth",
            "1",
            "--recurse-submodules",
            "--shallow-submodules",
            pin.repository,
            str(source),
        ],
        log,
        CLONE_TIMEOUT_S,
    )
    head = run_captured([str(git), "-C", str(source), "rev-parse", "HEAD"], 60.0).stdout.strip()
    if head != pin.commit:
        raise SourceBuildError(f"{pin.version} is commit {head}, pinned {pin.commit}")

    environment = dict(os.environ)
    environment["RUSTFLAGS"] = "-Awarnings"  # No warnings: build logs carry no source excerpts.
    environment["CARGO_TARGET_DIR"] = str(directory / "target")
    _run(
        [str(npm), "ci", "--no-audit", "--no-fund", "--loglevel=error"],
        log,
        BUILD_TIMEOUT_S,
        cwd=source,
        env=environment,
    )
    _run(
        [str(npm), "run", "--silent", "generate:plugin-registry"],
        log,
        BUILD_TIMEOUT_S,
        cwd=source,
        env=environment,
    )
    _run(
        [str(cargo), "build", "--release", "--quiet"],
        log,
        BUILD_TIMEOUT_S,
        cwd=source / pin.crate,
        env=environment,
    )

    binary = directory / pin.executable
    if not binary.is_file():
        raise SourceBuildError(f"the build produced no {binary}")
    # The repository may pin its own toolchain: ask from the crate's directory.
    toolchain = run_captured([str(cargo), "--version"], 60.0, cwd=source / pin.crate).stdout.strip()
    node = run_captured([str(npm), "--version"], 60.0).stdout.strip()
    record = {
        "schema_version": 1,
        "kind": "source_build",
        "built_at_utc": utc_timestamp(),
        "name": pin.name,
        "version": pin.version,
        "repository": pin.repository,
        "commit": pin.commit,
        "cargo_version": toolchain,
        "npm_version": node,
        "binary": str(binary),
        "binary_sha256": sha256_file(binary),
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record
