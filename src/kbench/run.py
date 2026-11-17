"""Running a suite: slice every case, time it, decode the files with UVTools, measure them.

All timed runs of a suite happen first, serially; decoding and analysis (which load the host
heavily) come after, so they never overlap a measurement. Everything is written under
``work/runs/<run-id>/`` (docs/METHODOLOGY.md, Runs).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from kbench.config import Case, Suite, Target
from kbench.env import capture_environment, parse_meminfo
from kbench.execution import describe, launcher_floor, run_timed
from kbench.karasu_build import build_record_for
from kbench.metrics.stack import AnalysisError, PngStack, analyze_stack
from kbench.models import build_catalog, build_model, load_catalog
from kbench.provenance import sha256_file, suite_root, utc_timestamp
from kbench.reference import Layer, uniform_schedule
from kbench.slicers import karasu_job
from kbench.tools import inventory
from kbench.uvtools import UVTools, UVToolsError

RUN_SCHEMA_VERSION = 1
CASE_SCHEMA_VERSION = 1
SUPPORTED_SLICERS = ("karasu",)

# Declared pixel pitch and layer height are printed by UVTools with a few decimals; agreement
# within half a micrometre is agreement to the printed precision.
PITCH_TOLERANCE_MM = 0.0005
LAYER_HEIGHT_TOLERANCE_MM = 0.0005


class RunError(RuntimeError):
    """The suite cannot run (missing tools, unknown models or targets)."""


def _write_json(path: Path, record: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _host_load() -> dict[str, Any]:
    try:
        load_1min: float | None = os.getloadavg()[0]
    except (AttributeError, OSError):
        load_1min = None
    try:
        available = parse_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))[
            "available_kib"
        ]
    except OSError:
        available = None
    return {"load_1min": load_1min, "memory_available_kib": available}


def run_suite(
    suite: Suite,
    targets: Mapping[str, Target],
    catalog_path: Path,
    work: Path,
    environ: Mapping[str, str],
    *,
    cases: Sequence[str] = (),
    keep_layers: bool = False,
    progress: Callable[[str], None] = print,
) -> Path:
    """Run ``suite`` (or only the named ``cases``) and return the run directory."""
    selected = [case for case in suite.cases if not cases or case.id in cases]
    if cases and len(selected) != len(set(cases)):
        raise RunError(f"unknown cases: {sorted(set(cases) - {case.id for case in suite.cases})}")
    _check_cases(selected, targets, catalog_path)

    tools = inventory(environ, work)
    by_name = {tool["name"]: tool for tool in tools}
    needed = {"karasu-cli"} | ({"UVtoolsCmd"} if any(case.analyze for case in selected) else set())
    missing = sorted(name for name in needed if not by_name[name]["ok"])
    if missing:
        raise RunError(f"tools not ready: {missing}; run `kbench doctor`")
    karasu = Path(by_name["karasu-cli"]["path"])
    karasu_build = build_record_for(karasu)

    started = utc_timestamp()
    run_id = f"{started.replace('-', '').replace(':', '')}-{suite.id}"
    run_dir = work / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    progress(f"Run {run_id}")

    floor_dir = run_dir / "launcher-floor"
    floor_dir.mkdir()
    floor = launcher_floor(floor_dir)
    git = by_name["git"]
    environment_before = capture_environment(
        suite_root(), Path(git["path"]) if git["ok"] else None, environ
    )
    manifest = build_catalog(
        catalog_path, run_dir / "models", sorted({case.model for case in selected})
    )
    records = {record["id"]: record for record in manifest["models"]}
    specs = {spec.id: spec for spec in load_catalog(catalog_path)}

    case_records: list[dict[str, Any]] = []
    for case in selected:
        for slicer in case.slicers:
            directory = run_dir / "cases" / case.id / slicer
            directory.mkdir(parents=True)
            progress(f"  timing {case.id} with {slicer}")
            record = _time_case(
                suite,
                case,
                targets[case.target],
                slicer,
                karasu,
                run_dir / "models" / records[case.model]["stl"],
                directory,
            )
            record["model"] = records[case.model]
            record["slicer_build"] = karasu_build
            case_records.append(record)

    uvtools = Path(by_name["UVtoolsCmd"]["path"]) if by_name["UVtoolsCmd"]["ok"] else None
    for record, case in _with_cases(case_records, selected):
        directory = Path(record["directory"])
        if case.analyze and uvtools is not None:
            progress(f"  analysing {case.id} with {record['slicer']}")
            record["analysis"] = _analyze_case(
                record,
                case,
                targets[case.target],
                build_model(specs[case.model]),
                UVTools(uvtools, suite.timing.timeout_s),
                keep_layers,
            )
        _write_json(directory / "case.json", record)

    environment_after = capture_environment(
        suite_root(), Path(git["path"]) if git["ok"] else None, environ
    )
    run_record = {
        "schema_version": RUN_SCHEMA_VERSION,
        "kind": "run",
        "run_id": run_id,
        "started_at_utc": started,
        "ended_at_utc": utc_timestamp(),
        "suite": {
            "id": suite.id,
            "description": suite.description,
            "sha256": suite.sha256,
            "timing": vars(suite.timing),
        },
        "targets": {
            name: {
                "description": target.description,
                "sha256": target.sha256,
                "source": dict(target.source),
            }
            for name, target in targets.items()
            if name in {case.target for case in selected}
        },
        "models": {
            "generator_version": manifest["generator_version"],
            "catalog_sha256": manifest["catalog_sha256"],
        },
        "tools": tools,
        "launcher_floor_kib": floor,
        "environment_before": environment_before,
        "environment_after": environment_after,
        "cases": [
            {
                "case": record["case"],
                "slicer": record["slicer"],
                "record": str(Path(record["directory"]).relative_to(run_dir) / "case.json"),
            }
            for record in case_records
        ],
    }
    _write_json(run_dir / "run.json", run_record)
    return run_dir


def _with_cases(records: list[dict[str, Any]], cases: Sequence[Case]):
    by_id = {case.id: case for case in cases}
    for record in records:
        yield record, by_id[record["case"]]


def _check_cases(cases: Sequence[Case], targets: Mapping[str, Target], catalog_path: Path) -> None:
    model_ids = {spec.id for spec in load_catalog(catalog_path)}
    for case in cases:
        if case.model not in model_ids:
            raise RunError(f"case {case.id!r}: unknown model {case.model!r}")
        if case.target not in targets:
            raise RunError(f"case {case.id!r}: unknown target {case.target!r}")
        unsupported = sorted(set(case.slicers) - set(SUPPORTED_SLICERS))
        if unsupported:
            raise RunError(f"case {case.id!r}: slicers {unsupported} have no adapter yet")


def _time_case(
    suite: Suite,
    case: Case,
    target: Target,
    slicer: str,
    karasu: Path,
    model: Path,
    directory: Path,
) -> dict[str, Any]:
    timing = suite.timing
    attempts: list[dict[str, Any]] = []
    print_file: Path | None = None
    total = timing.warmup + timing.repetitions
    for attempt in range(total):
        warmup = attempt < timing.warmup
        stem = directory / f"attempt-{attempt:02d}"
        log = directory / "slicer-phases.log" if attempt == 0 and warmup else None
        job = karasu_job(karasu, model, target, stem, log=log)
        load = _host_load()
        run = run_timed(
            job.argv, timing.timeout_s, stem.with_suffix(".stdout"), stem.with_suffix(".stderr")
        )
        entry = {"attempt": attempt, "warmup": warmup, "host_before": load, **run.to_record()}
        entry["succeeded"] = run.exit_status == 0 and not run.timed_out and job.output.is_file()
        if job.output.is_file():
            entry["output_bytes"] = job.output.stat().st_size
            entry["output_sha256"] = sha256_file(job.output)
            if print_file is None and entry["succeeded"] and not warmup:
                print_file = directory / f"print{job.output.suffix}"
                job.output.rename(print_file)
            else:
                job.output.unlink()
        attempts.append(entry)

    timed = [entry for entry in attempts if not entry["warmup"]]
    good = [entry for entry in timed if entry["succeeded"]]
    hashes = sorted({entry["output_sha256"] for entry in attempts if entry.get("output_sha256")})
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "kind": "case",
        "case": case.id,
        "slicer": slicer,
        "target": target.id,
        "directory": str(directory),
        "attempts": attempts,
        "performance": {
            "timed_runs": len(timed),
            "failed_runs": len(timed) - len(good),
            "wall_s": describe([entry["wall_s"] for entry in good]),
            "user_s": describe([entry["user_s"] for entry in good]),
            "system_s": describe([entry["system_s"] for entry in good]),
            "peak_rss_kib": describe([entry["peak_rss_kib"] for entry in good]),
            "output_bytes": describe([entry["output_bytes"] for entry in good]),
        },
        "determinism": {
            "outputs": len([e for e in attempts if e.get("output_sha256")]),
            "distinct_sha256": hashes,
        },
        "print_file": str(print_file) if print_file is not None else None,
    }


def schedule_from_layers(layer_properties: Sequence[Mapping[str, Any]]) -> list[Layer]:
    """The layer slabs from UVTools' per-layer ``PositionZ`` (the top of each layer, in mm)."""
    layers: list[Layer] = []
    bottom = 0.0
    for index, entry in enumerate(layer_properties):
        top = entry.get("PositionZ")
        if top is None:
            raise AnalysisError(f"layer {index} declares no PositionZ")
        height = float(top) - bottom
        if height <= 0.0:
            raise AnalysisError(f"layer {index} does not rise above the previous one ({top} mm)")
        layers.append(Layer(index, bottom, height))
        bottom = float(top)
    return layers


