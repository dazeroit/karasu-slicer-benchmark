from __future__ import annotations

import json

from kbench.env import SCHEMA_VERSION, capture_environment, detect_wsl, parse_cpuinfo, parse_meminfo
from kbench.provenance import suite_root

# Two physical cores with two hardware threads each, as Linux lists them.
CPUINFO_2C_4T = """\
processor\t: 0
model name\t: Example CPU 9000
physical id\t: 0
core id\t\t: 0
flags\t\t: fpu sse2 hypervisor avx2

processor\t: 1
model name\t: Example CPU 9000
physical id\t: 0
core id\t\t: 1
flags\t\t: fpu sse2 hypervisor avx2

processor\t: 2
model name\t: Example CPU 9000
physical id\t: 0
core id\t\t: 0
flags\t\t: fpu sse2 hypervisor avx2

processor\t: 3
model name\t: Example CPU 9000
physical id\t: 0
core id\t\t: 1
flags\t\t: fpu sse2 hypervisor avx2
"""

MEMINFO = """\
MemTotal:       16320232 kB
MemFree:         6000000 kB
MemAvailable:   13871087 kB
SwapTotal:       4194304 kB
SwapFree:        4194304 kB
HugePages_Total:       0
"""


def test_parse_cpuinfo_counts_threads_and_cores() -> None:
    assert parse_cpuinfo(CPUINFO_2C_4T) == {
        "model": "Example CPU 9000",
        "logical_cpus": 4,
        "physical_cores": 2,
        "hypervisor_flag": True,
    }


def test_parse_cpuinfo_without_topology_or_hypervisor() -> None:
    text = (
        "processor : 0\nmodel name : Bare\nflags : fpu sse2\n\nprocessor : 1\nmodel name : Bare\n"
    )
    assert parse_cpuinfo(text) == {
        "model": "Bare",
        "logical_cpus": 2,
        "physical_cores": None,
        "hypervisor_flag": False,
    }


def test_parse_cpuinfo_of_nothing() -> None:
    assert parse_cpuinfo("") == {
        "model": None,
        "logical_cpus": None,
        "physical_cores": None,
        "hypervisor_flag": None,
    }


def test_parse_meminfo() -> None:
    assert parse_meminfo(MEMINFO) == {
        "total_kib": 16320232,
        "available_kib": 13871087,
        "swap_total_kib": 4194304,
        "swap_free_kib": 4194304,
    }


def test_detect_wsl() -> None:
    assert detect_wsl("6.6.87.2-microsoft-standard-WSL2", {}) is True
    assert detect_wsl("6.8.0-48-generic", {}) is False
    assert detect_wsl("6.8.0-48-generic", {"WSL_DISTRO_NAME": "Ubuntu"}) is True
    assert detect_wsl(None, {}) is None


def test_environment_record_contract() -> None:
    record = capture_environment(suite_root(), git=None, environ={})
    assert record["schema_version"] == SCHEMA_VERSION
    assert record["kind"] == "environment"
    # The fixed set of sections; nothing identifying a person (host or user name) is recorded.
    assert set(record) == {
        "schema_version",
        "kind",
        "captured_at_utc",
        "suite",
        "python",
        "os",
        "cpu",
        "memory",
        "load_average",
    }
    assert set(record["cpu"]) == {
        "model",
        "logical_cpus",
        "usable_cpus",
        "physical_cores",
        "hypervisor_flag",
        "scaling_governor",
    }
    json.dumps(record)  # Serialisable as it is.
