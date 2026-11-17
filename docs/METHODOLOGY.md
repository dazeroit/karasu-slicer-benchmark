# Methodology

How the suite records the conditions of its measurements and computes its ground truth. Protocols
not implemented yet (repetitions, statistics, decoding) are described in [DESIGN.md](DESIGN.md)
until they are added here. The metrics are defined in [METRICS.md](METRICS.md), the test models
in [MODELS.md](MODELS.md).

## Records

Every record is a JSON object with `schema_version` (an integer, raised whenever a field's
meaning changes or a field is removed) and `kind`. JSON is written with sorted keys, so the same
content gives the same bytes. Times are UTC, ISO 8601, to the second, with a `Z` suffix. A value
that cannot be read on the current platform is `null`, never guessed.

## Environment record

`kbench env --json` prints it; every run will store it. `kind: environment`, schema version 1.

| Field | Meaning | Source |
| --- | --- | --- |
| `captured_at_utc` | when the record was taken | system clock |
| `suite.version` | the suite's package version | installed package metadata |
| `suite.git_commit` | the suite's commit, `null` without a checkout or a commit | `git rev-parse HEAD` |
| `suite.git_dirty` | whether tracked or untracked files differ from the commit | `git status --porcelain` |
| `suite.lockfile_sha256` | SHA-256 of `uv.lock`: the exact Python packages | the file |
| `python.implementation`, `python.version` | the interpreter running the suite | `platform` |
| `os.system`, `os.release`, `os.machine` | kernel name, release and architecture | `platform` |
| `os.distribution` | the operating system's name and version | `/etc/os-release` |
| `os.wsl` | whether Linux runs under Windows Subsystem for Linux | Microsoft in the kernel release, or `WSL_DISTRO_NAME` set |
| `cpu.model` | processor model | `/proc/cpuinfo`, else `platform` |
| `cpu.logical_cpus` | hardware threads of the host | `/proc/cpuinfo`, else `os.cpu_count()` |
| `cpu.usable_cpus` | threads this process may run on (affinity) | `os.sched_getaffinity` |
| `cpu.physical_cores` | distinct (package, core) pairs | `/proc/cpuinfo` |
| `cpu.hypervisor_flag` | the processor's `hypervisor` flag: the system runs under a hypervisor (WSL 2 included) | `/proc/cpuinfo` |
| `cpu.scaling_governor` | frequency governor of CPU 0, `null` where the kernel exposes none (as under WSL) | `/sys/devices/system/cpu/cpu0/cpufreq` |
| `memory.*_kib` | total and available memory, total and free swap, in KiB | `/proc/meminfo` |
| `load_average` | 1, 5 and 15 minute load averages | `os.getloadavg()` |

**Not recorded:** host name, user name, or anything else that identifies a person (BD-005).

**Limits.** The hypervisor flag says that a hypervisor is present, not which one or how much
it interferes; WSL is identified separately. Frequency boost, thermal state, other virtual
machines on the host and Windows-side activity under WSL are not observable from inside and are
not recorded. Results taken under WSL are WSL results, not native Linux or native Windows ones.

## Tool inventory record

`kbench doctor --json` prints it. `kind: tool_inventory`, schema version 1. One entry per tool,
in a fixed order:

| Field | Meaning |
| --- | --- |
| `name`, `role`, `required` | the tool, what the suite uses it for, whether runs need it |
| `env_var` | the variable that names it (BD-006) |
| `status` | `found`, `missing`, or `invalid` (the variable names something unusable) |
| `source` | `env:<variable>` or `PATH` |
| `path`, `resolved_path` | where it was found, and the file after following symbolic links |
| `sha256` | SHA-256 of the resolved file |
| `version` | the first non-blank output line of the version query, when it exits with status 0 |
| `version_probe` | the query's arguments, exit status, timeout flag, start error and first output line |
| `ok` | found, and the version query succeeded |
| `error` | why the tool is not ready |

For a launcher such as a rustup proxy (`cargo`), the hash is the launcher's, and the version is
what the launcher reports for the default toolchain.

`kbench doctor` exits with status 1 when a required tool is not `ok`.

