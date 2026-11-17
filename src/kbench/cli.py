"""The ``kbench`` command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kbench import __version__
from kbench.config import ConfigError, load_suite, load_targets, repository_path
from kbench.env import capture_environment
from kbench.geometry import GeometryError
from kbench.install import InstallError, default_pins_path, install, load_pins
from kbench.karasu_build import BuildError, build_karasu
from kbench.models import CatalogError, build_catalog, default_catalog_path, load_catalog
from kbench.provenance import suite_root, utc_timestamp, work_root
from kbench.report import write_report
from kbench.run import RunError, run_suite
from kbench.tools import CARGO, GIT, TOOLS, inventory, resolve

TOOL_INVENTORY_SCHEMA_VERSION = 1

EXIT_OK = 0
EXIT_NOT_READY = 1
EXIT_FAILURE = 1
EXIT_USAGE = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``kbench`` with ``argv`` (default: the process arguments) and return the exit status."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.handler is None:
        getattr(args, "parser", parser).print_help(sys.stderr)
        return EXIT_USAGE
    status: int = args.handler(args)
    return status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kbench",
        description="Independent benchmark suite for karasu-slicer and other resin slicers.",
    )
    parser.add_argument("--version", action="version", version=f"kbench {__version__}")
    parser.set_defaults(handler=None)
    commands = parser.add_subparsers(title="commands", metavar="COMMAND")

    env = commands.add_parser(
        "env",
        help="print the host environment record",
        description="Print the environment record that every run stores: suite version and "
        "commit, Python, operating system, WSL, processor, memory and load.",
    )
    env.add_argument("--json", action="store_true", help="print the record as JSON")
    env.set_defaults(handler=_run_env)

    tools_help = ", ".join(f"{spec.name} ({spec.env_var})" for spec in TOOLS)
    doctor = commands.add_parser(
        "doctor",
        help="check the external tools the suite needs",
        description="Find each external tool through its environment variable or PATH, hash "
        f"it and query its version: {tools_help}. Exits with status 1 when a required tool is "
        "not ready.",
    )
    doctor.add_argument("--json", action="store_true", help="print the record as JSON")
    doctor.set_defaults(handler=_run_doctor)

    models = commands.add_parser(
        "models",
        help="list or build the test models",
        description="List the test-model catalog, or build its models into STL files with a "
        "manifest of their exact properties.",
    )
    model_commands = models.add_subparsers(title="model commands", metavar="ACTION")
    models.set_defaults(handler=None, parser=models)
    model_list = model_commands.add_parser("list", help="list the catalog's models")
    model_list.add_argument(
        "--catalog", type=Path, help="catalog file (default: models/catalog.toml)"
    )
    model_list.set_defaults(handler=_run_models_list)
    model_build = model_commands.add_parser(
        "build",
        help="build models into STL files and manifest.json",
        description="Build the catalog's models (or only the given ids) into STL files and write "
        "manifest.json beside them.",
    )
    model_build.add_argument("ids", nargs="*", metavar="ID", help="model ids (default: all)")
    model_build.add_argument(
        "--catalog", type=Path, help="catalog file (default: models/catalog.toml)"
    )
    model_build.add_argument("--out", type=Path, help="output directory (default: work/models)")
    model_build.set_defaults(handler=_run_models_build)

    install_parser = commands.add_parser(
        "install",
        help="install a pinned external tool into work/tools",
        description="Download the tool pinned in tools/pins.toml, check its size and SHA-256, and "
        "extract it into work/tools/<name>/<version>/.",
    )
    install_parser.add_argument("name", help="the pin's name (uvtools)")
    install_parser.add_argument("--archive", type=Path, help="use this downloaded archive instead")
    install_parser.set_defaults(handler=_run_install)

    karasu = commands.add_parser("karasu", help="build karasu-cli from a git ref")
    karasu_commands = karasu.add_subparsers(title="karasu commands", metavar="ACTION")
    karasu.set_defaults(handler=None, parser=karasu)
    karasu_build = karasu_commands.add_parser(
        "build",
        help="build karasu-cli at a ref into work/karasu/<commit>",
        description="Export the ref of a karasu-slicer checkout with git archive (the checkout is "
        "only read) and build karasu-cli with Cargo's release profile and locked dependencies.",
    )
    karasu_build.add_argument("--repo", type=Path, required=True, help="karasu-slicer checkout")
    karasu_build.add_argument("--ref", default="HEAD", help="commit, branch or tag (default HEAD)")
    karasu_build.set_defaults(handler=_run_karasu_build)

    run = commands.add_parser(
        "run",
        help="run a suite",
        description="Slice every case of a suite, time it, decode the files with UVTools and "
        "measure them; everything goes to work/runs/<run-id>/ with a report.md.",
    )
    run.add_argument("--suite", required=True, help="suite name in suites/ or path to a suite file")
    run.add_argument("--case", action="append", default=[], help="run only this case (repeatable)")
    run.add_argument("--keep-layers", action="store_true", help="keep the decoded layer images")
    run.set_defaults(handler=_run_suite)

    report = commands.add_parser("report", help="write the Markdown report of a run")
    report.add_argument("run_dir", type=Path, help="the run directory (work/runs/<run-id>)")
    report.set_defaults(handler=_run_report)
    return parser


def _run_env(args: argparse.Namespace) -> int:
    git = resolve(GIT, os.environ)
    record = capture_environment(suite_root(), git.path if git.status == "found" else None)
    if args.json:
        _print_json(record)
    else:
        for key, value in _flatten(record):
            print(f"{key}: {_text(value)}")
    return EXIT_OK


def _run_doctor(args: argparse.Namespace) -> int:
    tools = inventory(os.environ, work_root())
    ready = all(tool["ok"] for tool in tools if tool["required"])
    if args.json:
        _print_json(
            {
                "schema_version": TOOL_INVENTORY_SCHEMA_VERSION,
                "kind": "tool_inventory",
                "captured_at_utc": utc_timestamp(),
                "tools": tools,
            }
        )
    else:
        _print_doctor_text(tools)
    return EXIT_OK if ready else EXIT_NOT_READY


def _run_models_list(args: argparse.Namespace) -> int:
    try:
        specs = load_catalog(args.catalog or default_catalog_path())
    except (OSError, CatalogError) as error:
        print(f"kbench: {error}", file=sys.stderr)
        return EXIT_FAILURE
    width = max(len(spec.id) for spec in specs)
    for spec in specs:
        print(f"{spec.id:<{width}}  {spec.description}")
    return EXIT_OK


def _run_models_build(args: argparse.Namespace) -> int:
    out = args.out
    if out is None:
        root = suite_root()
        if root is None:
            print("kbench: not run from a checkout; give --out", file=sys.stderr)
            return EXIT_USAGE
        out = root / "work" / "models"
    try:
        manifest = build_catalog(args.catalog or default_catalog_path(), out, args.ids)
    except (OSError, CatalogError, GeometryError) as error:
        print(f"kbench: {error}", file=sys.stderr)
        return EXIT_FAILURE
    for record in manifest["models"]:
        print(
            f"{record['id']}: {record['triangle_count']} triangles, {record['volume_mm3']:.3f} mm3"
        )
    print(f"Wrote {len(manifest['models'])} models and manifest.json to {out}")
    return EXIT_OK


def _work_or_fail() -> Path:
    work = work_root()
    if work is None:
        raise RunError("not run from a checkout; set KBENCH_WORK")
    return work


def _run_install(args: argparse.Namespace) -> int:
    try:
        pins = load_pins(default_pins_path())
        if args.name not in pins:
            print(f"kbench: no pin named {args.name!r}; pins: {sorted(pins)}", file=sys.stderr)
            return EXIT_USAGE
        executable = install(pins[args.name], _work_or_fail(), archive=args.archive)
    except (InstallError, RunError, OSError) as error:
        print(f"kbench: {error}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"Installed {args.name} {pins[args.name].version}: {executable}")
    return EXIT_OK


def _run_karasu_build(args: argparse.Namespace) -> int:
    git, cargo = resolve(GIT, os.environ), resolve(CARGO, os.environ)
    if git.path is None or cargo.path is None or "found" not in (git.status, cargo.status):
        print("kbench: git and cargo are needed; see `kbench doctor`", file=sys.stderr)
        return EXIT_FAILURE
    try:
        record = build_karasu(args.repo.resolve(), args.ref, _work_or_fail(), git.path, cargo.path)
    except (BuildError, RunError, OSError) as error:
        print(f"kbench: {error}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"karasu-cli at {record['commit']}: {record['binary']}")
    print(f"Use it with: export KBENCH_KARASU_CLI={record['binary']}")
    return EXIT_OK


def _run_suite(args: argparse.Namespace) -> int:
    candidate = Path(args.suite)
    path = (
        candidate
        if candidate.suffix == ".toml"
        else repository_path("suites", f"{args.suite}.toml")
    )
    try:
        suite = load_suite(path)
        targets = load_targets(repository_path("targets"))
        run_dir = run_suite(
            suite,
            targets,
            default_catalog_path(),
            _work_or_fail(),
            os.environ,
            cases=args.case,
            keep_layers=args.keep_layers,
        )
        report = write_report(run_dir)
    except (ConfigError, RunError, CatalogError, OSError) as error:
        print(f"kbench: {error}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"Report: {report}")
    return EXIT_OK


def _run_report(args: argparse.Namespace) -> int:
    try:
        report = write_report(args.run_dir)
    except (OSError, KeyError, ValueError) as error:
        print(f"kbench: {error}", file=sys.stderr)
        return EXIT_FAILURE
    print(f"Report: {report}")
    return EXIT_OK


def _print_doctor_text(tools: list[dict[str, Any]]) -> None:
    name_width = max(len(tool["name"]) for tool in tools)
    indent = " " * (name_width + 2)
    for tool in tools:
        need = "required" if tool["required"] else "optional"
        if tool["ok"]:
            state = "ok"
        elif tool["status"] == "found":
            state = "NOT READY"
        else:
            state = tool["status"].upper()
        line = f"{tool['name']:<{name_width}}  {need:<8}  {state:<9}  {tool['version'] or ''}"
        print(line.rstrip())
        print(f"{indent}{tool['role']}")
        if tool["path"] is not None:
            print(f"{indent}{tool['path']} (from {tool['source']})")
        if tool["sha256"] is not None:
            print(f"{indent}sha256 {tool['sha256']}")
        if tool["error"] is not None:
            print(f"{indent}{tool['error']}")
            probe = tool["version_probe"]
            if probe is not None and probe["first_line"]:
                print(f"{indent}output: {probe['first_line']}")
    required = [tool for tool in tools if tool["required"]]
    ready = sum(1 for tool in required if tool["ok"])
    print(f"\nRequired tools ready: {ready} of {len(required)}.")


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        items: list[tuple[str, Any]] = []
        for key in value:
            items.extend(_flatten(value[key], f"{prefix}{key}."))
        return items
    return [(prefix.rstrip("."), value)]


def _text(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _print_json(record: dict[str, Any]) -> None:
    print(json.dumps(record, indent=2, sort_keys=True))
