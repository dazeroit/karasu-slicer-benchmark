# Campaign 2026-11-17

The first published measurements of karasu-slicer, alone and beside DragonFruit, PrusaSlicer,
CHITUBOX and Lychee. This page gives the scope, the main measured facts and the limits; the
summaries hold every value with its conditions, and [docs/METRICS.md](../../docs/METRICS.md)
defines each metric. Nothing here is a ranking or a score.

## Scope

| | |
| --- | --- |
| Host | AMD Ryzen 7 7700 (8 cores, 16 threads), 15.2 GiB, Ubuntu 24.04.5 LTS under WSL2 (kernel 6.6.87.2-microsoft-standard-WSL2) |
| Slicer under test | karasu-slicer 0.2.0-dev, `karasu-cli` built from commit `45bc195` |
| Compared by command line | DragonFruit v0.2.2 (`dragonfruit-cli` built from tag commit `188df82`, BD-022), PrusaSlicer 2.8.1 (BD-015) |
| Compared by manual export | CHITUBOX 1.4.0 and Lychee 8.0.001, exported by the owner for the Elegoo Mars 5; no timing |
| Reader | UVTools 7.1.2 for every file; SL1 and SL1S layers by the suite's reader (BD-018) |
| Targets | Elegoo Mars 5 (4098 × 2560 px, 35 µm), Anycubic Photon Mono 4K (3840 × 2400 px, 35 µm), Elegoo Mars 4 (8520 × 4320 px, 18 µm), Elegoo Saturn 4 Ultra 16K (15120 × 6230 px, 14 × 19 µm), Prusa SL1S (2560 × 1620 px, 50 µm); 0.05 mm layers |
| Timing | serial, 1 warm-up and 5 timed runs per case, median with minimum, maximum and IQR in the summaries |

| Summary | Runs | Suite commit |
| --- | --- | --- |
| [elegoo-mars-5-four-slicers](elegoo-mars-5-four-slicers.md) | `compare-elegoo` (karasu-slicer and DragonFruit, Mars 5 and Saturn 4 Ultra 16K) and 10 imports of manual exports | `f43da43`, `ea7cf0f` |
| [prusa-sl1s-karasu-prusaslicer](prusa-sl1s-karasu-prusaslicer.md) | `compare-sl1s` | `9797158` |
| [karasu-accuracy](karasu-accuracy.md) | `accuracy` (Mars 5, Photon Mono 4K, Saturn 4 Ultra 16K) | `174aee7` |
| [karasu-scaling](karasu-scaling.md) | `scaling` | `174aee7` |

Every run was made from committed suite code with the same metric definitions (layer stack
schema 2, BD-023).

## karasu-slicer alone

- **Accuracy plate** (five bodies, 5914 triangles): per-layer IoU 0.9998 mean, 0.9997 minimum on
  all three panels; mean boundary distance at most 0.0005 mm; volume −0.093 % against the
  reference on the 35 µm panels and −0.041 % on the 16K panel; no height error.
- **Feature plate**: pins, walls, holes and slots resolved from 0.05 mm, the smallest size of the
  plate, on all three panels.
- **Z sampling**: the sphere's fitted Z phase is 0.500 layers (the middle of the layer).
- **Determinism**: every case wrote byte-identical files across its warm-up and timed runs.
- **Scaling** (wall-clock median): the accuracy plate takes 0.042 s at 4K, 0.048 s at 9K and
  0.047 s at 16K; 1200 layers take 0.063 s. On the 16K panel, spheres of 1280, 20 480, 327 680
  and 1 310 720 triangles take 0.084, 0.112, 0.360 and 1.148 s, with peak memory 20, 22, 111 and
  292 MiB. Restricted to 1, 2, 4 and 8 CPUs, the 327 680-triangle sphere takes 1.141, 0.707,
  0.456 and 0.372 s (0.360 s on all 16), and all 30 runs wrote the same file.
- **SL1S output**: on the SL1S target karasu-cli's peak memory is 107–123 MiB for the small
  models (15–19 MiB for the same models written as `.goo` for the Mars 5), and UVTools 7.1.2
  does not open its `.sl1s` files ("prusaslicer.ini is missing"), so their properties come from
  the suite's reader and they have no UVTools findings.

