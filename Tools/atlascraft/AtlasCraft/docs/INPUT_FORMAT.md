# Input format

## One parallel series

An input is a JSON manifest or a ZIP containing **`manifest.json` at its top level** and the referenced section files. A local JSON file may refer to files beneath its own directory. A browser-uploaded JSON should contain inline arrays; use ZIP when it references image files. Inline Python dictionaries also require inline arrays.

```json
{
  "schema": "atlascraft-input-v1",
  "name": "My curated atlas",
  "curated": true,
  "coordinate_system": "Reviewed local image XYZ frame in millimetres",
  "spacing_xy_mm": [0.025, 0.025],
  "labels": [
    {"id": 0, "name": "Outside", "color": "#000000"},
    {"id": 1, "name": "Region A", "color": "#78bbae"},
    {"id": 65535, "name": "Unresolved tissue", "color": "#c6c7cf"}
  ],
  "sections": [
    {"name": "Section 1", "z_mm": 0.0, "file": "sections/001.png"},
    {"name": "Section 2", "z_mm": 0.2, "file": "sections/002.png"}
  ],
  "sources": [
    {"citation": "Your original source citation", "url": "https://example.org/source", "license": "Applicable source terms"}
  ]
}
```

This illustrates the schema; the image files must be supplied. Working inputs are in `examples/`.

| Field | Requirement |
| --- | --- |
| `schema` | Exactly `atlascraft-input-v1` |
| `curated` | `true` after human review of identity, orientation, ordering and scale |
| `name` | Optional, 1–250 characters when supplied |
| `spacing_xy_mm` | Positive finite `[X, Y]` pixel spacing in millimetres |
| `labels` | Unique integer IDs with names; `color` is optional except for RGB import |
| `sections` | 2–128 sections in strictly increasing `z_mm` order |
| `coordinate_system` | Optional description of the user-defined physical frame |
| `sources`, `description` | Optional attribution and descriptive metadata |

Each section has a finite `z_mm`, optional `name`, and exactly one of `file` or `labels`. The latter is a two-dimensional JSON array of integer IDs. Positions may be nonuniform; sections are never silently reordered. Files use relative paths without parent-directory traversal. Absolute paths and ZIP symbolic links are rejected.

### Label images and identity registry

- **NPY:** a two-dimensional integer array, loaded without pickle.
- **Grayscale or indexed PNG/TIFF:** pixel values are label IDs. An indexed PNG's palette appearance does not change its stored IDs. Use a suitable integer format to retain IDs above 255.
- **RGB/RGBA PNG/TIFF:** every RGB colour must exactly match a unique `#RRGGBB` registry colour. RGBA must be fully opaque. Antialiasing and compression-created colours are not interpreted as anatomy.

All sections in a series have the same height, width and XY scale. Supply one image per file; multipage TIFF is not accepted. Every occupied ID other than **0** and **65535** must have a registry name. These two reserved IDs mean outside tissue and unresolved tissue, respectively; names do not change their special handling. At most 256 registry entries are accepted. A human must reconcile the same anatomical identity across sections.

Array order is **`[section, row, column]`**, or ZYX. Before alignment, pixel-centre X increases to the right from zero, Y increases downward from zero, and Z is the supplied `z_mm`. These axes are not automatically assigned anatomical RAS/LPS directions. Alignment may pad the canvas and change its XY origin; use the exported origin and transforms when relating coordinates back to the input.

### Size limits

Section dimensions are 8–2048 pixels per side. The full reconstruction core accepts at most **16,000,000 input label pixels**, **1,000,000 pixels per padded plane** and **32,000,000 output voxels**, subject also to its 768 MB estimated working-memory ceiling. A large allowed side length therefore does not guarantee that a particular stack will fit.

Uploads/ZIPs are limited to 256 MiB, including the expanded ZIP total, with at most 512 archive entries. Crop or explicitly resample the curated maps and update their physical scale before attempting an oversized input. Do not resample categorical IDs with antialiasing.

## Multi-plane series

Use `atlascraft-multiplane-v1` for 2–8 complementary parallel series. Each series is reconstructed independently, then sampled into a supplied common world grid. The example below references two ordinary series manifests:

```json
{
  "schema": "atlascraft-multiplane-v1",
  "name": "My complementary reference series",
  "placements_reviewed": true,
  "world_grid": {
    "shape_zyx": [64, 96, 96],
    "spacing_xyz_mm": [0.025, 0.025, 0.025],
    "origin_xyz_mm": [-0.5, -0.5, 0.0]
  },
  "series": [
    {
      "name": "Series A",
      "input": "series_a/manifest.json",
      "local_to_world": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    },
    {
      "name": "Series B",
      "input": "series_b/manifest.json",
      "local_to_world": [[1,0,0,0],[0,0,-1,1],[0,1,0,0],[0,0,0,1]]
    }
  ]
}
```

These example transforms illustrate syntax, not placement for your specimen. Supply **one proper rigid 4×4 transform per entire series**, shared by all its sections:

```text
[world_x, world_y, world_z, 1]^T
    = local_to_world @ [local_x_mm, local_y_mm, local_z_mm, 1]^T
```

The upper 3×3 block must be orthonormal with determinant +1, and the last row must be `[0,0,0,1]`. Translation is in millimetres; scaling, shear and reflection are not accepted. Section-specific Z positions live inside each series input. For already placed stacks, consider `alignment="none"` so additional in-plane registration does not alter your reviewed placement.

Coronal, horizontal, sagittal or oblique placement is defined by these matrices, not by the series name. AtlasCraft does not estimate the matrices or determine anatomical orientation. All series must use a manually reconciled ID registry; the same ID with different names is rejected.

`input` may instead contain a complete inline single-series manifest. An inline multi-plane dictionary requires inline series inputs and arrays. Multi-plane ZIPs use the same top-level `manifest.json` convention; paths resolve within the archive. Nested multi-plane collections are unsupported.

The world grid uses **ZYX shape** but **XYZ spacing and origin**. Each dimension is 2–2048 voxels and the total is at most 16,777,216 voxels. Categorical nearest-neighbour sampling preserves disagreements as 65535; source unresolved tissue also stays unresolved. Per-series aligned anchors remain available even though common-grid resampling does not preserve those rasters exactly.

`examples/multiplane_inline.json` deliberately places contradictory synthetic series together to exercise conflict reporting. It is a software demonstration, not evidence of biological reconstruction accuracy.
