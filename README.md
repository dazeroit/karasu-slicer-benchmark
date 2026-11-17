# karasu-slicer-benchmark

An independent benchmark suite for [karasu-slicer](https://github.com/dazeroit/karasu-slicer) and
other MSLA/LCD resin slicers. It measures, with objective and reproducible numbers:

- **performance**: wall time, CPU time, peak memory and output size, and how they scale;
- **geometric accuracy** of the print files: every decoded layer against the exact
  cross-section of the model that was sliced;
- the same quantities for **other slicers**, on the same models and printers;
- what **UVTools** reports about every produced file.

karasu-slicer is treated as a black box: the suite runs its command line and reads its files, and
never uses its code, fixtures or outputs as expected values. Every print file is decoded by the
same pinned UVTools release, whichever slicer wrote it. The design is in
[docs/DESIGN.md](docs/DESIGN.md).

## Requirements

- Linux. Native Windows is not supported yet.
- Python 3.12 or later and [uv](https://docs.astral.sh/uv/).
- External tools, found through an environment variable or on `PATH`:

  | Tool | Variable | Needed for |
  | --- | --- | --- |
  | `karasu-cli` | `KBENCH_KARASU_CLI` | runs (the slicer under test) |
  | `UVtoolsCmd` (UVTools) | `KBENCH_UVTOOLSCMD` | runs (decoding and file analysis) |
  | `git` | `KBENCH_GIT` | building karasu-cli from a ref, recording the suite's commit |
  | `cargo` | `KBENCH_CARGO` | building karasu-cli from a ref |

  A variable that names a missing or non-executable file is an error; the suite then does not
  look on `PATH`.

## Setup

```console
uv sync
uv run kbench install uvtools
uv run kbench karasu build --repo ../karasu-slicer --ref HEAD
export KBENCH_KARASU_CLI=<the path the build prints>
uv run kbench doctor
```

`kbench install uvtools` downloads the pinned UVTools release and checks its SHA-256.
`kbench karasu build` builds karasu-cli from a commit of a karasu-slicer checkout without
writing to it, so every run can name the commit it measured; any karasu-cli can be used
instead through `KBENCH_KARASU_CLI`. `kbench doctor` lists each tool with its path, SHA-256 and
version, and exits with status 1 while a required tool is not ready.

## Usage

```console
uv run kbench env            # the environment record every run stores
uv run kbench env --json
uv run kbench doctor --json  # the tool inventory as JSON
uv run kbench models list    # the test models
uv run kbench models build   # STL files and manifest.json into work/models/
uv run kbench run --suite smoke        # a few minutes: time, decode and measure one job
uv run kbench run --suite accuracy     # every target and single-shape model
uv run kbench run --suite performance  # timing only, more repetitions, scaling series
uv run kbench report work/runs/<run-id>
```

Each run writes `work/runs/<run-id>/` with its records and `report.md`. Everything a run
produces goes under `work/` (or `KBENCH_WORK`), which Git ignores.

## Checks before a change

```console
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

## Repository layout

- `src/kbench/`: the suite and its `kbench` command; `geometry/` (meshes, STL, exact sections and
  pixel coverage), `metrics/` (layer, stack and body metrics).
- `models/catalog.toml`: the test models.
- `targets/`: benchmark printers (panel, layer height, each slicer's settings).
- `suites/`: suites of cases with their timing parameters.
- `tools/pins.toml`: pinned external tools.
- `tests/`: the suite's tests.
- `docs/`: design, methodology and decisions.
- `.github/workflows/`: continuous integration.
- `work/` (ignored): tools, builds, generated models, runs and raw outputs.

## Documentation

- [AGENTS.md](AGENTS.md): permanent rules for contributors and agents.
- [docs/DESIGN.md](docs/DESIGN.md): what the suite measures and how it is built.
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md): records, environment, tools and the reference.
- [docs/METRICS.md](docs/METRICS.md): every metric, its definition, unit and limits.
- [docs/MODELS.md](docs/MODELS.md): the test models and their manifest.
- [docs/SLICERS.md](docs/SLICERS.md): how each slicer is driven and how UVTools reads the files.
- [docs/DECISIONS.md](docs/DECISIONS.md): decisions and open questions.

## Licence

MIT, see [LICENSE](LICENSE). karasu-slicer is a separate project under its own licence; its name
and logo are its owner's trademarks.
