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

## BD-007: NumPy and SciPy as run-time dependencies

2026-11-17. The reference rasterizer and the metrics work on arrays of millions of pixels per
layer; the standard library has no array type.

| | NumPy | SciPy |
| --- | --- | --- |
| Purpose | arrays, vectorised geometry and rasterization | exact Euclidean distance transforms and morphology (`scipy.ndimage`) for boundary distances; `scipy.spatial` in tests |
| Licence | BSD-3-Clause | BSD-3-Clause |
| Native code | compiled C (wheels for Linux and Windows) | compiled C, C++ and Fortran (wheels for Linux and Windows) |
| Maintenance | the reference array library of scientific Python, regular releases | likewise |
| Why not the standard library | no arrays | an exact distance transform written in Python loops would take minutes per stack |

Exact versions and hashes are pinned in `uv.lock`.

## BD-008: Reference sampled at the mid-plane of each layer

2026-11-17. A layer's reference is the exact section at the slab's mid-height, rasterised as exact
pixel coverage (METHODOLOGY.md, Reference). A vertex on the plane counts as above it; a face in
the plane is refused rather than resolved by a guess. Where a slicer samples elsewhere in the
layer, the per-layer metrics show it as a shape error and the Z-phase metric measures it.

## BD-009: Placement registered by least squares, not by centroid

2026-11-17. The placement offset is the translation minimising the squared coverage differences
on up to 16 layers, starting from the centroid difference (METRICS.md, Placement). The centroid
alone was tried first and rejected: on the accuracy plate, a perfect binary slicer's half-pixel
ties along the edges of two bodies moved the whole-plate centroid by 0.6 pixel, which the
centroid registration reported as a displacement. The least-squares fit balances edge misfits
and recovers the true offset within 0.05 pixel.

## BD-010: Material attributed to the nearest body

2026-11-17. Per-body metrics attribute each pixel of the comparison window to the body whose
bounding box is nearest. A fixed margin around each body was tried first and rejected: a body
that grew or moved beyond the margin lost area, so the body's metrics depended on the margin.

## BD-011: Pinned installs of external tools

2026-11-17. External tools the suite installs are pinned in `tools/pins.toml` by version, URL,
size and SHA-256, and installed by `kbench install <name>` into `work/tools/<name>/<version>/`:
downloaded into a directory of their own, checked before extraction, extracted member by member
with paths confined to the target and symbolic links refused. Tool discovery (BD-006) looks
there after the environment variable and before `PATH`. UVTools is pinned at v7.1.2, Linux x64
portable build, with the digest the GitHub release lists; the release is more than two weeks
old.

## BD-012: Pillow as a run-time dependency

2026-11-17. Decoded layers are PNG files. Pillow reads them into NumPy arrays.

| | Pillow |
| --- | --- |
| Licence | MIT-CMU (HPND) |
| Native code | compiled C image codecs (wheels for Linux and Windows) |
| Maintenance | the standard Python imaging library, regular releases |
| Why not the standard library | it reads no PNG |

## BD-013: Target panels from published specifications

2026-11-17. A target's panel (resolution and pixel pitch) comes from the manufacturer's
published specification, cited in the target file with the date and how it was retrieved, never
from a slicer's catalog: the panel is the frame the files are measured in, so it must not come
from the program under test. Each run checks what the file declares against it.

## BD-014: Timing before analysis, statistics over every sample

2026-11-17. A run times every case before decoding or analysing anything, and keeps every sample
(METHODOLOGY.md, Timing protocol). Warm-up runs are recorded and flagged but not in the
statistics; failed runs are recorded and counted but not in the statistics.

## BD-015: PrusaSlicer 2.8.1 AppImage on Linux

2026-11-17, owner. PrusaSlicer's GitHub releases carry a Linux build up to 2.8.1 (AppImage,
September 2024); later releases are on Flathub for Linux. The suite pins the 2.8.1 "newer
distros" AppImage, unpacked with its own `--appimage-extract` so runs need no FUSE mount and
timing does not include mounting. GitHub lists no digest for this asset, so the SHA-256 was
computed at the first download and pinned. The build needs the system libraries
`libwebkit2gtk-4.1`, `libsoup-3.0` and `libjavascriptcoregtk-4.1`; the owner installs them
(`sudo apt install libwebkit2gtk-4.1-0` on Ubuntu 24.04).

