from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from support import MakeScript, posix_only

from kbench.execution import describe, launcher_floor, run_timed


@posix_only
def test_measures_time_cpu_and_memory(tmp_path: Path) -> None:
    # Allocate and touch about 64 MiB, then spin for a moment.
    program = (
        "import time\n"
        "block = bytearray(64 * 1024 * 1024)\n"
        "for i in range(0, len(block), 4096): block[i] = 1\n"
        "end = time.process_time() + 0.2\n"
        "while time.process_time() < end: pass\n"
        "print('done')\n"
    )
    run = run_timed([sys.executable, "-c", program], 60, tmp_path / "out.txt", tmp_path / "err.txt")
    assert run.exit_status == 0
    assert not run.timed_out
    assert run.user_s + run.system_s >= 0.2
    assert run.wall_s >= run.user_s * 0.5
    assert run.peak_rss_kib >= 64 * 1024
    assert (tmp_path / "out.txt").read_text() == "done\n"


@posix_only
def test_records_failures_and_signals(make_script: MakeScript, tmp_path: Path) -> None:
    failing = make_script("fail", 'echo "bad input" >&2; exit 3')
    run = run_timed([str(failing)], 10, tmp_path / "o", tmp_path / "e")
    assert run.exit_status == 3
    assert (tmp_path / "e").read_text() == "bad input\n"
    killed = make_script("killed", "kill -9 $$")
    assert run_timed([str(killed)], 10, tmp_path / "o2", tmp_path / "e2").exit_status == -9


@posix_only
def test_kills_at_the_timeout(make_script: MakeScript, tmp_path: Path) -> None:
    hanging = make_script("hang", "sleep 30 & wait")
    started = time.monotonic()
    run = run_timed([str(hanging)], 0.3, tmp_path / "o", tmp_path / "e")
    assert run.timed_out
    assert run.exit_status == -9
    assert time.monotonic() - started < 10


@posix_only
def test_the_suites_memory_does_not_leak_into_the_peak(tmp_path: Path) -> None:
    held = bytearray(300 * 1024 * 1024)
    for index in range(0, len(held), 4096):
        held[index] = 1
    run = run_timed(["/bin/true"], 10, tmp_path / "o", tmp_path / "e")
    assert run.peak_rss_kib < 50 * 1024  # The launcher's floor, not this process's 300 MiB.
    del held


@posix_only
def test_launcher_floor_and_exec_errors(tmp_path: Path) -> None:
    floor = launcher_floor(tmp_path)
    assert floor["count"] == 3
    assert 0 < floor["median"] < 50 * 1024
    run = run_timed([str(tmp_path / "missing")], 10, tmp_path / "o", tmp_path / "e")
    assert run.exit_status == 127
    assert "FileNotFoundError" in run.exec_error


def test_describe() -> None:
    result = describe([4.0, 1.0, 3.0, 2.0])
    assert result["count"] == 4
    assert result["median"] == 2.5
    assert result["min"] == 1.0
    assert result["max"] == 4.0
    # Inclusive quartiles of 1..4: 1.75 and 3.25.
    assert result["iqr"] == pytest.approx(1.5)
    assert result["samples"] == [4.0, 1.0, 3.0, 2.0]  # Order kept, nothing removed.
    assert describe([2.0])["iqr"] is None
    assert describe([])["median"] is None


@posix_only
def test_cpu_affinity_restricts_the_program(tmp_path: Path) -> None:
    import os

    first = sorted(os.sched_getaffinity(0))[0]
    program = "import os; print(sorted(os.sched_getaffinity(0)))"
    run = run_timed(
        [sys.executable, "-c", program], 30, tmp_path / "o", tmp_path / "e", cpus=[first]
    )
    assert run.exit_status == 0
    assert (tmp_path / "o").read_text().strip() == f"[{first}]"
