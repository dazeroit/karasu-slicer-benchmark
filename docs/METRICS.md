# Metrics

Every metric the suite reports: its definition, unit and sign. A measured layer stack (decoded
from a print file) is compared with the reference stack of the same model, panel and layer
schedule ([METHODOLOGY.md](METHODOLOGY.md#reference)). The code is `src/kbench/metrics/`.

## Conventions

- **Coverage.** A measured pixel's coverage is `grey / 255` for 8-bit images. A reference pixel's
  coverage is the exact fraction of its area covered by the section.
- **Material.** In binary metrics a pixel is material when its coverage is at least 0.5
  (`MATERIAL_THRESHOLD`; grey ≥ 128). A reference pixel at exactly 0.5 (an edge through pixel
  centres) is material too, so a binary slicer that keeps coverage ≥ 0.5 matches it.
- **Canonical frame.** The panel seen from above, +X to the right, +Y towards row 0.
  `dx` is positive towards +X, `dy` towards +Y (the back of the plate).
- **Errors** are measured minus reference.
- **Pitch.** Pixel distances become millimetres with the panel's pitch along each axis.

## Orientation

The stored images are compared with the canonical top view under the eight symmetries of the
square (`identity`, `rotate_90`, `rotate_180`, `rotate_270`, `mirror_x`, `mirror_y`,
`transpose`, `antitranspose`), each naming what turns the canonical image into the stored one.
Only orientations that give the stored image's size are candidates (four on a non-square panel).
For each, the union-of-layers silhouettes are cropped, centred on their centroids and compared
by intersection over union.

| Field | Meaning |
| --- | --- |
| `orientation.stored` | the best candidate |
| `orientation.iou`, `orientation.scores` | its overlap, and every candidate's |
| `orientation.margin` | best overlap minus the second best |
| `orientation.ambiguous` | margin below 0.05: the model is symmetric under some candidate |

## Placement

| Field | Unit | Meaning |
| --- | --- | --- |
| `placement.offset_mm` | mm | `[dx, dy]` that moves the reference onto the measurement: the model's placement error relative to the centre of the panel |
| `placement.offset_px` | px | the same in pixels, `[columns, rows]` (rows grow towards −Y) |
| `placement.centroid_offset_px` | px | the starting estimate from the whole stack's centroids |
| `placement.registration` | | iterations, convergence, and the layers used |

The offset minimises the sum of squared coverage differences on up to 16 layers spread over
the model's height, by Gauss-Newton steps with the reference re-rasterised exactly at each
estimate (translation-only Lucas-Kanade). It starts from the centroid difference. The least-squares
fit balances the misfit of every edge; the centroid alone would mistake an area error that
differs between bodies (or rounding along a single edge) for a displacement. Every shape metric
below is computed after this one translation, applied to the whole stack, so drift between layers
is never absorbed.

## Per-layer metrics

Reported per layer under `layers.<field>` and summarised under `summary.<field>` (count, mean,
minimum, maximum, and the worst layer: lowest `iou`, otherwise largest absolute value).

| Field | Unit | Definition |
| --- | --- | --- |
| `measured_area_mm2` | mm² | sum of coverage × pixel area, in the comparison window |
| `reference_area_mm2` | mm² | the same for the reference: the exact section area |
| `area_error_mm2` | mm² | measured − reference |
| `iou` | ratio | material pixels in both / material pixels in either; `null` when both are empty |
| `xor_area_mm2` | mm² | pixels material in exactly one of the two, × pixel area |
| `boundary_mean_mm`, `boundary_p95_mm`, `boundary_max_mm` | mm | every boundary pixel of either mask (a material pixel with an empty 4-neighbour) gives its distance to the nearest boundary pixel of the other, between pixel centres; mean, 95th percentile and maximum (the Hausdorff distance). Zero for identical masks; `null` when exactly one mask is empty |
| `centroid_dx_mm`, `centroid_dy_mm` | mm | coverage-weighted centroid, measured − reference |
| `width_error_mm`, `depth_error_mm` | mm | extent of the material mask along X and Y, measured − reference |
| `edge_coverage_mae` | ratio | mean absolute coverage difference over pixels that are partial (strictly between 0 and 1) in either image: how well grey levels follow exact coverage. About 0.25 for a binary slicer, near 0 for exact anti-aliasing; `null` when no pixel is partial |
| `stray_area_mm2` | mm² | measured material outside the comparison window (the model's bounds plus 8 pixels) |

**Limits.** Boundary distances are between pixel centres: their resolution is one pixel, and
one-pixel growth gives one pitch. Extents count whole pixels.

## Model metrics

| Field | Unit | Definition |
| --- | --- | --- |
| `volume.measured_mm3` | mm³ | Σ over layers of the measured area on the whole panel × layer height |
| `volume.reference_stack_mm3` | mm³ | Σ of reference areas × layer height (mid-plane rule) |
| `volume.mesh_mm3` | mm³ | the mesh's exact volume |
| `volume.error_vs_reference_mm3`, `_pct` | mm³, % | measured against the reference stack: what slicing should give at this schedule |
| `volume.error_vs_mesh_pct` | % | measured against the mesh: also includes the layer discretisation |
| `height.measured_top_mm` | mm | top of the last layer whose measured area is at least half a pixel |
| `height.error_mm` | mm | measured top − mesh top |
| `height.first_layer`, `last_layer` | index | first and last layers holding material |

## Body metrics

Each pixel of the comparison window belongs to the body whose bounding box is nearest, so a body
that grows or moves keeps all its material. Per body (`bodies[]`):

| Field | Unit | Definition |
| --- | --- | --- |
| `measured_volume_mm3` | mm³ | Σ measured body area × layer height |
| `reference_stack_volume_mm3` | mm³ | Σ exact body section area at mid-planes × layer height |
| `volume_error_pct` | % | measured against reference |
| `z_phase.phase` | layers | where inside each layer the slicer sampled the body: 0 at the layer's bottom, 1 at its top, 0.5 at mid-height |
| `z_phase.area_scale` | ratio | the fitted area scale `s` |
| `z_phase.rms_mm2` | mm² | RMS residual of the fit |
| `z_phase.reason` | | why no phase was fitted, if none was |

**Z phase.** The measured body areas `a_i` are fitted by `s · A(z_i + φ · h_i)`, where `A` is the
body's exact section area, `z_i` and `h_i` the layer's bottom and height, and `s` a free scale,
so that a uniform XY growth does not pass for a Z shift. `φ` is searched from −1 to 2 in steps of
0.05 and refined by a parabola through the best step and its neighbours: −0.5 or 1.5 means a
schedule one layer off. Layers whose candidate planes could reach the body's bottom or top are
left out. Bodies whose area varies by less than 5 % over the fitted layers (prisms, boxes)
get no phase: pixel noise, not geometry, would decide it.

**Limits.** At coarse pixels binarisation noise moves the phase by a few hundredths of a layer
(tests: within 0.08 at 5 pixels per mm). A growth that is not proportional to the area (a fixed
offset of the outline) is only partly absorbed by `s`.
