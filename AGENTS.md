# Project Instructions for Agents and Contributors

These rules apply to the entire repository and must be followed in every session.

## Mission and scope

karasu-slicer-benchmark is an independent, executable and documented suite that measures:

- the **performance** of karasu-slicer (time, CPU, memory, output size, scaling);
- the **geometric accuracy** of the print files it writes, against ground truth computed from
  mathematics;
- the same quantities for **other resin slicers**, so that results can be compared;
- what **UVTools** reports about every produced file (properties, layers, issues).

The suite records objective measurements with their provenance. It does not rank slicers with
scores, does not judge results unless a separate, versioned threshold file is asked for, and does
not replace karasu-slicer's own tests. The approved design is [docs/DESIGN.md](docs/DESIGN.md);
decisions and open questions are in [docs/DECISIONS.md](docs/DECISIONS.md).

## Language policy

Every repository artifact is written in professional English: source code, identifiers,
comments, documentation, test names, CLI text, reports, record fields, commit messages and pull
request descriptions. No other language enters the repository.

## Independence

The suite must stay a black-box observer of karasu-slicer. Its results are only credible if
nothing in it depends on the implementation it measures.

1. karasu-slicer is invoked only as an executable: a binary given by path, or `karasu-cli` built
   from a recorded git ref of a karasu-slicer checkout. Never import, link, vendor or copy its
   crates, source, test fixtures, validation tools, profiles or expected values.
2. Never write to the karasu-slicer checkout. Builds export the ref with `git archive` into this
   suite's work directory and build there.
3. karasu-slicer's public documentation may be read to learn how to use its command line, as any
   user would. Its outputs are never a source of expected values. The only exception is
   regression comparison between two karasu-slicer versions, which is reported as such and never
   as accuracy.
4. Ground truth comes only from mathematics and from this suite's own generators and reference
   implementation (exact plane sections and exact pixel coverage of the meshes it generates).
5. Print files are decoded by the pinned UVTools release, never by the slicer that wrote them.
   karasu-slicer's `reference` image export is a secondary channel used only to check its encoder.
6. Every slicer gets the same treatment: the same models, targets, settings intent, decoder,
   metrics and statistics. A setting that cannot be made equivalent in a slicer is recorded with
   the case, not hidden.

## Clean room

Results of this suite feed karasu-slicer's clean-room development (see karasu-slicer's
`AGENTS.md`), so this repository must be safe for karasu-slicer developers to read. Other
programs, commercial or open source, including UVTools and every compared slicer, are used only
as an ordinary user uses them.

Allowed: their published documentation, their command line and interface, the files they write
from inputs prepared for the purpose, read as data.

Not allowed, for any program and whatever its licence: reading its source code, decompiling,
disassembling, debugging or inspecting its binaries; bypassing licensing, encryption, signatures
or other access controls (an encrypted file is recorded as "not decodable"); modifying an
installed program.

Never put into this repository: another program's source code, pseudocode or a paraphrase of
it; descriptions of another program's internals; another program's assets, presets or profiles.
Profiles used by the suite are authored here and list only the values the suite sets. A document
may mention another program only for its observed behaviour or published facts, citing the
program version, the date, public sources by address and files by SHA-256. Raw third-party
outputs stay in the ignored work directory and are referenced by hash.

## Measurement rules

1. Every reported number has a unit, a definition in `docs/METRICS.md` and a provenance record.
2. Every run records its environment: CPU model, core count, memory, OS and kernel, whether it
   runs under WSL or a virtual machine, load and free memory before and after, Python version,
   the lockfile hash, every external tool's version and SHA-256, the karasu-slicer commit and
   binary SHA-256, and the SHA-256 of every suite definition and input model.
3. Timed runs are serial. Builds, installations, model generation and decoding are outside the
   timed region. Each timed workload has warm-up runs and repeated timed runs; every raw sample
   is kept and reported with median, minimum, maximum and interquartile range. Outliers are never
   removed. Results from different hosts are never averaged or pooled.
4. Failures are results. A nonzero exit status, crash, timeout, decoding failure or missing layer
   is recorded as the outcome of that case. Never retry silently, skip, or replace a failed
   sample; a retry is a new, recorded attempt that leaves the first one in place.
5. Measurements and judgments are separate. Thresholds and pass/fail gates live in versioned
   files under `thresholds/` and are applied only when asked for. Reports state the measured
   values first.
6. Claim only what was measured. WSL results are not native Linux or native Windows results; one
   host is not every host; manually exported files from GUI slicers carry no timing claim.
