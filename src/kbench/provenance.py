"""Hashes and suite state recorded with every measurement."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kbench import __version__
from kbench.process import run_captured

_HASH_CHUNK_BYTES = 1 << 20

# Git answers these queries from local metadata; the limit only guards against a hung process.
_GIT_TIMEOUT_S = 30.0


def utc_timestamp() -> str:
    """The current UTC time to the second, as ISO 8601 with a ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """The SHA-256 of a file's bytes, as lowercase hexadecimal."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def suite_root() -> Path | None:
    """The checkout this package runs from, or ``None`` when it is not run from a checkout.

    The package lives in ``<root>/src/kbench``; the root is recognised by its
    ``pyproject.toml``.
    """
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").is_file() else None


def suite_state(root: Path | None, git: Path | None) -> dict[str, Any]:
    """The suite's version, commit and lockfile, so a record names the code that produced it.

    ``git_commit`` is ``None`` when there is no checkout, no git, or no commit yet;
    ``git_dirty`` is ``None`` when it cannot be determined. Untracked files count as dirty,
    because they can change what the suite runs.
    """
    commit: str | None = None
    dirty: bool | None = None
    lockfile_sha256: str | None = None

    if root is not None:
        lockfile = root / "uv.lock"
        if lockfile.is_file():
            lockfile_sha256 = sha256_file(lockfile)
        if git is not None and (root / ".git").exists():
            head = run_captured(
                [str(git), "-C", str(root), "rev-parse", "--verify", "--quiet", "HEAD"],
                _GIT_TIMEOUT_S,
            )
            if head.exit_status == 0 and head.stdout.strip():
                commit = head.stdout.strip()
            status = run_captured(
                [str(git), "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
                _GIT_TIMEOUT_S,
            )
            if status.exit_status == 0:
                dirty = bool(status.stdout.strip())

    return {
        "version": __version__,
        "git_commit": commit,
        "git_dirty": dirty,
        "lockfile_sha256": lockfile_sha256,
    }
