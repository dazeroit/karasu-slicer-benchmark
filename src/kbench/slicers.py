"""Slicer adapters: how each slicer is told to slice a case (docs/SLICERS.md).

An adapter turns (model, target, output path) into an argument list. It never interprets the
slicer's output; the print file is read by UVTools and the run is measured by the runner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from kbench.config import ConfigError, Target, repository_path

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
    printer, resin = (_profile(settings[key]) for key in ("printer", "resin"))
    argv = [
        str(executable),
        "slice",
        "--model",
        str(model),
        "--units",
        "mm",
        "--printer",
        printer,
        "--resin",
        resin,
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


def _profile(value: str) -> str:
    """A catalog id as it is, or a suite-authored profile file (``*.json``, relative to
    ``targets/``) as an absolute path."""
    return str(repository_path("targets", value)) if value.endswith(".json") else value


PRUSASLICER_SETTINGS = {
    "display_width_mm",
    "display_height_mm",
    "display_pixels_x",
    "display_pixels_y",
    "display_orientation",
    "max_print_height_mm",
    "extension",
}


def prusaslicer_job(
    executable: Path, model: Path, target: Target, output_stem: Path, *, log: Path | None = None
) -> SliceJob:
    """The PrusaSlicer command for ``model`` on ``target`` (``log`` is not used).

    Only documented command-line options are given (``--help-sla``), no preset: the panel is the
    target's, from its ``[slicers.prusaslicer]`` table; the bed is the panel; the model is centred
    on it. Supports, pad and hollowing are off; ``--gamma-correction 0`` thresholds the masks
    (no anti-aliasing), as karasu-cli's default does; exposure values only fill the file.
    """
    del log
    settings = _settings(target, "prusaslicer", PRUSASLICER_SETTINGS)
    output = output_stem.with_suffix(settings["extension"])
    width = float(settings["display_width_mm"])
    height = float(settings["display_height_mm"])
    layer = f"{target.layer_height_mm:g}"
    argv = [
        str(executable),
        "--export-sla",
        "--printer-technology",
        "SLA",
        "--display-width",
        settings["display_width_mm"],
        "--display-height",
        settings["display_height_mm"],
        "--display-pixels-x",
        settings["display_pixels_x"],
        "--display-pixels-y",
        settings["display_pixels_y"],
        "--display-orientation",
        settings["display_orientation"],
        "--bed-shape",
        f"0x0,{width:g}x0,{width:g}x{height:g},0x{height:g}",
        "--max-print-height",
        settings["max_print_height_mm"],
        "--layer-height",
        layer,
        "--initial-layer-height",
        layer,
        "--no-supports-enable",
        "--no-pad-enable",
        "--no-hollowing-enable",
        "--gamma-correction",
        "0",
        "--exposure-time",
        "2",
        "--initial-exposure-time",
        "25",
        "--faded-layers",
        "3",
        "--center",
        f"{width / 2:g},{height / 2:g}",
        "--output",
        str(output),
        str(model),
    ]
    return SliceJob(argv, output, None)


DRAGONFRUIT_SETTINGS = {"extension"}


def dragonfruit_job(
    executable: Path, model: Path, target: Target, output_stem: Path, *, log: Path | None = None
) -> SliceJob:
    """The DragonFruit command-line slice for ``model`` on ``target`` (``log`` is not used).

    Only documented options are given (``slice run --help``): the plate and the raster are the
    target's panel, the layer height the target's, anti-aliasing off. The format follows the
    output extension from the target's ``[slicers.dragonfruit]`` table. No printer preset is
    used, so the file declares no mirroring.
    """
    del log
    settings = _settings(target, "dragonfruit", DRAGONFRUIT_SETTINGS)
    output = output_stem.with_suffix(settings["extension"])
    panel = target.panel
    argv = [
        str(executable),
        "slice",
        "run",
        str(model),
        "--output",
        str(output),
        "--layer-height",
        f"{target.layer_height_mm:g}",
        "--build-width-mm",
        f"{panel.resolution_x * panel.pitch_x_mm:.6g}",
        "--build-depth-mm",
        f"{panel.resolution_y * panel.pitch_y_mm:.6g}",
        "--source-width-px",
        str(panel.resolution_x),
        "--source-height-px",
        str(panel.resolution_y),
        "--anti-aliasing",
        "Off",
    ]
    return SliceJob(argv, output, None)


def _settings(target: Target, slicer: str, keys: set[str]) -> Mapping[str, str]:
    if slicer not in target.slicers:
        raise ConfigError(f"target {target.id!r} has no [slicers.{slicer}] table")
    settings = target.slicers[slicer]
    if set(settings) != keys:
        raise ConfigError(f"target {target.id!r} [slicers.{slicer}] needs exactly {sorted(keys)}")
    return settings


JobBuilder = Callable[..., SliceJob]


@dataclass(frozen=True)
class Adapter:
    """A slicer the suite can drive: its name in suites, its tool in the inventory, its jobs."""

    name: str
    tool: str
    job: JobBuilder


ADAPTERS: dict[str, Adapter] = {
    "karasu": Adapter("karasu", "karasu-cli", karasu_job),
    "prusaslicer": Adapter("prusaslicer", "PrusaSlicer", prusaslicer_job),
    "dragonfruit": Adapter("dragonfruit", "dragonfruit-cli", dragonfruit_job),
}
