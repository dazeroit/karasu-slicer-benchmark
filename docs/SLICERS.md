# Slicers and readers

How the suite drives each slicer and how it reads their files. Every program here is used as an
ordinary user uses it: its documented command line and the files it writes (AGENTS.md, Clean
room). Observations are dated and name the version.

## karasu-slicer (`karasu-cli`)

The slicer under test, found through `KBENCH_KARASU_CLI` or `PATH` (BD-006). `kbench karasu
build --repo <checkout> --ref <ref>` builds it from a commit: the checkout is only read (`git
archive` into `work/karasu/<commit>/src`), Cargo builds `karasu-cli` with the release profile and
`--locked`, and `build.json` records the commit, the toolchain and the binary's SHA-256. A run
whose karasu-cli comes from such a build records that commit. The build is also selected: runs
use it without any setting until another commit is built or re-selected, unless
`KBENCH_KARASU_CLI` names another karasu-cli (BD-025).

**Command** (`src/kbench/slicers.py`), built from the target's `[slicers.karasu]` table:

```console
karasu-cli slice --model <model.stl> --units mm --printer <printer id> --resin <resin id> \
  --format <format id> --output <file> --center --no-progress
```

- Printer, resin and format are built-in catalog ids; the print setting is the catalog's for
  that printer and resin, which karasu-cli reports on standard error.
