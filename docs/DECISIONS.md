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

## Open questions

Each is answered by a later `BD` record. Until then, the suite assumes the default given.

| Question | Default assumed |
| --- | --- |
| Initial benchmark targets | Prusa SL1S (common ground with PrusaSlicer), a 4K catalog printer with verified orientation, the Anycubic Photon P1, a 16K printer |
| GUI slicers for manual campaigns | none until the owner names them |
| Publication of results | nothing published; results stay under `work/` |
| Building karasu-cli from a git ref | allowed, by `git archive` export into `work/`, never writing to the karasu-slicer checkout |
| Hosting, remote and CI service | local repository only; the GitHub Actions workflow is ready for when it is hosted |
