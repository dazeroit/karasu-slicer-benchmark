"""Building karasu-cli from a git ref of a karasu-slicer checkout.

The checkout is only read: the commit is exported with ``git archive`` into
``work/karasu/<commit>/src`` and built there with Cargo's release profile and the locked
dependencies. ``build.json`` beside it records the commit, the toolchain and the binary's
SHA-256, so every run that uses this binary names the exact commit it measured.
"""

from __future__ import annotations

import io
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any

from kbench.process import run_captured
from kbench.provenance import sha256_file, utc_timestamp

# Reading refs and exporting an archive are local operations; a release build of karasu-cli
# from a cold cache takes minutes, so it gets an hour.
GIT_TIMEOUT_S = 300.0
BUILD_TIMEOUT_S = 3600.0


class BuildError(RuntimeError):
    """karasu-cli could not be built from the ref."""


def build_directory(work: Path, commit: str) -> Path:
    return work / "karasu" / commit


def build_karasu(repo: Path, ref: str, work: Path, git: Path, cargo: Path) -> dict[str, Any]:
    """Build karasu-cli at ``ref`` and return the build record (existing builds are reused)."""
    resolved = run_captured(
        [str(git), "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"], GIT_TIMEOUT_S
    )
    if resolved.exit_status != 0:
        raise BuildError(f"cannot resolve {ref!r} in {repo}: {resolved.stderr.strip()}")
    commit = resolved.stdout.strip()
    directory = build_directory(work, commit)
    record_path = directory / "build.json"
    if record_path.is_file():
        record: dict[str, Any] = json.loads(record_path.read_text(encoding="utf-8"))
        if (
            Path(record["binary"]).is_file()
            and sha256_file(Path(record["binary"])) == record["binary_sha256"]
        ):
            return record

    source = directory / "src"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir(parents=True)
    archive = _git_archive(git, repo, commit)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(source, filter="data")

    target_dir = directory / "target"
    log_path = directory / "build.log"
    built = run_captured(
        [
            str(cargo),
            "build",
            "--release",
            "--locked",
            "-p",
            "karasu-cli",
            "--target-dir",
            str(target_dir),
        ],
        BUILD_TIMEOUT_S,
        cwd=source,
    )
    log_path.write_text(built.stdout + built.stderr, encoding="utf-8")
    if built.exit_status != 0:
        raise BuildError(f"cargo build failed (status {built.exit_status}); see {log_path}")
    binary = target_dir / "release" / "karasu-cli"
    if not binary.is_file():
        raise BuildError(f"cargo build produced no {binary}")

    rustc = run_captured([str(cargo), "--version", "--verbose"], GIT_TIMEOUT_S)
    record = {
        "schema_version": 1,
        "kind": "karasu_build",
        "built_at_utc": utc_timestamp(),
        "repository": str(repo),
        "ref": ref,
        "commit": commit,
        "profile": "release",
        "cargo_version": rustc.stdout.strip(),
        "binary": str(binary),
        "binary_sha256": sha256_file(binary),
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def build_record_for(binary: Path) -> dict[str, Any] | None:
    """The build record of a karasu-cli built by :func:`build_karasu`, if ``binary`` is one."""
    candidate = (
        binary.resolve().parents[2] / "build.json" if len(binary.resolve().parents) > 2 else None
    )
    if candidate is None or not candidate.is_file():
        return None
    record: dict[str, Any] = json.loads(candidate.read_text(encoding="utf-8"))
    return record if Path(record.get("binary", "")).resolve() == binary.resolve() else None


def _git_archive(git: Path, repo: Path, commit: str) -> bytes:
    import subprocess

    try:
        completed = subprocess.run(
            [str(git), "-C", str(repo), "archive", "--format=tar", commit],
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BuildError(f"git archive failed: {error}") from error
    if completed.returncode != 0:
        raise BuildError(f"git archive failed: {completed.stderr.decode(errors='replace').strip()}")
    return completed.stdout