## BD-016: Timed runs started by a small launcher

2026-11-17. The first performance runs reported the same peak memory, 842.6 MiB, for every case,
from a 5,914-triangle plate to a 1.3-million-triangle sphere. A check showed why: Linux carries a
process's resident-memory high-water mark across `exec`, so `/bin/true` started by the suite's
Python process after it held 600 MiB reported 632 MiB, and only 5.4 MiB when started by a fresh
small interpreter. Timed runs are therefore started by a separate launcher
(`timer_helper.py`) that forks and execs the program itself; each run records the launcher's
floor. GNU `time` has a lower floor (about 1.3 MiB) but reports times to the hundredth of a
second, too coarse for runs of a few hundredths; the launcher keeps microsecond CPU times.
Records made before this decision report wrong peaks and are not used.

## BD-017: The SL1S target panel, given identically to both slicers

2026-11-17. Prusa publishes the SL1S SPEED's LCD resolution (2560 × 1620 px) and print volume
(127 × 80 × 150 mm) but no pixel pitch; third-party tables give 0.049 and 0.05 mm. The target
uses 0.05 mm square pixels: a 128 × 81 mm panel that holds the published print area.

A first version took the print volume as the panel (127 × 80 mm, pixels of 0.0496 × 0.0494 mm)
and was rejected after two observations with a 20 mm cube:

- PrusaSlicer 2.8.1 in portrait orientation, which the SL1S format stores, rasterises each plate
  axis with the other axis's pitch: with non-square pixels the cube came out 405 × 403 px and
  5.5 px off centre; with 0.05 mm square pixels it is 400 × 400 px and centred.
- karasu-slicer's profile had been written with the panel resolution in plate order; its
  documentation says that with `swap_xy` the resolution is in panel order (1620 × 2560). Written
  that way, the cube is 400 × 400 px and centred too.

karasu-slicer has no SL1S in its catalog, so the suite gives it printer and resin profiles of its
own (`targets/profiles/karasu/`); PrusaSlicer gets the same panel through its documented display
options, without any of its presets. Both slicers are told exactly the same panel; the comparison
measures how each rasterises the same geometry on it.

## BD-018: The suite reads SL1 and SL1S archives itself

2026-11-17. UVTools v7.1.2 refuses karasu-slicer's `.sl1s` files ("Malformed file:
prusaslicer.ini is missing"); it reads PrusaSlicer's, which hold that file. An SL1 archive is a
ZIP of one PNG per layer and a `config.ini`, which the suite reads as data (`src/kbench/sl1.py`).
To keep one decoder per format for every slicer, the suite decodes the layers of every SL1 and
SL1S file itself, whichever slicer wrote it, and still asks UVTools for the properties and issues
of each file, recording its refusals. For SL1 files the suite also hashes the layer images alone,
because PrusaSlicer writes the creation time into `config.ini` and its files are never
byte-identical.

## BD-019: HTML report charts

2026-11-17. The HTML report draws its charts as inline SVG with a small script for tooltips, no
chart library. Series take the slots of the reference categorical palette in a fixed order, the
order in which slicers first appear in the report, so a slicer keeps its colour on every chart.

- **Line charts** show up to four series. The first four slots pass the palette validator on
  adjacent pairs in light and dark mode (CVD ΔE ≥ 8.4, normal-vision ΔE ≥ 19.8). Their fourth
  slot (yellow) and second (orange) are close for colour-blind readers, so every line of a chart
  with two or more series also carries a direct label, in the right margin, joined to the line's
  end by a leader; labels are spaced so they never overlap where lines converge.
- **The wall-time dot plot** sets every series against every other on the same row, which only
  the first three slots pass (all pairs: CVD ΔE ≥ 9.2, normal-vision ΔE ≥ 20.9); it shows three.
- In light mode the third and fourth colours are below 3:1 against the surface: every chart keeps
  its legend and direct labels, and every value is in a table.

