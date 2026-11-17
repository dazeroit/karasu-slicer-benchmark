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
from kbench.models import BuiltModel, build_catalog, build_model, load_catalog
from kbench.provenance import sha256_file, suite_root, utc_timestamp
from kbench.reference import Layer, uniform_schedule
from kbench.sl1 import SL1_SUFFIXES, SL1Error, layers_digest, read_sl1
from kbench.slicers import ADAPTERS, Adapter
from kbench.tools import inventory
from kbench.uvtools import GLOBAL_NUMBERS, GLOBAL_TEXTS, UVTools, UVToolsError

RUN_SCHEMA_VERSION = 1
CASE_SCHEMA_VERSION = 1

# Files kept besides the print file when runs write different bytes.
MAX_DISTINCT_FILES = 2

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
    slicers = sorted({slicer for case in selected for slicer in case.slicers})
    needed = {ADAPTERS[slicer].tool for slicer in slicers}
    if any(case.analyze for case in selected):
        needed.add("UVtoolsCmd")
    missing = sorted(name for name in needed if not by_name[name]["ok"])
    if missing:
        raise RunError(f"tools not ready: {missing}; run `kbench doctor`")
    executables = {slicer: Path(by_name[ADAPTERS[slicer].tool]["path"]) for slicer in slicers}

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
                ADAPTERS[slicer],
                executables[slicer],
                run_dir / "models" / records[case.model]["stl"],
                directory,
            )
            record["model"] = records[case.model]
            record["slicer_tool"] = by_name[ADAPTERS[slicer].tool]
            record["slicer_build"] = (
                build_record_for(executables[slicer]) if slicer == "karasu" else None
            )
            case_records.append(record)

    uvtools = Path(by_name["UVtoolsCmd"]["path"]) if by_name["UVtoolsCmd"]["ok"] else None
    for record, case in _with_cases(case_records, selected):
        directory = Path(record["directory"])
        if case.analyze and uvtools is not None:
            progress(f"  analysing {case.id} with {record['slicer']}")
            record["analysis"] = analyze_case(
                record,
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
        unsupported = sorted(set(case.slicers) - set(ADAPTERS))
        if unsupported:
            raise RunError(f"case {case.id!r}: slicers {unsupported} have no adapter yet")


def _time_case(
    suite: Suite,
    case: Case,
    target: Target,
    adapter: Adapter,
    executable: Path,
    model: Path,
    directory: Path,
) -> dict[str, Any]:
    timing = suite.timing
    cpus = _case_cpus(case)
    attempts: list[dict[str, Any]] = []
    print_file: Path | None = None
    # Up to MAX_DISTINCT_FILES more files whose bytes differ from the print file's, kept so the
    # analysis can tell metadata differences from layer differences.
    distinct: dict[str, Path] = {}
    total = timing.warmup + timing.repetitions
    for attempt in range(total):
        warmup = attempt < timing.warmup
        stem = directory / f"attempt-{attempt:02d}"
        log = directory / "slicer-phases.log" if attempt == 0 and warmup else None
        job = adapter.job(executable, model, target, stem, log=log)
        load = _host_load()
        run = run_timed(
            job.argv,
            timing.timeout_s,
            stem.with_suffix(".stdout"),
            stem.with_suffix(".stderr"),
            cpus=cpus,
        )
        entry = {"attempt": attempt, "warmup": warmup, "host_before": load, **run.to_record()}
        entry["succeeded"] = run.exit_status == 0 and not run.timed_out and job.output.is_file()
        if job.output.is_file():
            entry["output_bytes"] = job.output.stat().st_size
            entry["output_sha256"] = sha256_file(job.output)
            entry["layers_sha256"] = layers_digest(job.output)
            sha = entry["output_sha256"]
            if print_file is None and entry["succeeded"] and not warmup:
                print_file = directory / f"print{job.output.suffix}"
                job.output.rename(print_file)
                distinct[sha] = print_file
            elif (
                entry["succeeded"]
                and sha not in distinct
                and sum(path != print_file for path in distinct.values()) < MAX_DISTINCT_FILES
            ):
                kept = directory / f"distinct-{attempt:02d}{job.output.suffix}"
                job.output.rename(kept)
                distinct[sha] = kept
            else:
                job.output.unlink()
        attempts.append(entry)

    timed = [entry for entry in attempts if not entry["warmup"]]
    good = [entry for entry in timed if entry["succeeded"]]
    hashes = sorted({entry["output_sha256"] for entry in attempts if entry.get("output_sha256")})
    layer_hashes = sorted({e["layers_sha256"] for e in attempts if e.get("layers_sha256")})
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "kind": "case",
        "case": case.id,
        "slicer": adapter.name,
        "target": target.id,
        "cpus": cpus,
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
            # SL1 family only: identical layers despite differing metadata.
            "distinct_layers_sha256": layer_hashes or None,
        },
        "print_file": str(print_file) if print_file is not None else None,
        "distinct_files": [str(path) for path in distinct.values() if path != print_file],
    }


