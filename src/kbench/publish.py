"""Curated summaries of runs for publication under ``results/`` (BD-026).

A summary holds the measurements and their conditions and nothing else: tool versions and
hashes, the suite's commit, the host's hardware and operating system, per-case performance and
accuracy summaries, file conformity and UVTools findings. It holds no local path, host name or
user name, no per-layer arrays, and no third-party file: exported print files are named by their
SHA-256 only. Publication is refused if any absolute path is left in the output.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kbench.report import _load, render, slicer_label

PUBLISH_SCHEMA_VERSION = 1

# Absolute paths in the forms this suite meets: POSIX roots and Windows drives or WSL shares.
_ABSOLUTE_PATH = re.compile(
    r"(?:(?<![\w.])/(?:home|root|develop|tmp|mnt|opt|usr|var|srv|media|Users)/[^\s'\"`)\],]*"
    r"|\b[A-Za-z]:\\[^\s'\"`)\],]*|\\\\wsl[^\s'\"`)\],]*)"
)

PROPERTY_FIELDS = (
    "ResolutionX",
    "ResolutionY",
    "PixelWidth",
    "PixelHeight",
    "LayerHeight",
    "LayerCount",
    "BottomLayerCount",
    "ExposureTime",
    "BottomExposureTime",
    "AntiAliasing",
    "DisplayMirror",
    "MachineName",
)


class PublishError(ValueError):
    """The summary would publish something it must not."""


def scrub(text: str) -> str:
    """``text`` with every absolute path replaced by its last component."""

    def last(match: re.Match[str]) -> str:
        path = match.group(0).rstrip("/\\")
        return re.split(r"[/\\]", path)[-1] or "<path>"

    return _ABSOLUTE_PATH.sub(last, text)


def _check(text: str, where: str) -> None:
    found = _ABSOLUTE_PATH.search(text)
    if found:
        raise PublishError(f"{where} still holds a local path: {found.group(0)!r}")


def _host(environment: Mapping[str, Any]) -> dict[str, Any]:
    cpu, os_info, memory = environment["cpu"], environment["os"], environment["memory"] or {}
    return {
        "cpu_model": cpu["model"],
        "physical_cores": cpu["physical_cores"],
        "logical_cpus": cpu["logical_cpus"],
        "hypervisor_flag": cpu["hypervisor_flag"],
        "memory_total_kib": memory.get("total_kib"),
        "os_distribution": os_info["distribution"],
        "kernel_release": os_info["release"],
        "machine": os_info["machine"],
        "wsl": os_info["wsl"],
        "python": environment["python"]["version"],
    }


def _performance(case: Mapping[str, Any]) -> dict[str, Any] | None:
    perf = case.get("performance")
    if not perf:
        return None
    fields = ("wall_s", "user_s", "system_s", "peak_rss_kib", "output_bytes")
    return {
        "timed_runs": perf["timed_runs"],
        "failed_runs": perf["failed_runs"],
        **{field: perf[field] for field in fields},
    }


def _accuracy(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": metrics["schema_version"],
        "layer_count": metrics["layer_count"],
        "orientation": {
            key: metrics["orientation"][key] for key in ("stored", "ambiguous", "margin", "iou")
        },
        "placement_offset_mm": metrics["placement"]["offset_mm"],
        "volume": metrics["volume"],
        "height": metrics["height"],
        "layers": metrics["summary"],
        "bodies": [
            {
                "name": body["name"],
                "volume_error_pct": body["volume_error_pct"],
                "z_phase": {
                    key: body["z_phase"].get(key)
                    for key in ("phase", "outline_offset_mm", "outline_offset_basis", "reason")
                },
            }
            for body in metrics["bodies"]
        ],
        "features": metrics.get("features", []),
        "features_smallest_resolved": metrics.get("features_smallest_resolved", {}),
    }


def case_summary(case: Mapping[str, Any], directory: Path) -> dict[str, Any]:
    """The publishable record of one case of one run."""
    analysis = case.get("analysis") or {}
    summary: dict[str, Any] = {
        "case": case["case"],
        "slicer": case["slicer"],
        "slicer_label": slicer_label(dict(case)),
        "target": case["target"],
        "cpus": len(case["cpus"]) if case.get("cpus") else None,
        "model": {
            key: case["model"][key] for key in ("id", "sha256", "triangle_count", "volume_mm3")
        },
        "slicer_commit": (case.get("slicer_build") or {}).get("commit"),
        "performance": _performance(case),
        "determinism": None,
        "file": None,
        "accuracy": None,
        "analysis_status": analysis.get("status"),
        "analysis_error": scrub(analysis["error"]) if analysis.get("error") else None,
    }
    manual = case.get("manual")
    if manual:
        summary["manual_export"] = {
            key: manual[key]
            for key in (
                "slicer",
                "slicer_version",
                "source_name",
                "sha256",
                "bytes",
                "stl_sha256",
                "imported_at_utc",
            )
        } | {"note": scrub(manual.get("note") or "")}
    if case.get("determinism"):
        decoded = analysis.get("decoded_layers")
        summary["determinism"] = {
            "outputs": case["determinism"]["outputs"],
            "distinct_files": len(case["determinism"]["distinct_sha256"]),
            "distinct_decoded_layers": decoded["distinct"] if decoded else None,
            "decoded_files": decoded["files"] if decoded else None,
        }
    if analysis.get("status") == "analysed":
        properties = analysis.get("properties") or {}
        summary["file"] = {
            "declared": {key: properties.get(key) for key in PROPERTY_FIELDS},
            "properties_source": analysis.get("properties_source"),
            "decoder": analysis.get("decoder"),
            "conformity": {key: check["matches"] for key, check in analysis["conformity"].items()},
            "uvtools_issues": analysis["issues"]["by_type"]
            if analysis.get("issues")
            else "unreadable",
        }
        summary["accuracy"] = _accuracy(_load(directory / "metrics.json"))
    return summary


def run_summary(run_dir: Path) -> dict[str, Any]:
    """The publishable record of one run."""
    run = _load(run_dir / "run.json")
    cases = []
    for entry in run["cases"]:
        record_path = run_dir / entry["record"]
        cases.append(case_summary(_load(record_path), record_path.parent))
    environment = run["environment_before"]
    suite_code = environment["suite"]
    return {
        "run_id": run["run_id"],
        "started_at_utc": run["started_at_utc"],
        "ended_at_utc": run["ended_at_utc"],
        "suite": run["suite"],
        "suite_code": {
            key: suite_code[key]
            for key in ("version", "git_commit", "git_dirty", "lockfile_sha256")
        },
        "host": _host(environment),
        "launcher_floor_kib": (run.get("launcher_floor_kib") or {}).get("median"),
        "tools": [
            {"name": tool["name"], "version": tool["version"], "sha256": tool["sha256"]}
            for tool in run["tools"]
            if tool["ok"]
        ],
        "targets": run["targets"],
        "models": run["models"],
        "cases": cases,
    }


def publish(run_dirs: Sequence[Path], out_dir: Path, name: str, title: str) -> tuple[Path, Path]:
    """Write ``<name>.md`` (the report's tables) and ``<name>.json`` (the records) into
    ``out_dir``; refuse runs made from uncommitted suite code and any leftover local path."""
    runs = [run_summary(run_dir) for run_dir in run_dirs]
    unclean = [run["run_id"] for run in runs if run["suite_code"]["git_dirty"] is not False]
    if unclean:
        raise PublishError(f"runs made from uncommitted or unknown suite code: {unclean}")
    document = {
        "schema_version": PUBLISH_SCHEMA_VERSION,
        "kind": "published_summary",
        "title": title,
        "runs": runs,
    }
    text_json = json.dumps(document, indent=2, sort_keys=True) + "\n"
    _check(text_json, f"{name}.json")

    commits = sorted({run["suite_code"]["git_commit"][:7] for run in runs})
    report = scrub(render(list(run_dirs)))
    body = report.split("\n", 1)[1] if report.startswith("# ") else report
    text_md = (
        f"# {title}\n\n"
        f"Generated by `kbench publish` from {len(runs)} run(s) of karasu-slicer-benchmark at "
        f"commit(s) {', '.join(f'`{commit}`' for commit in commits)}. The data are in "
        f"[{name}.json]({name}.json); metric definitions in "
        "[docs/METRICS.md](../../docs/METRICS.md). Values hold for the host, tools and versions "
        "stated below and nowhere else.\n" + body
    )
    _check(text_md, f"{name}.md")

    out_dir.mkdir(parents=True, exist_ok=True)
    md_path, json_path = out_dir / f"{name}.md", out_dir / f"{name}.json"
    md_path.write_text(text_md, encoding="utf-8")
    json_path.write_text(text_json, encoding="utf-8")
    return md_path, json_path
