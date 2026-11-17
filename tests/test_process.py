from __future__ import annotations

import time
from pathlib import Path

from support import MakeScript, posix_only

from kbench.process import CapturedProcess, run_captured


@posix_only
def test_captures_both_streams_and_status(make_script: MakeScript) -> None:
    script = make_script("talk", 'echo "to stdout"; echo "to stderr" >&2; exit 3')
    result = run_captured([str(script)], timeout_s=10)
    assert result.exit_status == 3
    assert result.stdout == "to stdout\n"
    assert result.stderr == "to stderr\n"
    assert not result.timed_out
    assert result.start_error is None


def test_reports_a_program_that_cannot_start(tmp_path: Path) -> None:
    result = run_captured([str(tmp_path / "does-not-exist")], timeout_s=10)
    assert result.exit_status is None
    assert result.start_error is not None
    assert "FileNotFoundError" in result.start_error


@posix_only
def test_kills_the_process_group_at_the_timeout(make_script: MakeScript) -> None:
    # The sleeping grandchild would keep the pipes open if only the shell were killed.
    script = make_script("hang", "sleep 30 & wait")
    started = time.monotonic()
    result = run_captured([str(script)], timeout_s=0.2)
    elapsed_s = time.monotonic() - started
    assert result.timed_out
    assert result.exit_status is None
    assert elapsed_s < 10


def test_first_line_prefers_stdout_and_skips_blank_lines() -> None:
    result = CapturedProcess(("x",), 0, "\n  \n tool 1.2 \nmore\n", "warning\n", False, None)
    assert result.first_line() == "tool 1.2"


def test_first_line_falls_back_to_stderr() -> None:
    result = CapturedProcess(("x",), 0, "", "\nonly here\n", False, None)
    assert result.first_line() == "only here"


def test_first_line_of_silent_process() -> None:
    assert CapturedProcess(("x",), 0, "", "", False, None).first_line() is None