def conformity(
    properties: Mapping[str, Any], target: Target, layers: Sequence[Layer], model_height_mm: float
) -> dict[str, Any]:
    """What the file declares against what the target and the model call for."""
    panel = target.panel
    resolution = (properties.get("ResolutionX"), properties.get("ResolutionY"))
    pitch = (properties.get("PixelWidth"), properties.get("PixelHeight"))
    expected_layers = len(uniform_schedule(model_height_mm, target.layer_height_mm))
    checks = {
        "resolution": {
            "declared": list(resolution),
            "expected": [panel.resolution_x, panel.resolution_y],
            "matches": resolution == (panel.resolution_x, panel.resolution_y),
        },
        "pixel_pitch_mm": {
            "declared": list(pitch),
            "expected": [panel.pitch_x_mm, panel.pitch_y_mm],
            "matches": None not in pitch
            and abs(pitch[0] - panel.pitch_x_mm) <= PITCH_TOLERANCE_MM
            and abs(pitch[1] - panel.pitch_y_mm) <= PITCH_TOLERANCE_MM,
        },
        "layer_height_mm": {
            "declared": properties.get("LayerHeight"),
            "expected": target.layer_height_mm,
            "matches": properties.get("LayerHeight") is not None
            and abs(properties["LayerHeight"] - target.layer_height_mm)
            <= LAYER_HEIGHT_TOLERANCE_MM,
        },
        "layer_count": {
            "declared": properties.get("LayerCount"),
            "decoded": len(layers),
            "expected": expected_layers,
            "matches": len(layers) == expected_layers,
        },
        "uniform_layers": {
            "matches": all(
                abs(layer.height_mm - target.layer_height_mm) <= LAYER_HEIGHT_TOLERANCE_MM
                for layer in layers
            ),
        },
    }
    return checks