7. A change to a metric definition, a model generator or the reference implementation can change
   results. Bump the version of what changed, record it in `docs/DECISIONS.md`, and never compare
   records across incompatible versions without saying so.
8. The analysis is deterministic: fixed seeds, sorted iteration, no dependence on wall-clock time
   or thread count. The same stored outputs always give identical metric records.

## Numerical conventions

Millimetres, right-handed coordinates with Z up, `float64` for geometric computation. Pixel
`(column, row)` covers the half-open square `[column, column + 1) × [row, row + 1)` in pixel
units of the decoded image. Every tolerance is named, local to its use, and justified in a
comment or in `docs/METRICS.md`; never introduce an unexplained global epsilon. A degenerate
reference case (a sampling plane through a vertex, an open or self-intersecting mesh) is refused
with an explicit error rather than resolved by a guess.

## Implementation rules

- Python 3.12 or later, managed with `uv`; `pyproject.toml` and `uv.lock` are committed.
- Source lives under `src/kbench/` and exposes the `kbench` command.
- Type hints on public functions. Names carry units where a value has one (`height_mm`,
  `wall_time_s`, `peak_rss_kib`, `area_px`).
- Analysis code is pure functions over arrays and records; file and process I/O stay at the
  edges (adapters, the runner, the store).
- External programs run through adapters with argument lists (never shell strings), explicit
  timeouts, and captured stdout, stderr and exit status.
- No network access during runs. Downloads happen only in explicit install or fetch commands,
  from pinned versions verified by SHA-256.
- Do not add dependencies casually. Before adoption, record in `docs/DECISIONS.md` the licence,
  maintenance, native code it brings, size and why the standard library is not enough.
- Avoid speculative abstractions and empty future modules. Add a slicer adapter, metric or suite
  when it is needed and tested, not before.

## Testing and quality gates

Every metric and every reference computation has known-answer tests, and every metric has
defect-injection tests: synthetic layer stacks shifted, scaled, mirrored, dilated, eroded, with
missing layers or dropped features, where the metric must report the injected defect with the
expected magnitude. Before handing off a change, run:

```console
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

With karasu-cli and UVTools installed (`uv run kbench doctor`), also run
`KBENCH_INTEGRATION=1 uv run pytest -m integration`, which runs the smoke suite and an import with
the real tools. Report commands that could not run, and distinguish failures of
this suite's code from environment failures and from failures of the slicer under test.

## Data and repository hygiene

Committed: code, tests, suite and target definitions, suite-authored profiles, model
specifications, JSON schemas, documentation and, when the owner decides to publish them,
curated result summaries under `results/`.

Never committed: the `work/` directory (tool installs, karasu-slicer builds, generated models,
slicer outputs, decoded layers, raw run records), third-party binaries, third-party models
without a licence that allows it, and any raw evidence from other programs.

## Documentation conventions

- `README.md` says what the suite is, how to install its tools, how to run it and read its
  results, how the repository is laid out, and indexes the documentation. It holds no results,
  history or decisions.
- `docs/METHODOLOGY.md`: protocols, environment control, repetitions, statistics and limits.
- `docs/METRICS.md`: each metric's definition, unit, formula, sign convention and known limits.
- `docs/MODELS.md`: each test model, its parameters and its analytic properties.
- `docs/SLICERS.md`: each adapter, the settings used for equivalence, and the manual export
  protocol for slicers without a command line.
- `docs/DECISIONS.md`: durable decisions as numbered records (`BD-001`, …) with date and reason.

Create each of these documents with the change that gives it content, not before. Update the
relevant document in the same change as the behaviour it describes.

## Repository and Git safety

Inspect `git status` before editing. Preserve user files and unrelated changes. Do not commit,
push, change remotes or create remote repositories unless explicitly asked. Commit messages are
English, descriptive and imperative, and contain no `Co-Authored-By:` trailers or other
reference to AI agents or assistants (the same rule as karasu-slicer).

The remote is `origin` (`dazeroit/karasu-slicer-benchmark`). Until the owner says otherwise
(owner, 2026-11-17), each completed milestone is committed and pushed to `main` directly, and its
CI run is checked; a failing run is fixed before the next milestone starts. Ask the owner before
adding a compared slicer beyond those the design names, changing a metric definition once
results exist, or publishing results.

The repository is licensed MIT (`LICENSE`, BD-001). Never change the licence or add code under
an incompatible licence without explicit owner approval.
