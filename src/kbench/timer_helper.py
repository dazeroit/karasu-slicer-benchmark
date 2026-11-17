"""Standalone launcher for timed runs (run as ``python -I -S timer_helper.py``; no imports from
the suite).

Linux carries a process's resident-memory high-water mark across ``exec``: a program started
directly by the suite's own (large) Python process would report the suite's memory as its peak.
This launcher is a fresh, small interpreter that forks and execs the program itself, so the
program's reported peak starts from the launcher's few megabytes (the launcher floor, measured
with every run) instead of the suite's size.

Request on standard input (JSON): ``argv``, ``stdout``, ``stderr`` (file paths), ``timeout_s``,
``cwd`` (or null), ``env`` (or null). Result on standard output (JSON): ``exit_status``,
``timed_out``, ``wall_ns``, ``user_s``, ``system_s``, ``peak_rss_kib``, ``exec_error``.
"""

import json
import os
import signal
import sys
import threading
import time


def main() -> int:
    request = json.load(sys.stdin)
    argv = [str(argument) for argument in request["argv"]]
    env = request.get("env")
    cwd = request.get("cwd")
    stdout = os.open(request["stdout"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    stderr = os.open(request["stderr"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    devnull = os.open(os.devnull, os.O_RDONLY)
    error_read, error_write = os.pipe2(os.O_CLOEXEC)

    started = time.perf_counter_ns()
    pid = os.fork()
    if pid == 0:  # Child: become the program.
        try:
            os.setsid()
            os.dup2(devnull, 0)
            os.dup2(stdout, 1)
            os.dup2(stderr, 2)
            if cwd is not None:
                os.chdir(cwd)
            if env is None:
                os.execv(argv[0], argv)
            else:
                os.execve(argv[0], argv, env)
        except OSError as error:
            os.write(error_write, f"{type(error).__name__}: {error}".encode())
        os._exit(127)

    os.close(error_write)
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        try:  # noqa: SIM105 - no contextlib: the launcher keeps its imports minimal.
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    watchdog = threading.Timer(float(request["timeout_s"]), kill)
    watchdog.start()
    try:
        _, status, usage = os.wait4(pid, 0)
        ended = time.perf_counter_ns()
    finally:
        watchdog.cancel()
    exec_error = os.read(error_read, 4096).decode(errors="replace") or None

    json.dump(
        {
            "exit_status": os.waitstatus_to_exitcode(status),
            "timed_out": timed_out.is_set(),
            "wall_ns": ended - started,
            "user_s": usage.ru_utime,
            "system_s": usage.ru_stime,
            "peak_rss_kib": usage.ru_maxrss,
            "exec_error": exec_error,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