def _analyze_case(
    record: dict[str, Any], case: Case, target: Target, model, uvtools: UVTools, keep_layers: bool
) -> dict[str, Any]:
    directory = Path(record["directory"])
    if record["print_file"] is None:
        return {"status": "skipped", "reason": "no successful print file"}
    print_file = Path(record["print_file"])
    analysis: dict[str, Any] = {"status": "failed"}
    try:
        started = time.perf_counter()
        properties_text, properties = uvtools.properties(print_file)
        (directory / "uvtools-properties.txt").write_text(properties_text, encoding="utf-8")
        layers_dir = directory / "layers"
        files = uvtools.extract_layers(print_file, layers_dir)
        layer_text, layer_properties = uvtools.layer_properties(print_file, len(files))
        (directory / "uvtools-layers.txt").write_text(layer_text, encoding="utf-8")
        issues_text, issues = uvtools.issues(print_file)
        (directory / "uvtools-issues.txt").write_text(issues_text, encoding="utf-8")
        analysis["uvtools_wall_s"] = time.perf_counter() - started
        analysis["properties"] = properties
        analysis["issues"] = issues

        layers = schedule_from_layers(layer_properties)
        analysis["conformity"] = conformity(
            properties, target, layers, float(model.mesh.vertices[:, 2].max())
        )
        started = time.perf_counter()
        metrics = analyze_stack(model, target.panel, PngStack.open(files, layers))
        analysis["metrics_wall_s"] = time.perf_counter() - started
        _write_json(directory / "metrics.json", metrics)
        analysis["metrics"] = "metrics.json"
        analysis["status"] = "analysed"
        if not keep_layers:
            shutil.rmtree(layers_dir)
    except (UVToolsError, AnalysisError, OSError) as error:
        analysis["error"] = f"{type(error).__name__}: {error}"
    return analysis
