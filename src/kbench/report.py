"""Markdown report of a run: the measured values, with their conditions, and nothing judged."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


def _distinct(determinism: dict[str, Any]) -> str:
    text = str(len(determinism["distinct_sha256"]))
    if determinism.get("distinct_layers_sha256"):
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
    return (
        f"{case['slicer']} ({tool['version']})" if tool and tool.get("version") else case["slicer"]
    )


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
                _distinct(case["determinism"]),
            ]
        )
    lines += _table(
        [
            "Case",
            "Slicer",
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
        "included: 1 means byte-identical files. For SL1 and SL1S files, the count in brackets "
        "covers the layer images alone, without metadata such as a creation time.",
        "",
    ]

    analysed = [
        (case, _load(Path(case["directory"]) / "metrics.json"))
        for case in cases
        if case.get("analysis", {}).get("status") == "analysed"
    ]
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
                    _number(phase["area_scale"], 4),
                ]
            )
    lines += _table(
        ["Case", "Slicer", "Body", "Volume vs reference (%)", "Z phase (layers)", "Area scale"],
        rows,
    )

    lines += side_by_side(cases, dict((id(case), metrics) for case, metrics in analysed))
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
                f"{_number(props['LayerCount'], 0)} (expected {checks['layer_count']['expected']})",
                _number(props["BottomLayerCount"], 0),
                f"{_number(props['BottomExposureTime'], 2)} / {_number(props['ExposureTime'], 2)}",
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


SIDE_BY_SIDE: tuple[tuple[str, Any], ...] = (
    (
        "Wall median (s)",
        lambda c, m: _number(c["performance"]["wall_s"]["median"]) if c.get("performance") else "–",
    ),
    (
        "User + system CPU (s)",
        lambda c, m: (
            _number(c["performance"]["user_s"]["median"] + c["performance"]["system_s"]["median"])
            if c.get("performance") and c["performance"]["user_s"]["median"] is not None
            else "–"
        ),
    ),
    (
        "Peak RSS (MiB)",
        lambda c, m: (
            _number(c["performance"]["peak_rss_kib"]["median"] / 1024, 1)
            if c.get("performance") and c["performance"]["peak_rss_kib"]["median"] is not None
            else "–"
        ),
    ),
    (
        "Output (bytes)",
        lambda c, m: (
            _number(int(c["performance"]["output_bytes"]["median"]))
            if c.get("performance") and c["performance"]["output_bytes"]["median"] is not None
            else "–"
        ),
    ),
    ("Stored orientation", lambda c, m: m["orientation"]["stored"] if m else "–"),
    (
        "Placement dx, dy (mm)",
        lambda c, m: ", ".join(_number(v) for v in m["placement"]["offset_mm"]) if m else "–",
    ),
    ("IoU min", lambda c, m: _number(m["summary"]["iou"]["min"], 4) if m else "–"),
    ("IoU mean", lambda c, m: _number(m["summary"]["iou"]["mean"], 4) if m else "–"),
    (
        "Boundary mean (mm)",
        lambda c, m: _number(m["summary"]["boundary_mean_mm"]["mean"], 4) if m else "–",
    ),
    (
        "Boundary max (mm)",
        lambda c, m: _number(m["summary"]["boundary_max_mm"]["max"], 4) if m else "–",
    ),
    (
        "Volume vs reference (%)",
        lambda c, m: _number(m["volume"]["error_vs_reference_pct"]) if m else "–",
    ),
    ("Height error (mm)", lambda c, m: _number(m["height"]["error_mm"]) if m else "–"),
    (
        "Edge coverage MAE",
        lambda c, m: _number(m["summary"]["edge_coverage_mae"]["mean"]) if m else "–",
    ),
    (
        "Z phase (bodies)",
        lambda c, m: (
            ", ".join(
                f"{b['name']} {_number(b['z_phase']['phase'])}"
                for b in m["bodies"]
                if b["z_phase"]["phase"] is not None
            )
            or "–"
            if m
            else "–"
        ),
    ),
    (
        "UVTools issues",
        lambda c, m: (
            str(c["analysis"]["issues"]["count"])
            if c.get("analysis", {}).get("issues")
            else "unreadable"
            if c.get("analysis", {}).get("status") == "analysed"
            else "–"
        ),
    ),
)


def side_by_side(cases: Sequence[dict[str, Any]], metrics: dict[int, dict[str, Any]]) -> list[str]:
    """For every case measured with more than one slicer, one column per slicer."""
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
        rows = [
            [label, *(cell(case, metrics.get(id(case))) for case in group)]
            for label, cell in SIDE_BY_SIDE
        ]
        lines += _table(["Metric", *(slicer_label(case) for case in group)], rows)
        lines.append("")
    return lines


def write_report(run_dir: Path, others: Sequence[Path] = ()) -> Path:
    """Write ``report.md`` in ``run_dir`` (with ``others`` side by side when given)."""
    path = run_dir / "report.md" if not others else run_dir / "comparison.md"
    path.write_text(render([run_dir, *others]), encoding="utf-8")
    return path
