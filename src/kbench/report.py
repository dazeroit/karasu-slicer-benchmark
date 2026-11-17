"""Markdown report of a run: the measured values, with their conditions, and nothing judged."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

WSL_NOTE = " (WSL: not native Linux or Windows)"


def _load(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return record


def _number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.{digits}f}"


def _distinct(case: dict[str, Any]) -> str:
    determinism = case["determinism"]
    text = str(len(determinism["distinct_sha256"]))
    decoded = case.get("analysis", {}).get("decoded_layers")
    if decoded and len(determinism["distinct_sha256"]) > 1:
        text += f" (layers: {decoded['distinct']} of {decoded['files']} decoded)"
    elif determinism.get("distinct_layers_sha256"):
        text += f" (layers: {len(determinism['distinct_layers_sha256'])})"
    return text


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def slicer_label(case: dict[str, Any]) -> str:
    """The slicer and its version as the report shows them."""
    if case.get("manual"):
        return f"{case['slicer']} {case['manual']['slicer_version']} (manual)"
    tool = case.get("slicer_tool")
    label = (
        f"{case['slicer']} ({tool['version']})" if tool and tool.get("version") else case["slicer"]
    )
    build = case.get("slicer_build")
    if build:
        label = label[:-1] + f", {build['commit'][:7]})" if label.endswith(")") else label
    return label


def _conditions(run: dict[str, Any], cases: Sequence[dict[str, Any]]) -> list[str]:
    environment = run["environment_before"]
    cpu, memory, os_info, suite = (
        environment["cpu"],
        environment["memory"] or {},
        environment["os"],
        environment["suite"],
    )
    timing = run["suite"]["timing"]
    lines = [
        f"### Run {run['run_id']}",
        "",
        f"Suite `{run['suite']['id']}`: {run['suite']['description']} "
        f"Started {run['started_at_utc']}, ended {run['ended_at_utc']}.",
        "",
        f"- Host: {cpu['model']}, {cpu['physical_cores']} cores / {cpu['logical_cpus']} threads, "
        f"{_number((memory.get('total_kib') or 0) / 1048576, 1)} GiB; {os_info['distribution']}, "
        f"kernel {os_info['release']}{WSL_NOTE if os_info['wsl'] else ''}.",
        f"- Suite: version {suite['version']}, commit {suite['git_commit'] or 'none'}"
        f"{' (uncommitted changes)' if suite['git_dirty'] else ''}.",
    ]
    if timing is None:
        lines.append("- Manual export: no timing.")
    else:
        lines.append(
            f"- Timing: {timing['warmup']} warm-up and {timing['repetitions']} timed "
            "runs per case, serial, warm page cache; analysis after all timing."
        )
    if run.get("launcher_floor_kib"):
        lines.append(
            f"- Peak memory floor: {_number(run['launcher_floor_kib']['median'] / 1024, 1)} MiB "
            "(what the launcher reports for a program that uses almost none; a peak at the "
            "floor means at most that much)."
        )
    tools = {tool["name"]: tool for tool in run["tools"]}
    shown = {case["slicer_tool"]["name"] for case in cases if case.get("slicer_tool")}
    for name in sorted(shown | {"UVtoolsCmd"}):
        tool = tools.get(name)
        if tool and tool["ok"]:
            lines.append(f"- {name}: {tool['version']}, SHA-256 `{tool['sha256'][:16]}…`.")
    builds = {
        json.dumps(case.get("slicer_build"), sort_keys=True)
        for case in cases
        if case.get("slicer_build")
    }
    for build in sorted(builds):
        record = json.loads(build)
        lines.append(
            f"- karasu-cli built from commit `{record['commit']}` "
            f"({record['cargo_version'].splitlines()[0]})."
        )
    for case in cases:
        manual = case.get("manual")
        if manual:
            lines.append(
                f"- Manual export `{manual['source_name']}` from {manual['slicer']} "
                f"{manual['slicer_version']}, SHA-256 `{manual['sha256'][:16]}…`, model SHA-256 "
                f"`{manual['stl_sha256'][:16]}…`{'; ' + manual['note'] if manual['note'] else ''}."
            )
    lines.append("")
    return lines


def render(run_dirs: Sequence[Path] | Path) -> str:
    """The report of one run, or of several runs side by side, as Markdown."""
    directories = [run_dirs] if isinstance(run_dirs, Path) else list(run_dirs)
    runs = [_load(directory / "run.json") for directory in directories]
    per_run = [
        [_load(directory / entry["record"]) for entry in run["cases"]]
        for directory, run in zip(directories, runs, strict=True)
    ]
    cases = [case for run_cases in per_run for case in run_cases]
    title = runs[0]["run_id"] if len(runs) == 1 else f"{len(runs)} runs"
    lines = [f"# Report: {title}", "", "## Conditions", ""]
    for run, run_cases in zip(runs, per_run, strict=True):
        lines += _conditions(run, run_cases)

    lines += ["## Performance", ""]
    rows = []
    for case in cases:
        perf = case["performance"]
        if perf is None:
            continue
        wall = perf["wall_s"]
        rss = perf["peak_rss_kib"]
        rows.append(
            [
                case["case"],
                slicer_label(case),
                str(len(case["cpus"])) if case.get("cpus") else "all",
                _number(wall["median"]),
                _number(wall["min"]),
                _number(wall["max"]),
                _number(wall["iqr"]),
                _number(perf["user_s"]["median"]),
                _number(perf["system_s"]["median"]),
                _number(rss["median"] / 1024 if rss["median"] is not None else None, 1),
                _number(
                    int(perf["output_bytes"]["median"])
                    if perf["output_bytes"]["median"] is not None
                    else None
                ),
                f"{perf['timed_runs'] - perf['failed_runs']}/{perf['timed_runs']}",
                _distinct(case),
            ]
        )
    lines += _table(
        [
            "Case",
            "Slicer",
            "CPUs",
            "Wall median (s)",
            "Min",
            "Max",
            "IQR",
            "User (s)",
            "System (s)",
            "Peak RSS (MiB)",
            "Output (bytes)",
            "Succeeded",
            "Distinct outputs",
        ],
        rows,
    )
    lines += [
        "",
        "Distinct outputs counts the different SHA-256 among all runs of a case, warm-ups "
        "included: 1 means byte-identical files. When files differ, the brackets say whether "
        "their layers differ: up to three of them are decoded and their pixels compared (SL1 "
        "and SL1S layer images are hashed directly), so a creation time in the metadata does "
        "not pass for a different print.",
        "",
    ]

    analysed = [
        (case, _load(Path(case["directory"]) / "metrics.json"))
        for case in cases
        if case.get("analysis", {}).get("status") == "analysed"
    ]
    if analysed:
        lines += ["## Accuracy", ""]
        rows = []
        for case, metrics in analysed:
            summary = metrics["summary"]
            offset = metrics["placement"]["offset_mm"]
            orientation = metrics["orientation"]
            rows.append(
                [
                    case["case"],
                    slicer_label(case),
                    str(metrics["layer_count"]),
                    orientation["stored"] + (" (ambiguous)" if orientation["ambiguous"] else ""),
                    f"{_number(offset[0])}, {_number(offset[1])}",
                    f"{_number(summary['iou']['min'], 4)} / {_number(summary['iou']['mean'], 4)}",
                    " / ".join(
                        _number(summary[field][stat], 4)
                        for field, stat in (
                            ("boundary_mean_mm", "mean"),
                            ("boundary_p95_mm", "max"),
                            ("boundary_max_mm", "max"),
                        )
                    ),
                    _number(metrics["volume"]["error_vs_reference_pct"]),
                    _number(metrics["volume"]["error_vs_mesh_pct"]),
                    _number(metrics["height"]["error_mm"]),
                    _number(summary["edge_coverage_mae"]["mean"]),
                    _number(summary["stray_area_mm2"]["max"]),
                ]
            )
        lines += _table(
            [
                "Case",
                "Slicer",
                "Layers",
                "Stored orientation",
                "Placement dx, dy (mm)",
                "IoU min / mean",
                "Boundary mean / p95 max / max (mm)",
                "Volume vs reference (%)",
                "Volume vs mesh (%)",
                "Height error (mm)",
                "Edge coverage MAE",
                "Stray max (mm²)",
            ],
            rows,
        )
        lines += ["", "### Bodies", ""]
        rows = []
        for case, metrics in analysed:
            for body in metrics["bodies"]:
                phase = body["z_phase"]
                rows.append(
                    [
                        case["case"],
                        slicer_label(case),
                        body["name"],
                        _number(body["volume_error_pct"]),
                        _number(phase["phase"])
                        if phase["phase"] is not None
                        else f"– ({phase['reason']})",
                        _number(phase.get("outline_offset_mm"), 4),
                    ]
                )
        lines += _table(
            [
                "Case",
                "Slicer",
                "Body",
                "Volume vs reference (%)",
                "Z phase (layers)",
                "Outline offset (mm)",
            ],
            rows,
        )

    lines += feature_tables(analysed)
    lines += side_by_side(cases, {id(case): metrics for case, metrics in analysed})
    lines += determinism(cases)
    if analysed:
        lines += ["", "## File properties (UVTools)", ""]
        rows = []
        for case in cases:
            analysis = case.get("analysis", {})
            if analysis.get("status") != "analysed":
                continue
            props, checks = analysis["properties"], analysis["conformity"]
            rows.append(
                [
                    case["case"],
                    slicer_label(case),
                    f"{_number(props['ResolutionX'], 0)} × {_number(props['ResolutionY'], 0)}",
                    f"{_number(props['PixelWidth'], 4)} × {_number(props['PixelHeight'], 4)}",
                    _number(props["LayerHeight"], 3),
                    f"{_number(props['LayerCount'], 0)} "
                    f"(expected {checks['layer_count']['expected']})",
                    _number(props["BottomLayerCount"], 0),
                    f"{_number(props['BottomExposureTime'], 2)} / "
                    f"{_number(props['ExposureTime'], 2)}",
                    _number(props["AntiAliasing"], 0),
                    str(props.get("DisplayMirror") or "–"),
                    ", ".join(name for name, check in checks.items() if check["matches"] is False)
                    or "all match",
                ]
            )
        lines += _table(
            [
                "Case",
                "Slicer",
                "Resolution",
                "Pixel (mm)",
                "Layer (mm)",
                "Layers",
                "Bottom layers",
                "Exposure bottom / normal (s)",
                "AA",
                "Mirror",
                "Differs from target",
            ],
            rows,
        )

        lines += ["", "## UVTools issues", ""]
        rows = []
        for case in cases:
            analysis = case.get("analysis", {})
            if analysis.get("status") != "analysed":
                continue
            issues = analysis["issues"]
            if issues is None:
                error = analysis.get("uvtools_issues_error", "").splitlines()[0][:160]
                rows.append(
                    [
                        case["case"],
                        slicer_label(case),
                        "–",
                        f"UVTools could not read the file: {error}",
                        "–",
                    ]
                )
                continue
            by_type = (
                ", ".join(f"{name}: {count}" for name, count in issues["by_type"].items()) or "none"
            )
            rows.append(
                [
                    case["case"],
                    slicer_label(case),
                    str(issues["count"]),
                    by_type,
                    str(len(issues["unparsed"])),
                ]
            )
        lines += _table(["Case", "Slicer", "Issues", "By type", "Unparsed lines"], rows)
        lines += [
            "",
            "UVTools' detectors are heuristics: their findings are observations, not ground truth.",
            "",
        ]

    failures = []
    for case in cases:
        for attempt in case["attempts"]:
            if not attempt["succeeded"]:
                failures.append(
                    [
                        case["case"],
                        slicer_label(case),
                        str(attempt["attempt"]),
                        str(attempt["exit_status"]),
                        _number(attempt["timed_out"]),
                    ]
                )
        analysis = case.get("analysis", {})
        if analysis.get("status") == "failed":
            failures.append(
                [case["case"], slicer_label(case), "analysis", analysis.get("error", ""), "–"]
            )
    lines += ["## Failures", ""]
    lines += (
        _table(["Case", "Slicer", "Attempt", "Exit status / error", "Timed out"], failures)
        if failures
        else ["None."]
    )
    lines.append("")
    return "\n".join(lines)


def _perf(case: dict[str, Any], field: str) -> float | None:
    perf = case.get("performance")
    return perf[field]["median"] if perf else None


def _cpu_total(case: dict[str, Any]) -> float | None:
    user, system = _perf(case, "user_s"), _perf(case, "system_s")
    return user + system if user is not None and system is not None else None


def _rss_mib(case: dict[str, Any]) -> float | None:
    value = _perf(case, "peak_rss_kib")
    return value / 1024 if value is not None else None


def _issues(case: dict[str, Any]) -> float | str | None:
    analysis = case.get("analysis", {})
    if analysis.get("issues"):
        return float(analysis["issues"]["count"])
    return "unreadable" if analysis.get("status") == "analysed" else None


def _phases(metrics: dict[str, Any] | None) -> str | None:
    if metrics is None:
        return None
    text = ", ".join(
        f"{body['name']} {_number(body['z_phase']['phase'])}"
        for body in metrics["bodies"]
        if body["z_phase"]["phase"] is not None
    )
    return text or None


def _outline(metrics: dict[str, Any] | None) -> float | None:
    if metrics is None:
        return None
    offsets = [
        body["z_phase"].get("outline_offset_mm")
        for body in metrics["bodies"]
        if body["z_phase"].get("outline_offset_mm") is not None
    ]
    return float(np.median(offsets)) if offsets else None


def _smallest(metrics: dict[str, Any] | None, kind: str) -> float | None:
    if metrics is None:
        return None
    return (metrics.get("features_smallest_resolved") or {}).get(kind)


Metric = tuple[str, int, Any]

# Label, digits, and the value (a number, a text, or None) from a case and its metrics.
SIDE_BY_SIDE: tuple[Metric, ...] = (
    ("Wall median (s)", 3, lambda c, m: _perf(c, "wall_s")),
    ("User + system CPU (s)", 3, lambda c, m: _cpu_total(c)),
    ("Peak RSS (MiB)", 1, lambda c, m: _rss_mib(c)),
    ("Output (bytes)", 0, lambda c, m: _perf(c, "output_bytes")),
    ("Stored orientation", 0, lambda c, m: m["orientation"]["stored"] if m else None),
    ("Placement dx (mm)", 3, lambda c, m: m["placement"]["offset_mm"][0] if m else None),
    ("Placement dy (mm)", 3, lambda c, m: m["placement"]["offset_mm"][1] if m else None),
    ("IoU min", 4, lambda c, m: m["summary"]["iou"]["min"] if m else None),
    ("IoU mean", 4, lambda c, m: m["summary"]["iou"]["mean"] if m else None),
    ("Boundary mean (mm)", 4, lambda c, m: m["summary"]["boundary_mean_mm"]["mean"] if m else None),
    (
        "Boundary p95, worst layer (mm)",
        4,
        lambda c, m: m["summary"]["boundary_p95_mm"]["max"] if m else None,
    ),
    ("Boundary max (mm)", 4, lambda c, m: m["summary"]["boundary_max_mm"]["max"] if m else None),
    (
        "Volume vs reference (%)",
        3,
        lambda c, m: m["volume"]["error_vs_reference_pct"] if m else None,
    ),
    ("Height error (mm)", 3, lambda c, m: m["height"]["error_mm"] if m else None),
    ("Edge coverage MAE", 3, lambda c, m: m["summary"]["edge_coverage_mae"]["mean"] if m else None),
    ("Z phase (bodies)", 0, lambda c, m: _phases(m)),
    ("Outline offset, median of bodies (mm)", 4, lambda c, m: _outline(m)),
    ("Smallest pin (mm)", 2, lambda c, m: _smallest(m, "pin")),
    ("Smallest wall (mm)", 2, lambda c, m: _smallest(m, "wall")),
    ("Smallest hole (mm)", 2, lambda c, m: _smallest(m, "hole")),
    ("Smallest slot (mm)", 2, lambda c, m: _smallest(m, "slot")),
    ("UVTools issues", 0, lambda c, m: _issues(c)),
)


def _cell(value: Any, digits: int) -> str:
    if value is None:
        return "–"
    if isinstance(value, str):
        return value
    return _number(round(value) if digits == 0 else float(value), digits)


def side_by_side(cases: Sequence[dict[str, Any]], metrics: dict[int, dict[str, Any]]) -> list[str]:
    """For every case measured more than once (other slicers, other versions or other runs), one
    column each; with exactly two, a change column (second minus first)."""
    by_case: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_case.setdefault(case["case"], []).append(case)
    lines: list[str] = []
    for name, group in by_case.items():
        if len(group) < 2:
            continue
        if not lines:
            lines += ["", "## Side by side", ""]
        lines += [f"### {name}", ""]
        rows = []
        for label, digits, value_of in SIDE_BY_SIDE:
            values = [value_of(case, metrics.get(id(case))) for case in group]
            row = [label, *(_cell(value, digits) for value in values)]
            if len(group) == 2:
                first, second = values
                numeric = all(
                    isinstance(v, int | float) and not isinstance(v, bool) for v in values
                )
                row.append(_cell(second - first, digits) if numeric else "")
            rows.append(row)
        header = ["Metric", *(slicer_label(case) for case in group)]
        if len(group) == 2:
            header.append("Change")
        lines += _table(header, rows)
        lines.append("")
    return lines


def feature_tables(analysed: Sequence[tuple[dict[str, Any], dict[str, Any]]]) -> list[str]:
    """Measured size of every feature, by nominal size and kind (docs/METRICS.md, Features)."""
    lines: list[str] = []
    for case, metrics in analysed:
        features = metrics.get("features") or []
        if not features:
            continue
        if not lines:
            lines += [
                "",
                "## Features",
                "",
                "Measured size in mm (error against the reference in brackets); a pin or wall "
                "that did not print is *absent*, a hole or slot that closed is *closed*.",
                "",
            ]
        kinds = ("pin", "wall", "hole", "slot")
        sizes = sorted({feature["nominal_mm"] for feature in features})
        by_key = {(f["kind"], f["nominal_mm"]): f for f in features}
        rows = []
        for size in sizes:
            row = [_number(size, 2)]
            for kind in kinds:
                feature = by_key.get((kind, size))
                if feature is None:
                    row.append("")
                elif not feature["resolved"]:
                    row.append("absent" if kind in ("pin", "wall") else "closed")
                else:
                    row.append(f"{_number(feature['measured_mm'])} ({feature['error_mm']:+.3f})")
            rows.append(row)
        smallest = metrics.get("features_smallest_resolved", {})
        lines += [f"### {case['case']}: {slicer_label(case)}", ""]
        lines += _table(["Nominal (mm)", "Pin", "Wall", "Hole", "Slot"], rows)
        lines += [
            "",
            "Smallest size from which every larger one resolved: "
            + ", ".join(
                f"{kind} {_number(smallest.get(kind), 2)} mm" for kind in kinds if kind in smallest
            )
            + ".",
            "",
        ]
    return lines


def determinism(cases: Sequence[dict[str, Any]]) -> list[str]:
    """Outputs of the same model, target and slicer build across cases (CPU counts) and runs."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for case in cases:
        if case.get("attempts"):
            key = (case["model"]["id"], case["target"], slicer_label(case))
            groups.setdefault(key, []).append(case)
    rows = []
    for (model, target, slicer), group in groups.items():
        if len(group) < 2:
            continue
        attempts = [attempt for case in group for attempt in case["attempts"]]
        outputs = {a["output_sha256"] for a in attempts if a.get("output_sha256")}
        layers = {a["layers_sha256"] for a in attempts if a.get("layers_sha256")}
        cpus = ", ".join(str(len(case["cpus"])) if case.get("cpus") else "all" for case in group)
        rows.append(
            [
                model,
                target,
                slicer,
                cpus,
                str(len(attempts)),
                str(len(outputs)) + (f" (layers: {len(layers)})" if layers else ""),
            ]
        )
    if not rows:
        return []
    return [
        "",
        "## Determinism across cases",
        "",
        *_table(["Model", "Target", "Slicer", "CPUs per case", "Runs", "Distinct outputs"], rows),
        "",
        "One distinct output means every run, whatever its CPU count, wrote the same file.",
        "",
    ]


def write_report(run_dir: Path, others: Sequence[Path] = ()) -> Path:
    """Write ``report.md`` in ``run_dir`` (with ``others`` side by side when given)."""
    path = run_dir / "report.md" if not others else run_dir / "comparison.md"
    path.write_text(render([run_dir, *others]), encoding="utf-8")
    return path
