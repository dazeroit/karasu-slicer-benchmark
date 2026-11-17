"""Shared test helpers."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from support import MakeScript


@pytest.fixture
def make_script(tmp_path: Path) -> MakeScript:
    """Return a factory that writes an executable POSIX shell script into ``<tmp>/bin``."""
    directory = tmp_path / "bin"
    directory.mkdir(exist_ok=True)

    def make(name: str, body: str) -> Path:
        path = directory / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    return make
