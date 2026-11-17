# Test models

The suite generates every model it slices, from `models/catalog.toml`, so that the exact geometry
behind each print file is known. `kbench models list` lists the catalog; `kbench models build`
writes the STL files and `manifest.json` into `work/models/` (or `--out`).

## Rules every model follows

- **Units and frame:** millimetres, right-handed, Z up.
- **Placement:** the model's bounding box is centred on the origin in X and Y, and its lowest
  point is exactly `z = 0`. Slicers are asked to centre the model on the plate, so the expected
  position is the bounding box centred on the panel.
- **Exact coordinates:** every vertex is a `float32` value, exactly what binary STL stores. The
  reference is computed from these values, not from the ideal shape.
- **Bodies:** a model is one or more bodies, each a closed solid whose triangles are
  counter-clockwise seen from outside (every directed edge used once, its reverse once) with
  positive volume. Bodies are at least 1 mm apart in X or Y (`MIN_BODY_GAP_MM`), so slicer
  rounding cannot bridge them and their material can be attributed to them.
- **Determinism:** the same catalog and generator version give the same bytes. The manifest
  records each file's SHA-256; `GENERATOR_VERSION` is raised whenever a generator, the placement
  rules or the STL writer changes.

## Shapes

| Shape | Parameters | Geometry |
| --- | --- | --- |
| `box` | `size_mm = [x, y, z]` | axis-aligned box |
| `prism` | `radius_mm`, `segments`, `height_mm`, `phase_deg` | regular polygon of circumradius `radius_mm`, first vertex at `phase_deg`, extruded: the faceted cylinder a CAD export produces |
| `cone` | `radius_mm`, `segments`, `height_mm`, `phase_deg` | regular pyramid: the polygon at `z = 0`, apex at `height_mm` |
| `icosphere` | `radius_mm`, `subdivisions` | icosahedron split `subdivisions` times with vertices on the sphere: `20 · 4^subdivisions` triangles |
| `extrusion` | `polygon_mm`, `height_mm` | a simple counter-clockwise polygon, extruded (caps ear-clipped) |

Each body takes `at_mm = [x, y]`, the position of its bounding-box centre before the model is
centred.

## Catalog

| Id | Bodies | Purpose |
| --- | --- | --- |
| `cube-20` | 20 mm cube | flat faces along the panel axes, sharp corners |
| `box-30x10x5` | 30 × 10 × 5 mm box | different X and Y extents |
| `cylinder-r5-n64` | 64-segment prism, r 5, h 10 | coarse facets |
| `cylinder-r5-n512` | 512-segment prism, r 5, h 10 | fine facets |
| `cone-r8-h16` | 128-segment pyramid, r 8, h 16 | area changing with height: Z phase |
| `sphere-r10` | icosphere r 10, 20,480 triangles | curvature in every direction |
| `orientation-l` | chiral L, 2 mm thick | image orientation |
| `accuracy-plate` | cube 10, prism r 4, pyramid r 5 h 10, icosphere r 5, chiral L | one job for the accuracy metrics |
| `sphere-r20-s3` … `s8` | icosphere r 20, 1,280 to 1,310,720 triangles | performance scaling |

The **chiral L** has arms of 20 and 12 mm, 4 mm wide. Its arms differ in length, so each of the
eight flips and quarter turns of the panel gives a different image: the stored orientation of a
layer image can always be identified.

## Manifest

`manifest.json` (`kind: model_manifest`, schema version 1) holds `generator_version`,
`catalog_sha256`, `units` and, per model: `id`, `description`, `stl`, `sha256`,
`triangle_count`, `vertex_count`, `volume_mm3` (exact, from the divergence theorem on the
`float32` mesh), `bounds_mm`, and per body its `name`, `shape`, `first_triangle`,
`triangle_count`, `volume_mm3` and `bounds_mm`. Body triangles are contiguous, in catalog order.
