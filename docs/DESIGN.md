# karasu-slicer benchmark suite: design

**Status:** approved by the owner on 2026-11-17 (BD-003), as proposed the same day. Decisions
taken since, and the questions still open, are in [DECISIONS.md](DECISIONS.md).

## 1. Goal

An independent, executable and documented suite that measures, with objective and reproducible
numbers:

1. **Performance** of karasu-slicer: wall time, CPU time, peak memory, output size and how they
   scale with triangles, layers, panel resolution and features.
2. **Geometric accuracy** of the print files karasu-slicer writes: every decoded layer compared
   with the exact cross-section of the model that was sliced.
3. **Comparison** with other resin slicers on the same models, targets and settings intent.
4. **UVTools analysis** of every produced file: declared properties, decoded layers and the
   issues UVTools detects.

**Non-goals:** replacing karasu-slicer's own tests; scoring or ranking slicers with a single
number; physical print testing (it may be added later as separate, optional evidence); judging
results unless a versioned threshold file is applied on request.

## 2. Principles

- **Black box.** karasu-slicer is an executable and a commit hash. The suite never links its
  code or reuses its fixtures, tools or validators.
- **Ground truth from mathematics.** The suite generates its own test meshes and computes, from
  those meshes, the exact cross-section at each layer and the exact fraction of each pixel it
  covers. Expected values never come from a slicer's output.
- **Independent decoding.** Every print file, from every slicer, is decoded by the same pinned
  UVTools release.
- **Equal treatment.** Same models, targets, settings intent, decoder, metrics and statistics for
  every slicer. Settings that cannot be made equivalent are recorded with the case.
- **Full provenance.** Environment, versions, hashes, command lines, exit statuses, stdout,
  stderr and raw samples are kept for every run. Failures are results.
- **Measurements before judgments.** Metrics are numbers with units. Thresholds are separate and
  optional.
- **Clean room.** Other programs are used only as an ordinary user uses them (see `AGENTS.md`).

## 3. What is measured

### 3.1 Performance

Per slicer, target and case:

| Metric | Unit | Source |
| --- | --- | --- |
| Wall time | s | monotonic clock around the process |
| User and system CPU time | s | kernel resource usage of the process at exit (`os.wait4`) |
| Peak resident memory | KiB | the same resource usage (`ru_maxrss`), whole process |
| Output size | bytes | the written file |
| Throughput | layers/s, triangles/s, megapixels/s | derived from the above |
| Fixed overhead | s | the same protocol on a minimal model, reported, never subtracted |
| karasu-slicer phase durations | s | its `--log` file, karasu-only, observed and not compared |

**Protocol:**

- Builds, installations, model generation and decoding happen before timing.
- Each workload runs W warm-up and N timed repetitions (defaults 2 and 10), serially, each into a
  fresh output path. All samples are kept; reports give median, minimum, maximum and IQR.
- Warm page cache by default, stated in every report; cold-cache runs are a separate, explicit
  mode where the host allows it.
- Optional CPU pinning (`taskset`) and thread-count sweeps where a slicer exposes a control.
- Load average and free memory are recorded before and after each workload. A run on a busy
  host is flagged, never discarded.

**Scaling studies** (one variable at a time): triangle count (about 10^3 to 10^7, subdivided
spheres), layer count (model height), panel resolution (4K to 16K targets), anti-aliasing level,
and karasu-only features (hollowing, automatic supports, wall verification).

### 3.2 Geometric accuracy

The decoded layer stack is compared with the reference stack of the same mesh, target and layer
schedule.

**Reference.** For layer *i*, the mesh as written to STL (its `float32` coordinates) is cut by
the plane at the layer's mid-height. The section's polygons are filled, and the exact area of
each pixel covered is computed analytically. A plane through a vertex, or a mesh whose section
is not a valid set of closed polygons, is refused rather than guessed. The implementation is
checked against analytic areas and high supersampling in the tests.

