# Methods and limits

## What the workflow computes

AtlasCraft operates on already curated categorical maps. Boundary extraction follows their contours, and region assignment attaches the human-supplied registry IDs. It does not segment or identify raw histology, infer missing regional names, or determine anatomical orientation from appearance.

For a parallel series, bounded deterministic registration proposes in-plane translation and rotation. Section zero fixes the reference frame. Candidate changes must improve a regularized overlap objective and pass the implemented source-component preservation check. Subsequent correction rounds inspect adjacent-section consistency. Original maps are retained separately: exact reconstruction-anchor fidelity refers to the **aligned** maps, whose raster geometry may differ from the originals.

The reported overlap combines 0.8 times the mean Dice of shared named identities with 0.2 times known-tissue-union Dice. Background 0 and unresolved tissue 65535 are excluded. No shared named identity yields a null score, not evidence of good alignment. Optimizing this geometric score can still produce an anatomically inappropriate placement; inspect the transforms and anchors.

### Interpolation

The default `shared_warp` mode estimates one common displacement field per adjacent pair from shared named labels on a bounded coarse grid. Generic smoothing, displacement limits, boundary tapering and positive partial-map Jacobian checks constrain the candidate. A deformation is used only when its regularized overlap improves; unsafe inverse mapping or lack of a useful deformation triggers signed-distance interpolation. The correction records retain accepted/rejected decisions and fallback reasons.

The shared-map numerical component is adapted from the source workflow identified in the package's attribution records. Source-specific spinal midline/canal constraints, anatomical completion priors and study-specific empirical validation are not automatically transferred to arbitrary inputs.

`signed_distance` directly blends categorical region distance fields between aligned anchors. Interpolated planes are inferred geometry, not observations. The process retains source-supported IDs and distinguishes named tissue from unresolved tissue. Appearance/disappearance of regions, small structures, disconnected components and low-overlap pairs merit particular inspection.

`subdivisions=k` produces `(number_of_sections - 1) * k + 1` planes. Each supplied physical interval is divided separately, so nonuniform section positions remain nonuniform after interpolation. No additional tissue is reconstructed beyond the endpoint interval.

## Reconstruction settings

Set these in the Python `options` dictionary or the local API's `options` form field. The CLI exposes alignment, interpolation and subdivisions; the browser exposes those same choices, with subdivisions limited to 1–16 in its control.

| Setting | Default | Accepted range or values |
| --- | --- | --- |
| `alignment` | `rigid` | `rigid`, `translation`, `none` |
| `interpolation` | `shared_warp` | `shared_warp`, `signed_distance` |
| `subdivisions` | 4 | Integer 1–32 |
| `max_shift_px` | 24 | 0–128 pixels for explicit local settings |
| `max_rotation_deg` | 12 | 0–45 degrees; set to zero outside rigid mode |
| `max_correction_rounds` | 2 | Integer 0–5 deterministic correction rounds |
| `min_overlap_dice` | 0.55 | 0–1 warning threshold |

Agent-proposed retry limits are narrower: 64 pixels and 20 degrees, with at most two retries. Increasing the bounds or subdivisions increases work and may exceed the padded-grid or memory limit. `alignment="none"` disables rigid registration; choose `interpolation="signed_distance"` as well if you want to avoid shared-warp interpolation.

## Multi-plane integration

Each complementary series uses the same parallel-series reconstruction. A reviewed proper rigid 4×4 transform maps that entire series' local coordinates into the common world frame. AtlasCraft does not automatically align coronal, horizontal, sagittal or oblique series to one another.

The fused grid samples reconstructed series with categorical nearest-neighbour sampling. Background gives no non-background support. Matching named labels agree; different named labels conflict. Any source unresolved tissue or a named-label conflict leaves the result at 65535. There is no majority vote that silently assigns an identity to a conflict. The per-series originals, aligned anchors, transforms and QA remain in their respective output folders. Exact aligned-anchor fidelity applies there, not to the resampled fused grid.

The bundled multi-plane demonstration is intentionally contradictory synthetic data. It verifies the mechanics of placement and conflict reporting; it does not validate a biological multi-view reconstruction.

## Output records

| File | Contents |
| --- | --- |
| `viewer.html` | Self-contained offline surface and native-label slice viewer |
| `atlas.npz` | `uint16` labels, `uint8` evidence, exact Z coordinates, XY spacing and origin |
| `original_anchors.npz` | Original categorical maps and input coordinates |
| `aligned_anchors.npz` | Transformed anchor maps and indices in the reconstructed volume |
| `boundaries.json` | Contours and curated IDs in the original input XY frame |
| `source_manifest.json`, `input_hashes.json` | Attribution, input structure and provenance hashes |
| `metadata.json` | Coordinates, options, transforms, per-pair geometry and output provenance |
| `report.json` | Integrity checks, measured geometry, warnings and correction/fallback records |
| `tool_trace.json` | Invoked local operations and their aggregate results |
| `review.json` | Human review checklist; anatomical acceptance initially false |
| `checksums.json` | SHA-256 checksums for exported files |
| `surfaces_preview.ply`, `viewer_summary.json` | Display mesh and its sampling/coverage limits |

Multi-plane outputs additionally contain `series_01/`, `series_02/`, etc., and `crossplane_evidence.npz` with coverage and conflict arrays. The common root has the fused atlas, viewer, report and review record; single-series-only records live inside each series folder.

A single-series `atlas.nii.gz` is exported only when Z spacing is uniform. Its sform stores the user-defined image XYZ coordinates in millimetres, not an automatically established RAS/LPS orientation. Nonuniform coordinates are preserved in NPZ and the viewer. The current multi-plane export provides NPZ rather than a fused NIfTI.

### Evidence values

| Code | Parallel-series output | Fused multi-plane output |
| --- | --- | --- |
| 0 | Background | No non-background source support |
| 1 | Named aligned-anchor tissue | One reconstructed series |
| 2 | Named interpolated tissue | Multiple agreeing reconstructed series |
| 3 | Unresolved aligned-anchor tissue | Conflicting named labels |
| 4 | Unresolved interpolated tissue | Source unresolved tissue without a named-label conflict |

Read each output's `metadata.json` evidence definitions. Coverage of a reconstructed series is not equivalent to a directly observed anatomical section.

## Review and validation scope

The package has automated checks for synthetic geometry, category integrity, aligned anchors, bounded correction decisions, common-frame conflicts, viewer export and mocked provider formats/failures. These checks do not constitute biological validation, a full rerun of the manuscript's original benchmarks or a live-provider compatibility test.

The viewer's surface mesh may be downsampled and may omit structures too small for that preview. Use the full labels and exact coordinates for quantitative work. Display end closures are computational boundaries.

Review source orientation, physical scale, registry consistency, transformed anchors, inferred transitions and unresolved tissue before using an atlas scientifically. You can inspect intermediate files and rerun after manually changing inputs/settings. There is no per-stage interactive approval gate or viewer-based expert sign-off in this release. The output remains `awaiting_human_anatomical_review`; an agent cannot change that into anatomical acceptance.

Original third-party resources retain their attribution and reuse terms. Synthetic examples do not provide a licence for unrelated source anatomy. See [LICENSING.md](../LICENSING.md).
