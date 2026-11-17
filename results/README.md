# Published results

Curated summaries of benchmark runs, published by the owner's decision (BD-026). Each campaign
has its own folder, named by date; each summary is a pair of files written by `kbench publish`:

- `<name>.md`: the report's tables (conditions, performance, accuracy, features, side-by-side
  comparisons, file properties, UVTools findings, failures);
- `<name>.json`: the same records as data (`kind: published_summary`).

A campaign's `README.md` gives its scope, its main measured facts and its limits.

## What a summary holds, and what it does not

- Measurements with their conditions: the suite's commit (only committed code is published),
  the host's processor, memory and operating system, every tool's version and SHA-256, the
  karasu-slicer commit, and the SHA-256 of every model and of every manually exported file.
- No local path, host name or user name, no per-layer arrays, and no file written by another
  program: those stay in the work directory of the run, outside the repository.
- No ranking or score: values with their units, as defined in [docs/METRICS.md](../docs/METRICS.md).

## Reading and reproducing

Every value holds for the host, operating system and versions its summary states, and nowhere
else: results taken under WSL are not native Linux or Windows results. To reproduce a summary,
check out the suite at the stated commit, install the same tool versions (`kbench install`,
`kbench karasu build --ref <commit>`), and run the stated suites; files exported by hand from
graphical slicers are reproduced with the manual export protocol (docs/SLICERS.md).

## Campaigns

- [2026-11-17](2026-11-17/README.md): karasu-slicer `45bc195` alone, and beside DragonFruit
  v0.2.2, PrusaSlicer 2.8.1, CHITUBOX 1.4.0 and Lychee 8.0.001, on one WSL2 host.