def _case_cpus(case: Case) -> list[int] | None:
    """The CPUs a case's slicer may use: the first ``case.cpus`` of the suite's own, or all."""
    if case.cpus is None:
        return None
    available = sorted(os.sched_getaffinity(0))
    if case.cpus > len(available):
        raise RunError(f"case {case.id!r} asks for {case.cpus} CPUs; {len(available)} are usable")
    return available[: case.cpus]


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
    """What the file declares against what the target and the model call for.

    ``matches`` is ``None`` where the file declares nothing to check (a property no reader
    found): unknown is never reported as a mismatch.
    """
    panel = target.panel
    resolution = (properties.get("ResolutionX"), properties.get("ResolutionY"))
    pitch = (properties.get("PixelWidth"), properties.get("PixelHeight"))
    expected_layers = len(uniform_schedule(model_height_mm, target.layer_height_mm))
    expected_resolution = (panel.resolution_x, panel.resolution_y)
    expected_pitch = (panel.pitch_x_mm, panel.pitch_y_mm)

    def pitch_matches(order: tuple[float, float]) -> bool | None:
        if None in pitch:
            return None
        return all(abs(a - b) <= PITCH_TOLERANCE_MM for a, b in zip(pitch, order, strict=True))

    # A portrait format declares the panel with its sides exchanged: the same panel.
    transposed = resolution == expected_resolution[::-1] and resolution != expected_resolution
    checks = {
        "resolution": {
            "declared": list(resolution),
            "expected": list(expected_resolution),
            "transposed": transposed,
            "matches": None
            if None in resolution
            else resolution == expected_resolution or transposed,
        },
        "pixel_pitch_mm": {
            "declared": list(pitch),
            "expected": list(expected_pitch),
            "matches": pitch_matches(expected_pitch[::-1] if transposed else expected_pitch),
        },
        "layer_height_mm": {
            "declared": properties.get("LayerHeight"),
            "expected": target.layer_height_mm,
            "matches": None
            if properties.get("LayerHeight") is None
            else abs(properties["LayerHeight"] - target.layer_height_mm)
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


def analyze_case(
    record: dict[str, Any], target: Target, model: BuiltModel, uvtools: UVTools, keep_layers: bool
) -> dict[str, Any]:
    """Decode the case's print file, check it and measure it (``metrics.json``).

    UVTools reads every file's properties and issues; its failures are recorded, not hidden.
    Layers are decoded by UVTools, except SL1 and SL1S archives, which the suite reads itself
    for every slicer (BD-018).
    """
    directory = Path(record["directory"])
    if record["print_file"] is None:
        return {"status": "skipped", "reason": "no successful print file"}
    print_file = Path(record["print_file"])
    analysis: dict[str, Any] = {"status": "failed"}
    layers_dir = directory / "layers"
    try:
        started = time.perf_counter()
        properties: dict[str, Any] | None
        try:
            properties_text, properties = uvtools.properties(print_file)
            (directory / "uvtools-properties.txt").write_text(properties_text, encoding="utf-8")
            analysis["properties_source"] = "uvtools"
        except UVToolsError as error:
            properties = None
            analysis["uvtools_properties_error"] = str(error)[:2000]

        if print_file.suffix.lower() in SL1_SUFFIXES:
            files, config, layers = read_sl1(print_file, layers_dir)
            analysis["decoder"] = "kbench-sl1"
            analysis["sl1_config"] = config
            if properties is None:
                properties = _sl1_properties(config, files[0], len(files))
                analysis["properties_source"] = "config.ini and layer images"
        else:
            if properties is None:
                raise UVToolsError(analysis["uvtools_properties_error"])
            files = uvtools.extract_layers(print_file, layers_dir)
            layer_text, layer_properties = uvtools.layer_properties(print_file, len(files))
            (directory / "uvtools-layers.txt").write_text(layer_text, encoding="utf-8")
            layers = schedule_from_layers(layer_properties)
            analysis["decoder"] = "uvtools"

        try:
            issues_text, issues = uvtools.issues(print_file)
            (directory / "uvtools-issues.txt").write_text(issues_text, encoding="utf-8")
            analysis["issues"] = issues
        except UVToolsError as error:
            analysis["issues"] = None
            analysis["uvtools_issues_error"] = str(error)[:2000]
        analysis["decode_wall_s"] = time.perf_counter() - started
        analysis["properties"] = properties
        analysis["conformity"] = conformity(
            properties, target, layers, float(model.mesh.vertices[:, 2].max())
        )
        started = time.perf_counter()
        metrics = analyze_stack(model, target.panel, PngStack.open(files, layers))
        analysis["metrics_wall_s"] = time.perf_counter() - started
        _write_json(directory / "metrics.json", metrics)
        analysis["metrics"] = "metrics.json"
        analysis["decoded_layers"] = _decoded_determinism(record, files, uvtools, directory)
        analysis["status"] = "analysed"
    except (UVToolsError, AnalysisError, SL1Error, OSError) as error:
        analysis["error"] = f"{type(error).__name__}: {error}"[:2000]
    if not keep_layers and layers_dir.exists():
        shutil.rmtree(layers_dir)
    return analysis


def _pixel_digest(files: Sequence[Path]) -> str:
    """SHA-256 over the decoded pixels (and sizes) of layer images, in layer order."""
    import hashlib

    import numpy as np
    from PIL import Image

    digest = hashlib.sha256()
    for file in files:
        with Image.open(file) as image:
            pixels = np.asarray(image)
        digest.update(f"{pixels.shape}{pixels.dtype}".encode())
        digest.update(pixels.tobytes())
    return digest.hexdigest()


def _decode(print_file: Path, uvtools: UVTools, out_dir: Path) -> list[Path]:
    if print_file.suffix.lower() in SL1_SUFFIXES:
        return read_sl1(print_file, out_dir)[0]
    return uvtools.extract_layers(print_file, out_dir)


def _decoded_determinism(
    record: Mapping[str, Any], files: Sequence[Path], uvtools: UVTools, directory: Path
) -> dict[str, Any]:
    """Whether files with different bytes hold different layers: each kept file is decoded the
    same way as the analysed one and its pixels compared."""
    digests = [_pixel_digest(files)]
    for index, other in enumerate(record.get("distinct_files", [])):
        out_dir = directory / f"distinct-layers-{index}"
        try:
            digests.append(_pixel_digest(_decode(Path(other), uvtools, out_dir)))
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    return {"files": len(digests), "distinct": len(set(digests)), "digests": digests}


def _sl1_properties(config: Mapping[str, str], first_layer: Path, count: int) -> dict[str, Any]:
    """The properties an SL1 archive itself declares, where UVTools cannot read it."""
    from PIL import Image

    with Image.open(first_layer) as image:
        width, height = image.width, image.height
    properties: dict[str, Any] = dict.fromkeys(GLOBAL_NUMBERS)
    properties.update(dict.fromkeys(GLOBAL_TEXTS))
    properties.update(
        {
            "ResolutionX": float(width),
            "ResolutionY": float(height),
            "LayerHeight": float(config["layerHeight"]),
            "LayerCount": float(count),
            "ExposureTime": float(config["expTime"]) if "expTime" in config else None,
            "BottomExposureTime": float(config["expTimeFirst"])
            if "expTimeFirst" in config
            else None,
            "MachineName": config.get("printerModel"),
        }
    )
    return properties


def import_print_file(
    print_file: Path,
    *,
    slicer: str,
    slicer_version: str,
    target: Target,
    model_id: str,
    stl: Path,
    catalog_path: Path,
    work: Path,
    environ: Mapping[str, str],
    note: str = "",
    keep_layers: bool = False,
    progress: Callable[[str], None] = print,
) -> Path:
    """Analyse a print file exported by hand from a slicer without a command line.

    ``stl`` is the model file the operator sliced; it must be byte-identical to the model this
    version of the suite generates, or the reference would not be the geometry that was sliced.
    The run has no timing: a manual export carries no performance claim.
    """
    tools = inventory(environ, work)
    uvtools = next(tool for tool in tools if tool["name"] == "UVtoolsCmd")
    if not uvtools["ok"]:
        raise RunError("UVtoolsCmd is not ready; run `kbench doctor`")
    specs = {spec.id: spec for spec in load_catalog(catalog_path)}
    if model_id not in specs:
        raise RunError(f"unknown model {model_id!r}")
    if not print_file.is_file():
        raise RunError(f"no such print file: {print_file}")

    started = utc_timestamp()
    run_id = f"{started.replace('-', '').replace(':', '')}-import-{slicer}"
    run_dir = work / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    progress(f"Run {run_id}")
    manifest = build_catalog(catalog_path, run_dir / "models", [model_id])
    model_record = manifest["models"][0]
    stl_sha256 = sha256_file(stl)
    if stl_sha256 != model_record["sha256"]:
        shutil.rmtree(run_dir)
        raise RunError(
            f"{stl.name} is not the model this suite generates for {model_id!r} "
            f"(SHA-256 {stl_sha256[:16]}…, expected {model_record['sha256'][:16]}…); "
            "slice the file `kbench models build` writes"
        )

    case_id = f"{model_id}@{target.id}"
    directory = run_dir / "cases" / case_id / slicer
    directory.mkdir(parents=True)
    copy = directory / f"print{print_file.suffix}"
    shutil.copyfile(print_file, copy)
    record: dict[str, Any] = {
        "schema_version": CASE_SCHEMA_VERSION,
        "kind": "case",
        "case": case_id,
        "slicer": slicer,
        "target": target.id,
        "directory": str(directory),
        "manual": {
            "slicer": slicer,
            "slicer_version": slicer_version,
            "source_name": print_file.name,
            "sha256": sha256_file(copy),
            "bytes": copy.stat().st_size,
            "imported_at_utc": started,
            "stl_sha256": stl_sha256,
            "note": note,
        },
        "attempts": [],
        "performance": None,
        "determinism": None,
        "print_file": str(copy),
        "model": model_record,
        "slicer_tool": None,
        "slicer_build": None,
    }
    progress(f"  analysing {case_id} from {slicer} {slicer_version}")
    record["analysis"] = analyze_case(
        record,
        target,
        build_model(specs[model_id]),
        UVTools(Path(uvtools["path"])),
        keep_layers,
    )
    _write_json(directory / "case.json", record)

    git = next(tool for tool in tools if tool["name"] == "git")
    _write_json(
        run_dir / "run.json",
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "kind": "run",
            "run_id": run_id,
            "started_at_utc": started,
            "ended_at_utc": utc_timestamp(),
            "suite": {
                "id": "import",
                "description": f"Manual export from {slicer} {slicer_version}.",
                "sha256": None,
                "timing": None,
            },
            "targets": {
                target.id: {
                    "description": target.description,
                    "sha256": target.sha256,
                    "source": dict(target.source),
                }
            },
            "models": {
                "generator_version": manifest["generator_version"],
                "catalog_sha256": manifest["catalog_sha256"],
            },
            "tools": tools,
            "launcher_floor_kib": None,
            "environment_before": capture_environment(
                suite_root(), Path(git["path"]) if git["ok"] else None, environ
            ),
            "environment_after": None,
            "cases": [
                {
                    "case": case_id,
                    "slicer": slicer,
                    "record": str(directory.relative_to(run_dir) / "case.json"),
                }
            ],
        },
    )
    return run_dir
