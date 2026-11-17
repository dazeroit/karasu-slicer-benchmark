"""Timed execution of a slicer and the statistics of repeated runs (docs/METHODOLOGY.md).

A timed run measures one process from just before it is started until the kernel reports its
exit: wall time on the monotonic clock, and user time, system time and peak resident memory from
the resource usage that ``wait4`` returns for the process. Output streams go to files, never to
pipes that would have to be drained while timing.

The process is started by a separate small launcher (``timer_helper.py``), not by the suite:
Linux carries the resident-memory high-water mark across ``exec``, so a program started by the
suite's large Python process would report the suite's memory as its own peak (BD-016). The
launcher's own size is the floor of every reported peak; :func:`launcher_floor` measures it.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HELPER = Path(__file__).with_name("timer_helper.py")
# Starting the launcher interpreter and collecting its result take well under a second; the
# margin only keeps a stuck launcher from hanging the suite.
HELPER_MARGIN_S = 60.0
FLOOR_PROGRAM = "/bin/true"


class TimingError(RuntimeError):
    """The launcher itself failed (not the measured program)."""


@dataclass(frozen=True)
class TimedRun:
    """The outcome and cost of one process.

    ``exit_status`` is the exit code, or the negative signal number when a signal ended the
    process; ``timed_out`` says the suite killed it at the timeout; ``exec_error`` says why the
    program could not be started (exit status 127). ``peak_rss_kib`` is the largest resident set
    of the process (and of any child it waited for), as Linux reports it, never below the
    launcher floor.
    """

    argv: list[str]
    exit_status: int
    timed_out: bool
    wall_s: float
    user_s: float
    system_s: float
    peak_rss_kib: int
    exec_error: str | None
    stdout_path: str
    stderr_path: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def run_timed(
    argv: Sequence[str],
    timeout_s: float,
    stdout_path: Path,
    stderr_path: Path,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> TimedRun:
    """Run ``argv`` once through the launcher and measure it. ``argv[0]`` must be a path.

    Requires Linux (``fork``, ``wait4``).
    """
    if not hasattr(os, "wait4") or not hasattr(os, "fork"):
        raise OSError("timed runs need fork and wait4, which this platform lacks")
    arguments = [str(argument) for argument in argv]
    request = {
        "argv": arguments,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "timeout_s": timeout_s,
        "cwd": str(cwd) if cwd is not None else None,
        "env": dict(env) if env is not None else None,
    }
    try:
        helper = subprocess.run(
            [sys.executable, "-I", "-S", str(HELPER)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout_s + HELPER_MARGIN_S,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimingError(f"the launcher did not return: {error}") from error
    if helper.returncode != 0:
        raise TimingError(
            f"the launcher failed ({helper.returncode}): {helper.stderr.strip()[-1000:]}"
        )
    result = json.loads(helper.stdout)
    return TimedRun(
        argv=arguments,
        exit_status=result["exit_status"],
        timed_out=result["timed_out"],
        wall_s=result["wall_ns"] / 1e9,
        user_s=result["user_s"],
        system_s=result["system_s"],
        peak_rss_kib=result["peak_rss_kib"],  # Linux reports KiB.
        exec_error=result["exec_error"],
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )


def launcher_floor(directory: Path, runs: int = 3) -> dict[str, Any]:
    """The peak memory reported for a program that uses almost none (``/bin/true``): the floor
    under every reported peak. Returns its :func:`describe` summary in KiB."""
    samples = []
    for index in range(runs):
        run = run_timed(
            [FLOOR_PROGRAM],
            30.0,
            directory / f"floor-{index}.stdout",
            directory / f"floor-{index}.stderr",
        )
        samples.append(run.peak_rss_kib)
    return describe(samples)


def describe(values: Sequence[float]) -> dict[str, Any]:
    """Count, median, minimum, maximum and inclusive-quartile IQR of every sample, none removed.

    The IQR uses ``statistics.quantiles(method="inclusive")`` and is ``None`` for fewer than two
    samples. It describes spread; it is not a confidence interval.
    """
    samples = [float(value) for value in values]
    if not samples:
        return {"count": 0, "median": None, "min": None, "max": None, "iqr": None, "samples": []}
    iqr = None
    if len(samples) >= 2:
        q1, _, q3 = statistics.quantiles(samples, n=4, method="inclusive")
        iqr = q3 - q1
    return {
        "count": len(samples),
        "median": statistics.median(samples),
        "min": min(samples),
        "max": max(samples),
        "iqr": iqr,
        "samples": samples,
    }