## Four slicers on the Elegoo Mars 5

Per-layer IoU, mean (minimum):

| Model | karasu-slicer | DragonFruit | CHITUBOX | Lychee |
| --- | --- | --- | --- | --- |
| accuracy-plate | 0.9998 (0.9997) | 0.9942 (0.9933) | 0.9997 (0.9994) | 0.9985 (0.9966) |
| feature-plate | 0.9995 (0.9987) | 0.9592 (0.9144) | 0.9987 (0.9985) | 0.9995 (0.9987) |
| orientation-l | 0.9988 (0.9988) | 0.9998 (0.9998) | 1.0000 (1.0000) | 0.9988 (0.9988) |
| sphere-r10 | 1.0000 (0.9967) | 0.9971 (0.9692) | 1.0000 (0.9994) | 0.9907 (0.3545) |
| cone-r8-h16 | 0.9999 (0.9796) | 0.9828 (0.0000) | 0.9997 (0.9545) | 0.9905 (0.3333) |

Volume against the reference (%):

| Model | karasu-slicer | DragonFruit | CHITUBOX | Lychee |
| --- | --- | --- | --- | --- |
| accuracy-plate | −0.093 | +0.496 | −0.068 | −0.141 |
| feature-plate | +0.043 | +2.014 | +0.214 | +0.043 |
| orientation-l | −0.001 | +0.250 | −0.250 | −0.001 |
| sphere-r10 | 0.000 | +0.198 | +0.003 | −0.001 |
| cone-r8-h16 | +0.001 | +0.353 | +0.006 | −0.280 |

Minimum IoU values come from the layers near the cone's apex and the sphere's poles, where a
section covers a few pixels. Every slicer's last lit layer on the cone is one layer below the
apex (height error −0.050 mm), and UVTools reports that empty layer for each.

- **Placement**: the registration finds karasu-slicer's layers within 0.008 mm of the reference;
  DragonFruit's and CHITUBOX's 0.010–0.021 mm off in X and Y, about half a pixel; Lychee's
  −0.062 to −0.070 mm in X, about two pixels.
- **Z sampling**: the sphere's Z phase is 0.500 layers for karasu-slicer, DragonFruit and
  CHITUBOX, and 0.80 layers for Lychee (accuracy plate and sphere): sections taken higher in the
  layer than the reference's, consistent with its lower minimum IoU near the sphere's poles and
  the cone's apex and with its −0.280 % volume on the cone.
- **Outlines**: DragonFruit's outline offset is +0.004 to +0.027 mm on every body (karasu-slicer
  and CHITUBOX: −0.012 to +0.012 mm); its holes stay open from 0.20 mm (the others from
  0.05 mm), and UVTools reports 177 islands on its feature plate (none for the others).
- **Lychee and karasu-slicer** give the same metrics on the prismatic models (feature plate and
  L), apart from the placement and from rounding below 10⁻¹².
- **Declared anti-aliasing and mirroring**: karasu-slicer 1, `Vertically` (images `mirror_y`);
  DragonFruit 8, `None` (`identity`), with grey edges although `--anti-aliasing Off` was given
  ([docs/SLICERS.md](../../docs/SLICERS.md)); CHITUBOX 4, `Horizontally` (`mirror_x`), binary images; Lychee 8,
  `Vertically` (`mirror_y`), binary images.

## karasu-slicer and DragonFruit: time, memory and size

Wall-clock median (s) and peak memory (MiB), both writing `.goo`:

