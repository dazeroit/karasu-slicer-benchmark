"""UVTools as the shared, independent reader of print files (``UVtoolsCmd``).

Only the documented command line and its printed output are used (docs/SLICERS.md, UVTools):

- ``extract <file> <dir> -c Layers``: every layer as an 8-bit PNG (``layerNNN.png``);
- ``print-properties <file>``: the file's properties, one ``Name: value`` per line;
- ``print-properties <file> -r <first>:<last>``: per-layer blocks opened by ``# Layer: <index>``;
- ``print-issues <file> -i -o -r -s -t -p -e``: one issue per line,
  ``<type>, <layer>, <area>px², {X=…,Y=…,Width=…,Height=…}``, after ``Issues: <count>``.

``--no-progress`` is a global option and precedes the command. Formats were observed with
UVTools v7.1.2; a line that does not parse is kept in ``unparsed``, never dropped silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kbench.process import CapturedProcess, run_captured

# Properties worth recording and checking, with how to read them.
GLOBAL_NUMBERS = (
    "ResolutionX",
    "ResolutionY",
    "DisplayWidth",
    "DisplayHeight",
    "PixelWidth",
    "PixelHeight",
    "MachineZ",
    "LayerHeight",
    "LayerCount",
    "BottomLayerCount",
    "TransitionLayerCount",
    "BottomExposureTime",
    "ExposureTime",
    "BottomLiftHeight",
    "BottomLiftSpeed",
    "LiftHeight",
    "LiftSpeed",
    "RetractSpeed",
    "BottomLightPWM",
    "LightPWM",
    "AntiAliasing",
    "PrintTime",
    "PrintHeight",
    "Volume",
)
GLOBAL_TEXTS = ("MachineName", "DisplayMirror", "FileExtension", "Version")
LAYER_NUMBERS = (
    "Index",
    "PositionZ",
    "RelativePositionZ",
    "ExposureTime",
    "NonZeroPixelCount",
    "Area",
)

_ISSUE = re.compile(
    r"^(?P<type>[A-Za-z][A-Za-z ]*?), (?P<layer>\d+), (?P<area>[\d.]+)px², "
    r"\{X=(?P<x>-?\d+),Y=(?P<y>-?\d+),Width=(?P<w>\d+),Height=(?P<h>\d+)\}$"
)
_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")

ISSUE_FLAGS = ("-i", "-o", "-r", "-s", "-t", "-p", "-e")


class UVToolsError(RuntimeError):
    """UVtoolsCmd failed or printed something the suite cannot read."""


@dataclass(frozen=True)
class UVTools:
    """One UVtoolsCmd executable and the timeout for each of its commands."""

    executable: Path
    timeout_s: float = 1800.0

    def _run(self, *arguments: str) -> CapturedProcess:
        result = run_captured([str(self.executable), "--no-progress", *arguments], self.timeout_s)
        if result.exit_status != 0:
            detail = result.start_error or (result.stderr.strip() or result.stdout.strip())[-2000:]
            raise UVToolsError(
                f"UVtoolsCmd {arguments[0]} failed (status {result.exit_status}, "
                f"timed out {result.timed_out}): {detail}"
            )
        return result

    def extract_layers(self, print_file: Path, out_dir: Path) -> list[Path]:
        """Decode every layer into ``out_dir`` and return the PNG files in layer order."""
        self._run("extract", str(print_file), str(out_dir), "-c", "Layers")
        files = sorted(
            out_dir.glob("layer*.png"), key=lambda path: int(re.sub(r"\D", "", path.stem))
        )
        if not files:
            raise UVToolsError(f"UVtoolsCmd extracted no layers from {print_file.name}")
        return files

    def properties(self, print_file: Path) -> tuple[str, dict[str, Any]]:
        """The raw text and the parsed global properties of ``print_file``."""
        text = self._run("print-properties", str(print_file)).stdout
        return text, parse_properties(text)

    def layer_properties(self, print_file: Path, count: int) -> tuple[str, list[dict[str, Any]]]:
        """The raw text and per-layer properties of layers ``0`` to ``count - 1``."""
        text = self._run("print-properties", str(print_file), "-r", f"0:{count - 1}").stdout
        return text, parse_layer_properties(text)

    def issues(self, print_file: Path) -> tuple[str, dict[str, Any]]:
        """The raw text and parsed issues, every detector enabled."""
        text = self._run("print-issues", str(print_file), *ISSUE_FLAGS).stdout
        return text, parse_issues(text)


def _value(text: str) -> Any:
    stripped = text.strip()
    return float(stripped) if _NUMBER.match(stripped) else stripped


def _pairs(lines: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in lines:
        name, separator, value = line.partition(": ")
        if separator and name and " " not in name and name not in pairs:
            pairs[name] = value
    return pairs


def parse_properties(text: str) -> dict[str, Any]:
    """The recorded global properties (``GLOBAL_NUMBERS`` as numbers, ``GLOBAL_TEXTS`` as text).

    Only the first occurrence of a name counts. A missing property is ``None``.
    """
    head = text.split("\n# Layer:", 1)[0]
    pairs = _pairs(head.splitlines())
    result: dict[str, Any] = {}
    for name in GLOBAL_NUMBERS:
        value = _value(pairs[name]) if name in pairs else None
        result[name] = value if isinstance(value, float) or value is None else None
    for name in GLOBAL_TEXTS:
        result[name] = pairs.get(name)
    return result


def parse_layer_properties(text: str) -> list[dict[str, Any]]:
    """One record per ``# Layer: <index>`` block, with the ``LAYER_NUMBERS`` fields."""
    blocks = re.split(r"^# Layer: (\d+)\s*$", text, flags=re.MULTILINE)
    layers = []
    for number, body in zip(blocks[1::2], blocks[2::2], strict=True):
        pairs = _pairs(body.splitlines())
        record: dict[str, Any] = {"block": int(number)}
        for name in LAYER_NUMBERS:
            value = _value(pairs[name]) if name in pairs else None
            record[name] = value if isinstance(value, float) else None
        layers.append(record)
    return layers


def parse_issues(text: str) -> dict[str, Any]:
    """The declared count, every parsed issue, counts by type, and unparsed lines."""
    declared = None
    issues = []
    unparsed = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("Opening file", "Detecting issues")):
            continue
        if stripped.startswith("Issues:"):
            declared = int(stripped.split(":", 1)[1])
            continue
        match = _ISSUE.match(stripped)
        if match is None:
            unparsed.append(stripped)
            continue
        issues.append(
            {
                "type": match["type"],
                "layer": int(match["layer"]),
                "area_px": float(match["area"]),
                "bounds_px": [int(match["x"]), int(match["y"]), int(match["w"]), int(match["h"])],
            }
        )
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["type"]] = counts.get(issue["type"], 0) + 1
    return {
        "declared_count": declared,
        "count": len(issues),
        "by_type": dict(sorted(counts.items())),
        "issues": issues,
        "unparsed": unparsed,
    }
