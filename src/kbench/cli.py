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
from kbench.env import capture_environment
from kbench.geometry import GeometryError
from kbench.models import CatalogError, build_catalog, default_catalog_path, load_catalog
from kbench.provenance import suite_root, utc_timestamp
from kbench.tools import GIT, TOOLS, inventory, resolve

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
    tools = inventory(os.environ)
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
