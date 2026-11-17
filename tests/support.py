"""Helpers shared by the tests (importable because ``tests`` is on pytest's ``pythonpath``)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

posix_only = pytest.mark.skipif(os.name != "posix", reason="uses POSIX shell scripts as tools")

MakeScript = Callable[[str, str], Path]