**Frames.** Pixel coordinates become plate millimetres with the file's declared resolution and
pixel pitch, as UVTools reports them; a declaration that differs from the target is itself a
finding. Each model carries a chiral marker, so the orientation of the stored image (one of the
eight flips and quarter turns) is identified and reported; shape metrics are computed after
applying it. One translation per model registers the stacks: a least-squares fit of the coverage
on layers spread over the model's height, started from the centroids (BD-009). It is reported
as the placement error, and it applies to the whole stack, so drift between layers is never
absorbed. [METRICS.md](METRICS.md) is the authoritative definition of every metric.

**Metrics:**

| Level | Metric | Unit |
| --- | --- | --- |
| Layer | Material area and its error (pixels weighted by grey level) | mm² |
| Layer | Intersection over union (pixel is material at coverage ≥ 0.5 or grey ≥ 128) | ratio |
| Layer | Symmetric difference area | mm² |
| Layer | Boundary deviation: mean, 95th percentile and maximum (Hausdorff) contour distance | mm |
| Layer | Centroid offset (X, Y) and bounding-box size error | mm |
| Model | Volume (sum of layer areas × layer thickness) against the mesh volume | mm³, % |
| Model | Height and per-layer Z positions against the schedule | mm |
| Model | Z sampling phase: which height inside each layer the slicer samples, fitted on cones and spheres | fraction of layer |
| Model | Placement offset from the requested position | mm |
| Model | Stored image orientation | one of 8 |
| Feature | Diameter of holes and pins (circle fit on the decoded contour) | mm |
| Feature | Smallest pin, hole, gap and wall present in the output | mm |
| Anti-aliasing | Mean absolute error between grey/255 and exact coverage on edge pixels | ratio |
| Metadata | Declared layer count, heights, exposures, bottom layers and lift against the request | per field |
| Determinism | Equal output SHA-256 across repeated runs and thread counts; equal decoded layers | yes/no |
| Encoder (karasu) | Decoded machine file against karasu's own `reference` image export of the same job | differing pixels |

### 3.3 UVTools analysis

UVTools is the shared, independent reader of every file. Its command-line program
`UVtoolsCmd` provides, per its published documentation, `extract`, `convert`, `print-properties`,
`print-issues` and `compare`; the exact syntax and outputs are confirmed on the pinned release
before use.

- **Decoding:** layers to PNG for the accuracy metrics.
- **Properties:** resolution, pixel pitch, layer height, layer count, exposures, lift, volume,
  print-time estimate, recorded per file and checked against the request.
- **Issues:** islands, overhangs, resin traps, suction cups, touching bounds and empty layers,
  with the pinned release's settings recorded. These are UVTools' findings, reported side by side
  across slicers for the same case, not ground truth.

## 4. Slicers and targets

| Slicer | Mode | Measured |
| --- | --- | --- |
| karasu-slicer | `karasu-cli`, automated; built from a git ref or given as a binary | everything |
| PrusaSlicer | command line (SL1/SL1S export), automated | everything |
| CHITUBOX, Lychee, ELEGOO SatelLite, Anycubic Photon Workshop | GUI only: manual export by a documented protocol, imported with a provenance record (slicer, version, OS, date, settings, SHA-256) | accuracy, metadata, UVTools; no timing |

Each slicer has one adapter: its version, how its settings file is written from the case, the
command line, and where its output lands. Settings files are authored by the suite and list only
the values it sets (support, pad, raft, hollowing and XY compensation off for accuracy cases,
unless the case is about them).

**Targets** are benchmark printers: panel resolution, pixel pitch, build volume, layer height,
and the format and profile each slicer uses for them. Values come from the manufacturer's
published specification, cited with address and date. Candidates:

- a Prusa SL1S target, the common ground with PrusaSlicer (karasu-slicer writes
  `prusa-sl1s-firmware-motion` with a suite-authored custom printer);
- a 4K target from karasu-slicer's catalog with verified orientation (`.goo` or Photon Workshop);
- the Anycubic Photon P1 (`.pp1`), the printer karasu-slicer's files have been printed on;
- a 16K target for resolution scaling.

## 5. Test models

