from __future__ import annotations

import hashlib
import re
from pathlib import Path

from kbench import __version__
from kbench.provenance import sha256_file, suite_root, suite_state, utc_timestamp


def test_sha256_of_known_content(tmp_path: Path) -> None:
    path = tmp_path / "abc.bin"
    path.write_bytes(b"abc")
    # FIPS 180-2, appendix B.1.
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_of_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    assert sha256_file(path) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_spans_read_chunks(tmp_path: Path) -> None:
    data = bytes(range(256)) * (3 * 4096) + b"tail"  # 3 MiB and 4 bytes: several chunks.
    path = tmp_path / "large.bin"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_suite_root_is_this_checkout() -> None:
    root = suite_root()
    assert root is not None
    assert (root / "src" / "kbench" / "provenance.py").is_file()


def test_suite_state_without_checkout_or_git(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_bytes(b"abc")
    state = suite_state(tmp_path, git=None)
    assert state == {
        "version": __version__,
        "git_commit": None,
        "git_dirty": None,
        "lockfile_sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    }


def test_suite_state_without_root() -> None:
    state = suite_state(None, git=None)
    assert state["git_commit"] is None
    assert state["lockfile_sha256"] is None


def test_utc_timestamp_format() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", utc_timestamp())