| Case | Triangles | karasu-slicer | DragonFruit |
| --- | --- | --- | --- |
| orientation-l, Mars 5 | 20 | 0.024 s, 15.0 MiB | 0.256 s, 8.7 MiB |
| cube-20, Mars 5 | 12 | 0.040 s, 15.2 MiB | 0.256 s, 18.5 MiB |
| cone-r8-h16, Mars 5 | 254 | 0.092 s, 16.2 MiB | 0.256 s, 13.9 MiB |
| cylinder-r5-n512, Mars 5 | 2044 | 0.082 s, 16.4 MiB | 0.257 s, 12.6 MiB |
| feature-plate, Mars 5 | 3488 | 0.036 s, 19.0 MiB | 0.257 s, 26.8 MiB |
| accuracy-plate, Mars 5 | 5914 | 0.040 s, 15.9 MiB | 0.258 s, 23.8 MiB |
| sphere-r10, Mars 5 | 20 480 | 0.082 s, 18.1 MiB | 0.259 s, 26.9 MiB |
| sphere-r20-s7, Mars 5 | 327 680 | 0.356 s, 84.4 MiB | 0.815 s, 120.9 MiB |
| sphere-r20-s8, Mars 5 | 1 310 720 | 1.203 s, 291.1 MiB | 0.910 s, 243.9 MiB |
| accuracy-plate, Saturn 4 Ultra 16K | 5914 | 0.049 s, 18.2 MiB | 0.514 s, 41.1 MiB |
| sphere-r20-s8, Saturn 4 Ultra 16K | 1 310 720 | 1.265 s, 292.1 MiB | 2.961 s, 277.1 MiB |

- DragonFruit takes at least 0.256 s on this host, whatever the model.
- DragonFruit's files are 2.3 to 8.0 times larger than karasu-slicer's.
- DragonFruit's files differ between runs (creation time in the header); their decoded layers
  are identical (BD-024).

## karasu-slicer and PrusaSlicer on the Prusa SL1S

Both write `.sl1s` for the same panel, without supports or anti-aliasing ([docs/SLICERS.md](../../docs/SLICERS.md)).

| Case | Triangles | karasu-slicer | PrusaSlicer |
| --- | --- | --- | --- |
| orientation-l | 20 | 0.092 s, 107.5 MiB | 0.151 s, 76.4 MiB |
| feature-plate | 3488 | 0.095 s, 122.9 MiB | 0.242 s, 88.8 MiB |
| accuracy-plate | 5914 | 0.157 s, 120.0 MiB | 0.289 s, 145.2 MiB |
| cube-20 | 12 | 0.199 s, 116.9 MiB | 0.400 s, 132.2 MiB |
| cylinder-r5-n512 | 2044 | 0.255 s, 120.1 MiB | 0.312 s, 173.9 MiB |
| cone-r8-h16 | 254 | 0.263 s, 116.9 MiB | 0.361 s, 136.8 MiB |
| sphere-r10 | 20 480 | 0.248 s, 120.6 MiB | 0.551 s, 154.4 MiB |
| sphere-r20-s7 | 327 680 | 0.620 s, 203.3 MiB | 2.035 s, 377.9 MiB |
| sphere-r20-s8 | 1 310 720 | 1.459 s, 323.4 MiB | 7.004 s, 797.1 MiB |

- PrusaSlicer's wall time is 1.22 to 4.80 times karasu-slicer's; its files are 9.5 to 68 times
  smaller.
- Accuracy: per-layer IoU mean ≥ 0.9998 for both on the accuracy plate, cube, cylinder, sphere
  and L, with volume errors within 0.05 %. On the feature plate, karasu-slicer has IoU 0.9878
  mean and volume −0.148 %, PrusaSlicer 0.9726 and +0.572 %; both resolve pins, holes and slots
  from 0.10 mm, PrusaSlicer walls from 0.05 mm and karasu-slicer from 0.10 mm.
- Cone apex: karasu-slicer lights 4 pixels (0.010 mm²) on the next-to-last layer, where the exact
  section is 0.0044 mm² and no pixel is half covered: that layer's IoU is 0 and the height error
  −0.050 mm. PrusaSlicer leaves it empty: height error −0.100 mm.
- PrusaSlicer's files differ between runs (creation time in `config.ini`); their layers are
  identical.

## Limits

- One host, under WSL2: these are not native Linux or Windows results, and they say nothing of
  other processors.
- The manual exports carry no timing, and only the settings their operator could set: CHITUBOX
  and Lychee declare anti-aliasing (4 and 8) although their images are binary, and the models
  were placed by the operator, so their placement offsets measure the export as much as the
  slicer.
- DragonFruit is its command line built from the v0.2.2 tag, not its released desktop
  application, and its files carry grey edges although anti-aliasing was turned off.
- UVTools findings are heuristics, reported as observations, not as ground truth.
- Each value holds for the version and commit stated; karasu-slicer changes after `45bc195` are
  not measured here.