Generated by the suite, deterministic, with a manifest per model: parameters, generator
version, STL SHA-256, triangle count, exact mesh volume, bounds.

- **Primitives:** cube, elongated box, regular-prism cylinders at several segment counts,
  pyramids and cones (Z phase), spheres, a box with a sealed internal cavity.
- **Feature ladders:** pins, holes, gaps, walls and slots from 0.05 to 2 mm; overhang ramps.
- **Orientation marker:** a chiral mark on every model base.
- **Scaling:** spheres from about 10^3 to 10^7 triangles; tall columns; dense plates of many
  instances merged into one mesh.
- **Robustness (behaviour only):** open, non-manifold, reversed and self-intersecting meshes.
  What each slicer does (refuses, repairs, writes) is recorded; no accuracy is computed.
- **Real-world models (optional):** openly licensed models pinned by address and SHA-256,
  fetched into the work directory, never committed. When a model is closed and does not
  self-intersect, its exact sections serve as reference too.

Model dimensions are chosen so that no vertex lies on a sampling plane of any target schedule.

## 6. Runs and records

- A **run** is one suite, on one host, for a set of slicers, targets and cases. Its identifier is
  the UTC start time plus a short hash.
- Everything raw goes to the ignored `work/runs/<run-id>/`: `run.json` (environment, tools,
  hashes), and per case and slicer the command line, stdout, stderr, exit status, timing samples,
  the output file, UVTools outputs, and `metrics.json`. Decoded layers can be removed after
  analysis to save space; their hash stays.
- Records are JSON with a `schema_version`, validated against `schemas/`.
- `kbench report` writes Markdown and a self-contained HTML page: per-slicer tables, scaling
  charts, and comparisons against a baseline run (karasu-slicer regressions) or across slicers on
  the same target.
- Curated summaries may be published under `results/` when the owner decides; raw outputs never.

## 7. Implementation

**Language: Python 3.12+, managed with `uv` (BD-002).** The work is analysis-heavy (arrays, distance
transforms, connected components, statistics), Python is already the language of karasu-slicer's
measurement tools, and a different language from the Rust code under test removes any temptation
to share code with it. Hot paths are vectorised with NumPy and cropped to each model's bounds; if
the reference rasterizer proves too slow at 16K, a compiled worker is a separate decision.

**Dependencies** (each reviewed in `docs/DECISIONS.md` before adoption): NumPy, Pillow, SciPy;
development only: pytest, ruff. Charts are written as inline SVG, without a plotting library.

**External tools** pinned by version and SHA-256, installed by `tools/` scripts into `work/tools/`:
UVTools (Linux x64 portable build, which includes `UVtoolsCmd`) and PrusaSlicer. karasu-cli is
built with `cargo build --release -p karasu-cli --locked` from a `git archive` export, or taken
as a given binary; its commit and SHA-256 are recorded either way. Each tool is found through its
`KBENCH_*` environment variable, otherwise on `PATH`; a variable naming something unusable is an
error, never a silent fallback (BD-006).

**Command line:**

```console
kbench env                                     # the environment record every run stores
kbench doctor                                  # tools present, versions, hashes
kbench karasu build --repo PATH --ref REF      # build karasu-cli into work/
kbench models build [--suite NAME]             # generate test models and their manifest
kbench run --suite NAME [--slicer ...] [--target ...] [--case ...]
kbench analyze RUN                             # recompute metrics from stored outputs
kbench import FILE --slicer S --version V --target T --case C   # manually exported files
kbench report RUN [--baseline RUN]
```

**Suites:** `smoke` (minutes, suitable for CI), `accuracy`, `performance`, `scaling`,
`determinism`, `full`.

## 8. Repository layout

