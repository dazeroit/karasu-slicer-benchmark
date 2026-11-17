"""Running external programs with captured output and a hard timeout.

Every external program the suite starts (slicers, UVTools, git, cargo) goes through an argument
list, never a shell string, so that no input is ever interpreted by a shell.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CapturedProcess:
    """The observable outcome of one process.

    ``exit_status`` is the process's status as Python reports it: negative values mean the
    process was ended by that signal number. It is ``None`` when the process could not start
    (``start_error`` says why) or was killed at the timeout (``timed_out``).
    """

    argv: tuple[str, ...]
    exit_status: int | None
    stdout: str
    stderr: str
    timed_out: bool
    start_error: str | None

    def first_line(self) -> str | None:
        """The first non-blank line of stdout, or of stderr when stdout has none."""
        for stream in (self.stdout, self.stderr):
            for line in stream.splitlines():
                if line.strip():
                    return line.strip()
        return None


def run_captured(
    argv: Sequence[str],
    timeout_s: float,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CapturedProcess:
    """Run ``argv`` to completion or until ``timeout_s`` elapses, capturing both streams.

    On POSIX the process starts in its own session, so that at the timeout the whole process
    group is killed and no orphaned child keeps the output pipes open.
    """
    arguments = tuple(str(argument) for argument in argv)
    try:
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            start_new_session=os.name == "posix",
        )
    except OSError as error:
        return CapturedProcess(arguments, None, "", "", False, f"{type(error).__name__}: {error}")

    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        stdout, stderr = process.communicate()
        timed_out = True

    return CapturedProcess(
        argv=arguments,
        exit_status=None if timed_out else process.returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        timed_out=timed_out,
        start_error=None,
    )


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):  # The group has already exited.
            os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
