"""The suite's own reader of SL1 and SL1S archives (BD-018).

An SL1 or SL1S file is a ZIP archive holding ``config.ini`` (``key = value`` lines) and one 8-bit
greyscale PNG per layer, named ``<jobDir><index, 5 digits>.png``; ``layerHeight`` is the layer
height in mm and ``numFast + numSlow`` the layer count (observed in the files PrusaSlicer 2.8.1
and karasu-slicer 0.2.0-dev write, 2026-11-17). The archive is read as data: only the members
named that way are extracted, under names the suite chooses.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from kbench.reference import Layer

SL1_SUFFIXES = frozenset({".sl1", ".sl1s"})


class SL1Error(ValueError):
    """The archive is not a readable SL1 or SL1S file."""


def parse_config(text: str) -> dict[str, str]:
    """``key = value`` lines; other lines are ignored, the first occurrence of a key counts."""
    config: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() and key.strip() not in config:
            config[key.strip()] = value.strip()
    return config


def _layout(bundle: zipfile.ZipFile) -> tuple[dict[str, str], list[str], float]:
    try:
        config = parse_config(bundle.read("config.ini").decode("utf-8", errors="replace"))
    except KeyError:
        raise SL1Error("config.ini is missing") from None
    try:
        job = config["jobDir"]
        height = float(config["layerHeight"])
        count = int(config.get("numFast", "0")) + int(config.get("numSlow", "0"))
    except (KeyError, ValueError) as error:
        raise SL1Error(f"config.ini lacks a usable {error}") from None
    if count <= 0 or height <= 0.0:
        raise SL1Error(f"config.ini declares {count} layers of {height} mm")
    names = [f"{job}{index:05d}.png" for index in range(count)]
    present = set(bundle.namelist())
    missing = [name for name in names if name not in present]
    if missing:
        raise SL1Error(f"{len(missing)} layer images are missing, first {missing[0]}")
    return config, names, height


def read_sl1(path: Path, out_dir: Path) -> tuple[list[Path], dict[str, str], list[Layer]]:
    """Extract the layer images into ``out_dir`` and return them, ``config.ini`` and the
    schedule (uniform layers of ``layerHeight`` from ``z = 0``)."""
    try:
        bundle = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise SL1Error(f"{path.name} is not a ZIP archive: {error}") from error
    with bundle:
        config, names, height = _layout(bundle)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for index, name in enumerate(names):
            target = out_dir / f"layer{index:05d}.png"
            target.write_bytes(bundle.read(name))
            files.append(target)
    layers = [Layer(index, index * height, height) for index in range(len(names))]
    return files, config, layers


def layers_digest(path: Path) -> str | None:
    """SHA-256 over the layer images of an SL1 or SL1S file, in layer order; ``None`` for
    other files or unreadable archives.

    Two files with the same digest have identical layers even when their metadata (a creation
    time, for instance) differ.
    """
    if path.suffix.lower() not in SL1_SUFFIXES:
        return None
    try:
        with zipfile.ZipFile(path) as bundle:
            _, names, _ = _layout(bundle)
            digest = hashlib.sha256()
            for name in names:
                digest.update(bundle.read(name))
            return digest.hexdigest()
    except (zipfile.BadZipFile, SL1Error):
        return None
