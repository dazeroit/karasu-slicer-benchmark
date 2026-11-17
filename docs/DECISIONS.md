# Decisions

Durable decisions about the suite, numbered `BD-NNN`, newest last. A decision is changed only by
a later record that names the one it supersedes.

## BD-001: MIT licence

2026-11-17, owner. The repository is licensed under the MIT licence (`LICENSE`). It contains no
karasu-slicer code, so karasu-slicer's AGPL does not apply to it; MIT keeps the suite and its
records easy to reuse.

## BD-002: Python 3.12 managed with uv

2026-11-17, owner. The suite is written in Python 3.12 or later. `uv` manages the environment;
`pyproject.toml` and `uv.lock` are committed so every host resolves the same packages. Reasons:
the work is mostly analysis of arrays and records; karasu-slicer's own measurement tools are
Python; and a language different from the Rust code under test removes any temptation to share
code with it. A compiled worker for a hot path, if ever needed, is a separate decision.

## BD-003: Design approved

2026-11-17, owner. The proposal of the same day is approved as [DESIGN.md](DESIGN.md), with the
rules of [AGENTS.md](../AGENTS.md).

## BD-004: Development dependencies pytest and ruff

2026-11-17. Development only; neither is imported by the suite at run time.

| | pytest | ruff |
| --- | --- | --- |
| Purpose | test runner | formatter and linter |
| Licence | MIT | MIT |
| Native code | none (pure Python; brings `iniconfig`, `packaging`, `pluggy`, `pygments`, and `colorama` on Windows) | a compiled Rust executable shipped in the wheel, no Python dependencies |
| Maintenance | long-established, regular releases | actively developed, frequent releases |
| Why not the standard library | `unittest` lacks fixtures such as `tmp_path`, `monkeypatch` and `capsys` and readable assertion failures | the standard library has no formatter or linter |

Exact versions and hashes are pinned in `uv.lock`.

## BD-005: No personal identifiers in records

2026-11-17. Environment and tool records hold what can change a measurement and nothing that
identifies a person: no host name and no user name. Raw records under `work/` can contain local
paths, which may include a user name; curated summaries published under `results/` give tool
versions and hashes, never local paths.

## BD-006: Tool discovery through environment variables, then PATH

2026-11-17. Each external tool is found through its `KBENCH_*` variable when it is set and not
empty, otherwise on `PATH`. A variable that names a missing or non-executable file is reported as
invalid and the search does not fall back to `PATH`: measuring a different binary than the one
configured would silently change the results. Pinned installs under `work/tools/` will be added
to this order when their installers exist.

## Open questions

Each is answered by a later `BD` record. Until then, the suite assumes the default given.

| Question | Default assumed |
| --- | --- |
| Initial benchmark targets | Prusa SL1S (common ground with PrusaSlicer), a 4K catalog printer with verified orientation, the Anycubic Photon P1, a 16K printer |
| GUI slicers for manual campaigns | none until the owner names them |
| Publication of results | nothing published; results stay under `work/` |
| Building karasu-cli from a git ref | allowed, by `git archive` export into `work/`, never writing to the karasu-slicer checkout |
| Hosting, remote and CI service | local repository only; the GitHub Actions workflow is ready for when it is hosted |
