"""The host environment recorded with every run.

The record holds what can change a measurement (processor, memory, operating system,
virtualisation, load) and nothing that identifies a person: no host name and no user name.
Values that cannot be read on the current platform are ``None``, never guessed.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kbench.provenance import suite_state, utc_timestamp

SCHEMA_VERSION = 1

_PROC_CPUINFO = Path("/proc/cpuinfo")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_OSRELEASE = Path("/proc/sys/kernel/osrelease")
_SCALING_GOVERNOR = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")


def parse_cpuinfo(text: str) -> dict[str, Any]:
    """Processor facts from the text of Linux ``/proc/cpuinfo``.

    ``physical_cores`` counts distinct (``physical id``, ``core id``) pairs and is ``None``
    when the file does not list them. ``hypervisor_flag`` is the processor's ``hypervisor``
    feature flag, which is set when the system runs under a hypervisor (WSL 2 included).
    """
    model: str | None = None
    logical = 0
    cores: set[tuple[str, str]] = set()
    flags: set[str] | None = None
    physical_id: str | None = None
    core_id: str | None = None

    def close_block() -> None:
        if physical_id is not None and core_id is not None:
            cores.add((physical_id, core_id))

    for line in text.splitlines():
        if not line.strip():
            close_block()
            physical_id = core_id = None
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "processor":
            logical += 1
        elif key == "model name" and model is None:
            model = value
        elif key == "physical id":
            physical_id = value
        elif key == "core id":
            core_id = value
        elif key == "flags" and flags is None:
            flags = set(value.split())
    close_block()

    return {
        "model": model,
        "logical_cpus": logical or None,
        "physical_cores": len(cores) or None,
        "hypervisor_flag": None if flags is None else "hypervisor" in flags,
    }


def parse_meminfo(text: str) -> dict[str, int | None]:
    """Memory totals in KiB from the text of Linux ``/proc/meminfo``."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields and fields[0].isdigit():
            values[key.strip()] = int(fields[0])
    return {
        "total_kib": values.get("MemTotal"),
        "available_kib": values.get("MemAvailable"),
        "swap_total_kib": values.get("SwapTotal"),
        "swap_free_kib": values.get("SwapFree"),
    }


def detect_wsl(kernel_osrelease: str | None, environ: Mapping[str, str]) -> bool | None:
    """Whether Linux runs under Windows Subsystem for Linux.

    WSL kernels name Microsoft in their release string, and WSL sets ``WSL_DISTRO_NAME``.
    Returns ``None`` when neither source is available (not Linux).
    """
    if "WSL_DISTRO_NAME" in environ:
        return True
    if kernel_osrelease is None:
        return None
    return "microsoft" in kernel_osrelease.lower()


def capture_environment(
    root: Path | None,
    git: Path | None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The environment record (``kind: environment``) described in ``docs/METHODOLOGY.md``."""
    environ = os.environ if environ is None else environ
    cpuinfo = parse_cpuinfo(_read_text(_PROC_CPUINFO) or "")
    meminfo_text = _read_text(_PROC_MEMINFO)
    osrelease = _read_text(_PROC_OSRELEASE)
    governor = _read_text(_SCALING_GOVERNOR)

    try:
        usable_cpus: int | None = len(os.sched_getaffinity(0))
    except AttributeError:  # Not available on every platform.
        usable_cpus = None
    try:
        load = os.getloadavg()
        load_average: dict[str, float] | None = {
            "1min": load[0],
            "5min": load[1],
            "15min": load[2],
        }
    except (AttributeError, OSError):
        load_average = None

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "environment",
        "captured_at_utc": utc_timestamp(),
        "suite": suite_state(root, git),
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "os": {
            "system": platform.system() or None,
            "release": platform.release() or None,
            "machine": platform.machine() or None,
            "distribution": _distribution(),
            "wsl": detect_wsl(osrelease, environ),
        },
        "cpu": {
            "model": cpuinfo["model"] or platform.processor() or None,
            "logical_cpus": cpuinfo["logical_cpus"] or os.cpu_count(),
            "usable_cpus": usable_cpus,
            "physical_cores": cpuinfo["physical_cores"],
            "hypervisor_flag": cpuinfo["hypervisor_flag"],
            "scaling_governor": governor.strip() if governor else None,
        },
        "memory": parse_meminfo(meminfo_text) if meminfo_text is not None else None,
        "load_average": load_average,
    }


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _distribution() -> str | None:
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return None
    return release.get("PRETTY_NAME") or release.get("NAME")