Slicers beyond those limits are in the tables only, and the page says so. Wall time across cases
spans three decades, so it is a dot plot on a logarithmic axis rather than bars, which must start
at zero.

## BD-020: CPU affinity as the thread-count control

2026-11-17. karasu-cli has no thread-count option, and `RAYON_NUM_THREADS` does not change the
thread count its log reports (observed with 0.2.0-dev at `45bc195`). Restricting its CPU
affinity does: with one CPU its log reports one thread, with four CPUs four, and its output is
byte-identical. The suite therefore controls thread counts at the operating-system level
(`cpus` in suite cases, applied by the launcher), which works for any program that sizes its
pool to its usable CPUs and needs nothing from the program.

## BD-021: Fine features measured by area and enclosure

2026-11-17. Pins and walls are measured by their printed area (equivalent diameter, area over
length), slots by the uncovered area of a band away from the slot's ends, and holes by the empty
pixels their material encloses. Area measures use every pixel's coverage, so anti-aliasing
counts; the hole measure is binary because an enclosed region is binary. Fit-based measures
(circle fits on contours) were not used: on features of a few pixels they have no stable
solution.

## BD-022: DragonFruit built from its pinned source

2026-11-17, owner. DragonFruit's command line is documented but not released; the owner chose to
build it from the pinned release tag (v0.2.2, `188df82`) rather than to use only its desktop
application through the manual protocol. The source is cloned into `work/` (never committed)
and only the build commands its documentation gives are run (`tools/sources.toml`,
`src/kbench/source_build.py`); nobody opens or searches the source, and compiler warnings are
off so the build log quotes none of it. The repository records only how the command line is used
and what its files contain, as for every compared slicer. `kbench install dragonfruit` builds it;
the inventory names it by tag and commit from the build record.

## BD-023: Z phase fitted with an outline offset

2026-11-17, owner. The Z phase was fitted with a free area scale, `s · A(z + φh)`. DragonFruit's
files then gave a phase of 0.05 on the cone and 0.50 on the sphere: its outlines lie about half
a pixel outside the exact ones, and on a cone an outline offset and a Z shift add the same area
(both proportional to the perimeter), which a scale cannot absorb, so the fit took the offset for
a Z shift. The phase is now fitted with an outline offset, `A(z + φh) + g · P(z + φh)`, and is
reported only where its effect on the area is not proportional to the perimeter (spheres, not
cones). The outline offset `g` becomes a metric of its own: the average distance between the
printed and the exact outline. The stack-metrics schema goes to version 2; records of version 1
carry `area_scale` and are not comparable on this metric.

## BD-024: Determinism judged on decoded layers

2026-11-17. Byte-identical files prove determinism, but differing bytes do not disprove it:
PrusaSlicer writes a creation time into `config.ini` and DragonFruit into the GOO header
(`FileCreateTime`, observed with v0.2.2). When the runs of a case write differing files, the
suite keeps up to two of them besides the print file and, after analysing the print file, decodes
them the same way and compares their pixels; the report gives the number of distinct decoded
layer sets.

## BD-025: The selected karasu-cli build

2026-11-17, owner. karasu-cli is found without an environment variable: `kbench karasu build`
writes the commit it built (or found already built) into `work/karasu/selected`, and tool
discovery uses that build after `KBENCH_KARASU_CLI` and before `PATH`. The choice stays explicit,
never "the newest build": with several builds in `work/karasu/` (versions compared for
regressions), the one measured is the one last built or re-selected, and every run records its
commit.

## Open questions

Each is answered by a later `BD` record. Until then, the suite assumes the default given.

| Question | Default assumed |
| --- | --- |
| Initial benchmark targets | Prusa SL1S (common ground with PrusaSlicer), a 4K catalog printer with verified orientation, the Anycubic Photon P1, a 16K printer |
| GUI slicers for manual campaigns | none until the owner names them |
| Publication of results | nothing published; results stay under `work/` |
| Building karasu-cli from a git ref | allowed, by `git archive` export into `work/`, never writing to the karasu-slicer checkout |
| Hosting, remote and CI service | local repository only; the GitHub Actions workflow is ready for when it is hosted |
