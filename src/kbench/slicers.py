"""Slicer adapters: how each slicer is told to slice a case (docs/SLICERS.md).

An adapter turns (model, target, output path) into an argument list. It never interprets the
slicer's output; the print file is read by UVTools and the run is measured by the runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kbench.config import ConfigError, Target

KARASU_SETTINGS = {"printer", "resin", "format", "extension"}


@dataclass(frozen=True)
class SliceJob:
    """One slicing command and where its print file appears."""

    argv: list[str]
    output: Path
    log: Path | None


def karasu_job(
    executable: Path, model: Path, target: Target, output_stem: Path, *, log: Path | None = None
) -> SliceJob:
    """The karasu-cli command for ``model`` on ``target``.

    The model is read as millimetres and centred on the plate (``--center``); it already stands
    on ``z = 0``. Printer, resin and format come from the target's ``[slicers.karasu]`` table;
    the print setting is the catalog's for that printer and resin. ``log`` adds ``--log``, used
    only in untimed warm-up runs to record karasu-slicer's own phase durations.
    """
    settings = _settings(target, "karasu", KARASU_SETTINGS)
    output = output_stem.with_suffix(settings["extension"])
    argv = [
        str(executable),
        "slice",
        "--model",
        str(model),
        "--units",
        "mm",
        "--printer",
        settings["printer"],
        "--resin",
        settings["resin"],
        "--format",
        settings["format"],
        "--output",
        str(output),
        "--center",
        "--no-progress",
    ]
    if log is not None:
        argv += ["--log", str(log)]
    return SliceJob(argv, output, log)


def _settings(target: Target, slicer: str, keys: set[str]) -> Mapping[str, str]:
    if slicer not in target.slicers:
        raise ConfigError(f"target {target.id!r} has no [slicers.{slicer}] table")
    settings = target.slicers[slicer]
    if set(settings) != keys:
        raise ConfigError(f"target {target.id!r} [slicers.{slicer}] needs exactly {sorted(keys)}")
    return settings