- `--center` centres the model on the plate; the model already stands on `z = 0`.
- Anti-aliasing, XY compensation, supports, hollowing and repairs are left at their defaults,
  which karasu-cli reports in its summary (observed with 0.2.0-dev at commit `45bc195`:
  anti-aliasing 1 sample per pixel, no repairs needed for the suite's models).
- The first warm-up run adds `--log <file>`, which records karasu-slicer's own phase durations;
  timed runs never write a log.

**SL1S profile.** For the SL1S target karasu-slicer gets suite-authored printer and resin
profiles (`targets/profiles/karasu/`), in the format of `ProfileDocument::to_json` that its
documentation describes; with `swap_xy` the resolution is in panel order (1620 × 2560).

**Observed (0.2.0-dev, `45bc195`, 2026-11-17)**, on layer images as UVtoolsCmd v7.1.2 extracts
them:

- the `.goo` file for the Elegoo Mars 5 declares `DisplayMirror: Vertically`, and its images are
  the top view mirrored along Y (`mirror_y`);
- the `.pwma` file for the Anycubic Photon Mono 4K declares `DisplayMirror: Horizontally`, and its
  images are also `mirror_y` of the top view. Whether the declaration names the panel's mirror
  or the image's is a convention of the format and the firmware; the suite reports both, and
  does not judge which is right;
- UVtoolsCmd v7.1.2 refuses its `.sl1s` files: "Malformed file: prusaslicer.ini is missing"
  (BD-018).

## UVTools (`UVtoolsCmd`)

The shared reader of every print file, pinned at v7.1.2 (Linux x64 portable build) in
`tools/pins.toml` and installed with `kbench install uvtools` (BD-011). `UVtoolsCmd --version`
reports the command-line front end's own version (2.2.0 in this release); `--core-version`
reports the UVTools release, which the suite records.

Commands used (`src/kbench/uvtools.py`). `--no-progress` is a global option and goes before the
command:

| Purpose | Command | Output read |
| --- | --- | --- |
| Decode layers | `extract <file> <dir> -c Layers` | `layerNNN.png`, 8-bit greyscale, the panel's size |
| File properties | `print-properties <file>` | `Name: value` lines; the first occurrence of each name counts |
| Layer properties | `print-properties <file> -r 0:<last>` | blocks opened by `# Layer: <index>`; `PositionZ` is the top of the layer in mm |
| Issues | `print-issues <file> -i -o -r -s -t -p -e` | `Issues: <n>`, then `<type>, <layer>, <area>px², {X=…,Y=…,Width=…,Height=…}` |

Lines that do not parse are kept in the record (`unparsed`), never dropped. The raw outputs are
saved beside each case in the run directory.

**SL1 and SL1S** archives are decoded by the suite itself for every slicer (BD-018,
`src/kbench/sl1.py`): the layer images `<jobDir><index, 5 digits>.png` and `config.ini`
(`layerHeight`, `numFast + numSlow`). UVTools still reads their properties and issues.

**Layer schedule.** Layer `i` spans from the previous layer's `PositionZ` (0 for the first) to
its own. Two layers at the same height are refused: the reference has no slab for them.

**Issues** are UVTools' heuristic findings with every detector on: islands, overhangs, resin
traps, suction cups, touching bounds, print height and empty layers. They are reported side by
side across slicers as observations, not as ground truth.

## PrusaSlicer

Compared through its command line, pinned at 2.8.1 (BD-015) and installed with `kbench install
prusaslicer`; the first line of `--help` names the build, which the suite records as its
version. It is given no preset: only the options its `--help-sla` documents, built from the
target's `[slicers.prusaslicer]` table (`src/kbench/slicers.py`):

```console
AppRun --export-sla --printer-technology SLA \
  --display-width 127 --display-height 80 --display-pixels-x 2560 --display-pixels-y 1620 \
  --display-orientation portrait --bed-shape 0x0,127x0,127x80,0x80 --max-print-height 150 \
  --layer-height 0.05 --initial-layer-height 0.05 \
  --no-supports-enable --no-pad-enable --no-hollowing-enable --gamma-correction 0 \
  --exposure-time 2 --initial-exposure-time 25 --faded-layers 3 \
  --center 63.5,40 --output <file>.sl1s <model.stl>
```

- The bed is the panel, and the model is centred on it.
- `--gamma-correction 0` thresholds the masks (no anti-aliasing), matching karasu-cli's default of
  one sample per pixel.
- Exposure values only fill the file; they do not change the masks.
- The SHA-256 the inventory records is the unpacked `AppRun` launcher's; the whole AppImage is
  pinned by its own SHA-256.

**Observed (2.8.1, 2026-11-17):**

- The `.sl1s` file stores its layer images in portrait, 1620 px wide and 2560 px tall, and
  `config.ini` holds the creation time, so two runs never give byte-identical files.
- In portrait orientation, each plate axis is rasterised with the other axis's pitch: harmless
  with square pixels, a distortion and an offset with non-square ones (BD-017).

## DragonFruit

An open-source resin slicer of the Open Resin Alliance (AGPL-3.0-or-later). Its released
binaries are the desktop application; its documentation (`docs/reference/cli.md`) describes a
command line, `dragonfruit-cli`, that is not in the releases and is built from the repository.
The suite builds it from the pinned release tag (BD-022):

```console
uv run kbench install dragonfruit
```

clones `v0.2.2` (commit `188df82`) with its submodules into `work/dragonfruit/<commit>/src`,
checks the commit, and runs only the commands the documentation gives: `npm ci`, `npm run
generate:plugin-registry`, then `cargo build --release` in `rust/dragonfruit-cli`, with compiler
warnings off so that the build log carries no source excerpts. Nothing in the source is opened.
The repository pins its own Rust toolchain (1.97.0 at this tag), which rustup installs.
`dragonfruit-cli` has no version option; the suite reports the tag and commit from the build
record.

**Command** (`src/kbench/slicers.py`), the documented `slice run` options, with the panel taken
from the target:

```console
dragonfruit-cli slice run <model.stl> --output <file>.goo --layer-height 0.05 \
  --build-width-mm 143.43 --build-depth-mm 89.6 --source-width-px 4098 --source-height-px 2560 \
  --anti-aliasing Off
```

- The format follows the output extension (`slice info` lists `.aff`, `.azf`, `.nanodlp`,
  `.ctb`, `.goo` and `.lumen` at this version). The suite uses `.goo`, the format karasu-slicer
  writes for the same Elegoo targets, so both are read by the same UVTools decoder.
- No printer preset is given, so the file declares no mirroring.

**Observed (v0.2.2, `188df82`, 2026-11-17):**

- Its `.goo` files declare the panel given (resolution, 0.035 mm pixels, 0.05 mm layers) and
  `DisplayMirror: None`; the images are the unmirrored top view (`identity`).
- With `--anti-aliasing Off` its `.goo` files still declare `AntiAliasing: 8` (as UVTools reads
  them), and their layers have grey edge pixels: 26 levels, in steps of 255/25, on the 10 mm
  sphere on the Elegoo Mars 5, where 4.1 % of the lit pixels are partial. The binary metrics
  threshold them at 0.5 as they do every slicer's (METRICS.md); `edge_coverage_mae` measures how
  closely they follow the exact coverage.
- The model, centred at the origin, is placed on the panel half a pixel off its centre in X and Y.
- The GOO header carries the creation time (`FileCreateTime`), so two runs never give
  byte-identical files; their decoded layers are identical (BD-024).
- Without the application's job description its `.nanodlp` files declare a layer height and a
  pixel size of 0 (as UVTools reads them), so the suite does not use that format.

## Manual export protocol (slicers without a command line)

CHITUBOX, Lychee, ELEGOO SatelLite, Anycubic Photon Workshop and other slicers that only have a
graphical interface are compared through files an operator exports by hand. They get the same
decoding and metrics; they get no timing, because a stopwatch on an interface is not an
objective measurement.

1. Build the model with the suite: `uv run kbench models build <model id>`. Slice exactly the
   file it writes in `work/models/` (the import checks its SHA-256).
2. In the slicer, choose the printer of the target (`targets/<id>.toml`); note the slicer's
   name and version, and the operating system.
3. Import the STL in millimetres without moving, rotating or scaling it, and centre it on the
   plate if the slicer does not.
4. Use the target's layer height. Turn off supports, raft, hollowing, drain holes, anti-aliasing,
   blur, XY or elephant-foot compensation, and any automatic repair the slicer allows to turn
   off. Leave exposure and motion settings as the slicer's default profile gives them.
5. Export the printer's file and keep it outside the repository.
6. Run, giving every setting that could not be set as step 4 asks in `--note`:

   ```console
   uv run kbench import <file> --slicer <name> --slicer-version <version> \
     --target <target id> --model <model id> --stl work/models/<model id>.stl --note "<deviations>"
   ```

7. Compare with a suite run of the same target and model:
   `uv run kbench report work/runs/<suite run> work/runs/<import run>` writes `comparison.md`.

The import refuses a model file other than the suite's, records the file's SHA-256, the slicer
and version given, the note and the date, and keeps the file in the run directory under
`work/`.
