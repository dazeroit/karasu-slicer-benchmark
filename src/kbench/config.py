"""Benchmark targets (``targets/*.toml``) and suites (``suites/*.toml``).

Both are validated strictly: unknown keys, missing keys and wrong types are errors, so that a
typing mistake never silently changes what a run measures.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kbench.geometry.raster import Panel


class ConfigError(ValueError):
    """A target or suite file is malformed."""


@dataclass(frozen=True)
class Target:
    """A benchmark printer: its panel, its layer height and each slicer's settings for it."""

    id: str
    description: str
    panel: Panel
    layer_height_mm: float
    slicers: Mapping[str, Mapping[str, str]]
    source: Mapping[str, Any]
    sha256: str


@dataclass(frozen=True)
class Timing:
    warmup: int
    repetitions: int
    timeout_s: float


@dataclass(frozen=True)
class Case:
    id: str
    model: str
    target: str
    slicers: tuple[str, ...]
    analyze: bool


@dataclass(frozen=True)
class Suite:
    id: str
    description: str
    timing: Timing
    cases: tuple[Case, ...]
    sha256: str


def repository_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def _load(path: Path) -> tuple[dict[str, Any], str]:
    import hashlib

    data = path.read_bytes()
    try:
        return tomllib.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest()
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path.name}: {error}") from error


def _check_keys(
    where: str, table: Mapping[str, Any], required: set[str], optional: set[str] = frozenset()
) -> None:
    unknown = set(table) - required - optional
    missing = required - set(table)
    if unknown or missing:
        raise ConfigError(
            f"{where}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}"
        )


def _number(where: str, value: Any, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{where}: {value!r} is not a number")
    if positive and value <= 0:
        raise ConfigError(f"{where}: {value!r} must be positive")
    return float(value)


def _integer(where: str, value: Any, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{where}: {value!r} must be an integer of at least {minimum}")
    return value


def load_target(path: Path) -> Target:
    document, digest = _load(path)
    where = path.name
    _check_keys(where, document, {"id", "description", "panel", "source", "slicers"})
    panel = document["panel"]
    _check_keys(
        f"{where} [panel]",
        panel,
        {"resolution_x", "resolution_y", "pitch_x_mm", "pitch_y_mm", "layer_height_mm"},
    )
    slicers = document["slicers"]
    if not isinstance(slicers, dict) or not slicers:
        raise ConfigError(f"{where}: [slicers] must name at least one slicer")
    for name, settings in slicers.items():
        if not isinstance(settings, dict) or not all(isinstance(v, str) for v in settings.values()):
            raise ConfigError(f"{where} [slicers.{name}]: values must be strings")
    target_id = str(document["id"])
    if f"{target_id}.toml" != path.name:
        raise ConfigError(f"{where}: id {target_id!r} does not match the file name")
    return Target(
        id=target_id,
        description=str(document["description"]),
        panel=Panel(
            resolution_x=_integer(f"{where} resolution_x", panel["resolution_x"], 1),
            resolution_y=_integer(f"{where} resolution_y", panel["resolution_y"], 1),
            pitch_x_mm=_number(f"{where} pitch_x_mm", panel["pitch_x_mm"]),
            pitch_y_mm=_number(f"{where} pitch_y_mm", panel["pitch_y_mm"]),
        ),
        layer_height_mm=_number(f"{where} layer_height_mm", panel["layer_height_mm"]),
        slicers={name: dict(settings) for name, settings in slicers.items()},
        source=dict(document["source"]),
        sha256=digest,
    )


def load_targets(directory: Path) -> dict[str, Target]:
    targets = [load_target(path) for path in sorted(directory.glob("*.toml"))]
    return {target.id: target for target in targets}


def load_suite(path: Path) -> Suite:
    document, digest = _load(path)
    where = path.name
    _check_keys(where, document, {"id", "description", "timing", "cases"})
    timing = document["timing"]
    _check_keys(f"{where} [timing]", timing, {"warmup", "repetitions", "timeout_s"})
    cases = []
    for index, entry in enumerate(document["cases"]):
        _check_keys(
            f"{where} case {index}", entry, {"model", "target", "slicers"}, {"id", "analyze"}
        )
        if not isinstance(entry["slicers"], list) or not entry["slicers"]:
            raise ConfigError(f"{where} case {index}: slicers must be a non-empty list")
        cases.append(
            Case(
                id=str(entry.get("id", f"{entry['model']}@{entry['target']}")),
                model=str(entry["model"]),
                target=str(entry["target"]),
                slicers=tuple(str(name) for name in entry["slicers"]),
                analyze=bool(entry.get("analyze", True)),
            )
        )
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise ConfigError(f"{where}: case ids must be unique")
    return Suite(
        id=str(document["id"]),
        description=str(document["description"]),
        timing=Timing(
            warmup=_integer(f"{where} warmup", timing["warmup"], 0),
            repetitions=_integer(f"{where} repetitions", timing["repetitions"], 1),
            timeout_s=_number(f"{where} timeout_s", timing["timeout_s"]),
        ),
        cases=tuple(cases),
        sha256=digest,
    )