| Tool | Variable | Required | Version query |
| --- | --- | --- | --- |
| karasu-cli | `KBENCH_KARASU_CLI` | yes | `--version` |
| UVtoolsCmd | `KBENCH_UVTOOLSCMD` | yes | `--core-version` (the UVTools release; `--version` gives the front end's own) |
| PrusaSlicer | `KBENCH_PRUSASLICER` | no | `--help`, first line |
| dragonfruit-cli | `KBENCH_DRAGONFRUIT_CLI` | no | `info` must succeed; the version is the tag and commit of the suite's build record |
| npm | `KBENCH_NPM` | no | `--version` |
| git | `KBENCH_GIT` | no | `--version` |
| cargo | `KBENCH_CARGO` | no | `--version` |

## External programs

Every external program runs from an argument list, never through a shell, with standard input
closed, both output streams captured and a hard timeout. On POSIX the program starts in its own
session and, at the timeout, its whole process group is killed, so no child keeps running or
holds the output open. A negative exit status means the program was ended by that signal.

## Reference

The reference is what an exact slicer would put on the panel. It is computed from the model's
mesh as written to STL (`float32` coordinates), never from a slicer's output.

**Layer schedule.** Layer `i` is the slab `[z_bottom, z_bottom + height]`; heights and positions
come from the measured file when it declares them. For a uniform schedule the count is
`ceil(model height / layer height)`, the ratio rounded to nine decimals first so that a height
that is a whole number of layers in decimal does not gain a layer from binary rounding.

**Section.** A layer's reference is the mesh's section by the plane at the slab's mid-height,
the plane that best represents the slab. Each triangle crossing the plane gives one segment,
oriented with the material on its left; segments need no chaining. A vertex exactly on the plane
counts as above it, which makes the section the limit of sections just below the plane: exact
wherever the area is continuous. A face lying in the plane (where the area jumps) is refused as
ambiguous; model dimensions and schedules are chosen so that mid-planes never meet a horizontal
face. Intersection points are interpolated from the lower-index vertex of each edge, so the two
triangles sharing an edge produce the same point.

**Pixel coverage.** The exact covered fraction of every pixel is accumulated from the segments:
each piece of segment inside one pixel adds the signed area between itself and the pixel's right
edge, and its signed height to every pixel further right (a running sum along the row). For
closed loops of winding 0 or 1 this is the exact area up to rounding (well below 1e-9); coverage
outside `[0, 1]` beyond that tolerance means overlapping or inverted solids and is refused. The
rasterizer is checked in the tests against an independent polygon-clipping computation of every
pixel, and its total against the section's shoelace area.

**Panel frame.** The plate origin is the panel centre; the canonical image has `resolution_x`
columns along +X and `resolution_y` rows along −Y (row 0 at the back), so it reads like a view
from above. Pixel `(row, column)` covers `[column, column + 1)` in continuous column units.

**Validation of the metrics.** The tests render synthetic slicer outputs from the reference and
damage them in one known way each: binarised, mirrored, turned, transposed onto the exchanged
panel, shifted, grown by one pixel, missing a layer, sampled at another height in the layer or
one layer off, scaled in XY, with distorted grey levels, or with a stray speck. Each test checks
that the defect is reported by the right metric, with the expected magnitude, and that the other
metrics stay unaffected.

## Runs

`kbench run --suite <name>` runs `suites/<name>.toml` (or a suite file given by path). A suite
names its timing parameters (warm-up runs, timed repetitions, timeout) and its cases: a model,
a target and the slicers. Targets (`targets/<id>.toml`) give the panel (resolution and pixel
pitch along plate X and Y), the layer height, the source of those values, and each slicer's
settings for the printer.

Everything goes into `work/runs/<UTC start>-<suite>/`:

| Path | Content |
| --- | --- |
| `run.json` | `kind: run`: suite and target hashes, tools inventory, environment before and after, the list of case records |
| `models/` | the models built for this run, with their manifest |
| `cases/<case>/<slicer>/case.json` | `kind: case`: every attempt, the performance summary, determinism, the analysis summary |
| `cases/<case>/<slicer>/attempt-NN.stdout`, `.stderr` | each run's output streams |
| `cases/<case>/<slicer>/print.<ext>` | the first successful timed run's print file |
| `cases/<case>/<slicer>/uvtools-*.txt` | UVtoolsCmd's raw outputs |
| `cases/<case>/<slicer>/metrics.json` | `kind: stack_metrics` (METRICS.md) |
| `report.md` | the Markdown report (`kbench report <run dir>` rewrites it) |

**Order.** Models are built first. Then every timed run of every case runs, serially; decoding
and analysis come only after all timing, because they load every core and would disturb the
measurements.

## Timing protocol

- Each case runs `warmup` untimed-for-statistics runs, then `repetitions` timed runs, each into
  a fresh output path. Warm-up runs are recorded like the others and flagged.
- A run is measured from just before the process starts until the kernel reports its exit
  (`os.wait4`): wall time on the monotonic clock (`time.perf_counter_ns`), user and system CPU
  time and peak resident memory (`ru_maxrss`, KiB) of the process. Standard output and error go
  to files, so nothing drains pipes while timing.
- The process is started by a small separate launcher (`src/kbench/timer_helper.py`, a fresh
  interpreter without site packages) that forks, execs and waits for it, not by the suite
  itself: Linux carries the resident-memory high-water mark across `exec`, so a program started
  by the suite's large process would report the suite's memory as its peak (BD-016). The
  launcher's own size is a floor under every reported peak; each run measures it with
  `/bin/true` (`launcher_floor_kib` in `run.json`, and in the report). A peak at the floor means
  "at most the floor".
- A watchdog kills the process's whole group at the suite's timeout; the run is recorded as
  timed out.
- The 1-minute load average and the available memory are recorded before each run. They are not
  used to discard anything; note that the suite's own previous runs raise the load average.
- Statistics are over successful timed runs: count, median, minimum, maximum and the inclusive
  quartile range (`statistics.quantiles(method="inclusive")`), with every sample kept. The IQR
  describes spread; it is not a confidence interval. Results from different hosts are never
  pooled.
- Page cache is warm (the model was just written and read by the warm-up). Cold-cache timing is
  not measured.
- **CPU count.** A suite case may set `cpus = N`: the launcher restricts the program to the first
  N CPUs the suite may use (its CPU affinity, set before `exec`). Programs that size their thread
  pools to the CPUs they may use then run with N threads (karasu-cli reports this in its log),
  without any option of the program itself (BD-020). Cases without `cpus` use every CPU.
- **Determinism:** the SHA-256 of every run's print file, warm-ups included, is recorded; one
  distinct hash means byte-identical files. For SL1 and SL1S archives the layer images are also
  hashed alone (BD-018). When files differ, up to two more are kept and, after the analysis,
  decoded and compared pixel by pixel with the print file (BD-024). Reports compare cases of the
  same model, target and slicer build across CPU counts and runs (*Determinism across cases*).
- A failed run (non-zero exit, signal, timeout, no file) is recorded with its status and kept out
  of the statistics, which say how many runs succeeded.

## Decoding and analysis

The first successful timed run's file is read by UVtools (SLICERS.md): properties, per-layer
positions, issues, and every layer as an 8-bit PNG. The declared resolution, pixel pitch, layer
height and layer count are checked against the target and the model (`conformity` in the case
record). The PNG stack is then measured against the reference (METRICS.md) and deleted unless
`--keep-layers` is given; its metrics stay.

## Reports

`kbench run` writes `report.md` and `report.html` in the run directory; `kbench report <run>
[<run> ...]` rewrites them, or with several runs writes `comparison.md` and `comparison.html` in
the first one with every run's cases side by side. Two measurements of the same case (two
slicers, or two builds of one slicer from two runs) get a change column, second minus first: the
regression view between karasu-slicer versions.

The HTML page holds the same tables under its charts: median wall time per case (logarithmic),
wall time against triangle count for a model family on one target, wall time against CPU count,
and per-layer area error. Charts use the first three categorical colours of a validated palette
(BD-019); identity never rests on colour alone (legend, tables), labels are inserted as text,
and every charted value is also in a table.