```text
karasu-slicer-benchmark/
├── AGENTS.md                 permanent rules for agents and contributors
├── README.md                 what the suite is, setup, running, layout, documentation index
├── LICENSE                   MIT (BD-001)
├── pyproject.toml, uv.lock   Python project and pinned environment
├── .github/workflows/ci.yml  lint and tests on every push and pull request
├── src/kbench/
│   ├── cli.py                the `kbench` command
│   ├── config.py             suite, target and case loading and validation (TOML)
│   ├── env.py                host environment capture
│   ├── tools.py              external tool discovery, hashing and version queries
│   ├── install.py            pinned tool installation
│   ├── karasu_build.py       karasu-cli builds from a git ref
│   ├── execution.py          timed runs and their statistics
│   ├── timer_helper.py       the small launcher that starts and measures each timed run
│   ├── uvtools.py            UVtoolsCmd: decoding, properties, issues
│   ├── slicers.py            slicer adapters
│   ├── run.py                suite runs
│   ├── report.py             Markdown reports (HTML and comparisons in P4)
│   ├── process.py            external programs with captured output and hard timeouts
│   ├── provenance.py         hashing, suite state, run manifests, record versions
│   ├── models.py             the model catalog, builder and manifest
│   ├── reference.py          layer schedules and reference layers
│   ├── geometry/             meshes, primitives, polygons, STL I/O, exact sections, pixel coverage
│   └── metrics/              orientation, layer metrics, stack and body metrics (more per phase)
├── suites/                   smoke.toml, accuracy.toml, performance.toml (more per phase)
├── targets/                  one TOML per benchmark printer, with each slicer's settings
│   └── profiles/             suite-authored settings files for slicers that need them (P3)
├── models/                   catalog.toml; external models by address and SHA-256
├── thresholds/               optional, versioned gates, separate from measurements
├── schemas/                  JSON Schemas of run, case and metric records
├── tools/                    pins.toml: pinned external tools (UVTools, PrusaSlicer)
├── results/                  curated, published summaries (if decided)
├── docs/
│   ├── DESIGN.md             this document
│   ├── METHODOLOGY.md        protocols, environment control, statistics, limits
│   ├── METRICS.md            each metric: definition, unit, formula, limits
│   ├── MODELS.md             test models and their analytic properties
│   ├── SLICERS.md            adapters, settings equivalence, manual export protocols
│   └── DECISIONS.md          BD-NNN decision records
├── tests/                    known-answer and defect-injection tests
└── work/                     ignored: tools, builds, models, runs, raw outputs
```

## 9. Validating the suite itself

- **Known answers:** generator volumes and bounds against formulas; section areas against
  analytic areas; pixel coverage against high supersampling; statistics against hand-computed
  values.
- **Defect injection:** the reference stack itself, run through the metrics, gives zero error;
  then shifted by sub-pixel and whole-pixel amounts, scaled by 1 %, mirrored, dilated and eroded
  by one pixel, with a layer missing or duplicated, a feature removed, grey levels distorted. Each
  defect must be reported by the right metric with the expected magnitude.
- **Decoder cross-check:** UVTools' decoding of a karasu-slicer machine file against karasu-slicer's
  own `reference` export of the same job.
- **Reproducibility:** analysing the same stored outputs twice gives byte-identical metric
  records.

## 10. Phases

| Phase | Content | Done when |
| --- | --- | --- |
| P0 | Skeleton: `pyproject`, the `kbench` command with `env` and `doctor`, docs, decisions, CI with lint and tests | the owner approves the design and P0 passes its gates |
| P1 | Models, exact sections, reference rasterizer, layer and model metrics | known-answer and defect-injection tests pass, no slicer needed |
| P2 | karasu adapter, process runner, UVTools decoding, properties and issues | first accuracy and performance report of karasu-slicer on two targets |
| P3 | PrusaSlicer adapter, manual import protocol for GUI slicers | first comparison report on the SL1S target |
| P4 | Scaling, determinism, feature metrics, regression comparison between karasu-slicer versions, HTML report | full suite documented and reproducible |
| P5 | Optional: native Windows runs, scheduled runs on a dedicated host | as decided |

## 11. Decisions

The licence (MIT, BD-001) and the language (Python, BD-002) are decided. The initial targets,
the GUI slicers for manual campaigns, the publication of results, building karasu-cli from
source, and hosting remain open; [DECISIONS.md](DECISIONS.md) lists them with the default this
design assumes until the owner decides.
