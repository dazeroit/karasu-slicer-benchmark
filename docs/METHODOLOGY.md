# Methodology

How the suite records the conditions of its measurements. The measurement protocols themselves
(repetitions, statistics, decoding, reference geometry) are added here as they are implemented;
until then [DESIGN.md](DESIGN.md) describes them.

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
| UVtoolsCmd | `KBENCH_UVTOOLSCMD` | yes | `--version`, to be confirmed on the pinned release |
| git | `KBENCH_GIT` | no | `--version` |
| cargo | `KBENCH_CARGO` | no | `--version` |

## External programs

Every external program runs from an argument list, never through a shell, with standard input
closed, both output streams captured and a hard timeout. On POSIX the program starts in its own
session and, at the timeout, its whole process group is killed, so no child keeps running or
holds the output open. A negative exit status means the program was ended by that signal.
