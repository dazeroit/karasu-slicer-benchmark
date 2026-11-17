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

## Open questions

Each is answered by a later `BD` record. Until then, the suite assumes the default given.

| Question | Default assumed |
| --- | --- |
| Initial benchmark targets | Prusa SL1S (common ground with PrusaSlicer), a 4K catalog printer with verified orientation, the Anycubic Photon P1, a 16K printer |
| GUI slicers for manual campaigns | none until the owner names them |
| Publication of results | nothing published; results stay under `work/` |
| Building karasu-cli from a git ref | allowed, by `git archive` export into `work/`, never writing to the karasu-slicer checkout |
| Hosting, remote and CI service | local repository only; the GitHub Actions workflow is ready for when it is hosted |
