# Slicers and readers

How the suite drives each slicer and how it reads their files. Every program here is used as an
ordinary user uses it: its documented command line and the files it writes (AGENTS.md, Clean
room). Observations are dated and name the version.

## karasu-slicer (`karasu-cli`)

The slicer under test, found through `KBENCH_KARASU_CLI` or `PATH` (BD-006). `kbench karasu
build --repo <checkout> --ref <ref>` builds it from a commit: the checkout is only read (`git
archive` into `work/karasu/<commit>/src`), Cargo builds `karasu-cli` with the release profile and
`--locked`, and `build.json` records the commit, the toolchain and the binary's SHA-256. A run
whose karasu-cli comes from such a build records that commit.

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

**Observed (0.2.0-dev, `45bc195`, 2026-11-17)**, on layer images as UVtoolsCmd v7.1.2 extracts
them:

- the `.goo` file for the Elegoo Mars 5 declares `DisplayMirror: Vertically`, and its images are
  the top view mirrored along Y (`mirror_y`);
- the `.pwma` file for the Anycubic Photon Mono 4K declares `DisplayMirror: Horizontally`, and its
  images are also `mirror_y` of the top view. Whether the declaration names the panel's mirror
  or the image's is a convention of the format and the firmware; the suite reports both, and
  does not judge which is right.

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

**Layer schedule.** Layer `i` spans from the previous layer's `PositionZ` (0 for the first) to
its own. Two layers at the same height are refused: the reference has no slab for them.

**Issues** are UVTools' heuristic findings with every detector on: islands, overhangs, resin
traps, suction cups, touching bounds, print height and empty layers. They are reported side by
side across slicers as observations, not as ground truth.

## Other slicers

PrusaSlicer (command line, SL1/SL1S) and the manual protocol for slicers without a command line
are added in phase P3 (DESIGN.md).
