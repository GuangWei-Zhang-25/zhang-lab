# Spinal cord atlas: anatomical completion v3

This edition completes previously unidentified white matter in the approved smooth, symmetric, CC-centered maps and makes a localized source-reviewed correction where Co1 LSp had included part of the superficial dl tract. All other previously known labels are retained. It contains 71 named anatomical IDs and 908 tissue section–ID occurrences across 34 reference levels. The reconstruction is an explicitly modeled derivative of Allen P56 drawings, supported by a registered published SpinalJ segmentation prior.

Open [index.html](index.html) for the interactive [2D comparison](viewer2d/index.html), [3D volume](viewer3d/index.html), and local adapted NeuroFlow application. The standalone 2D/3D HTML viewers embed compressed labels and open from disk in a modern browser. Use a local HTTP server for the chunked loader.

## Anatomical inventory and remaining uncertainty

The independent audit compared all 947 printed level–ID entries with actual native label maps, the previous symmetric maps, and the volume. It identified 144 missing white-matter assignments: lf, vf and vwc at all 34 levels; cu at 14 levels; dl at 28 levels. The new maps now represent those entries and also recover eligible partial white-matter extents. All 764 previously represented entries remain present, with 1,324 previous known pixels corrected only within the independently reviewed donor/target allowance.

The global palette retains 89 official ontology IDs, each with a unique fixed RGB value. The reference ontology includes semantic aggregates, structures outside the P56 cord scope, and structures not localized on the chosen plates. It does not establish 89 mutually exclusive closed P56 tissue volumes. This edition does not fabricate parcels solely to reach that number.

All 947 printed entries remain in the metadata. Of these, 34 vmf entries describe the ventral median fissure, a cleft/landmark rather than neural parenchyma. Four dorsal-root extents at C3/C6/C7/C8 and the C3 spinal accessory nerve (11n) remain located but unbounded or ambiguous. The C3 nerve has two materially different possible closures; no filled polygon is asserted. Partial source-open gray territories at C1 LatC, C8 7Sp/8Sp, T9 5SpL/5SpM and Co1 LSp remain qualified. See the [coverage audit](audit/README.md).

Unresolved occupied tissue across the high-resolution reference maps decreased from 44.765% to 0.734% (77,924 remaining pixels). Label 65535 is occupied tissue with unresolved identity, shown in gray. Label 0 is outside the tissue envelope. Gray is never silently treated as empty background. Anatomical completeness is not certified: representing a name with an area does not establish every boundary or branch extent.

## How added boundaries were determined

The Allen drawings do not supply separate closed borders for lf, vf and vwc. The SpinalJ dataset supplies a published digitized anatomical prior, not an independent raw Allen contour set. Its matching named reference level is aligned to v2 at CC, with fitted XY scale and one shared regularized semantic deformation based on existing gray labels. Full prior region masks, not distances to text labels, guide competition. Source candidate faces are transported through the existing bilateral alignment. Added identities occupy compatible source-supported unresolved tissue. The CC stays fixed. Previously known labels change only inside the separately reviewed Co1 correction mask.

An additional source-extent review recovered thin DL territories that had been lost during bilateral averaging or clipped by the previous smoothed exterior. Source-drawn superficial contours, explicitly recorded medial closures, and measured ribbon widths guide boundary-relative recovery along the corresponding gray horn. Where a continuous source-supported ribbon requires space outside the previous envelope, only the independently hashed exterior allowance is added: 4,006 high-resolution pixels in total. These are modeled source-supported corrections, with evidence 4; they do not relabel the preserved laminae. The exact masks and native drawing overlays accompany the review manifests.

The vwc cap is constrained by the native gray/white arch and the manually reviewed dorsal endpoint of the ventral median fissure. Its closing edge is explicitly inferred. Ambiguous dorsal white matter uses candidate-compatible published support; any mirrored thin source territory is recorded as inferred. Ineligible or unresolved mixed tissue remains gray.

Each section includes a per-pixel evidence array: 0 outside; 1 retained v2 known assignment; 2 new source-bounded recovery, if used; 3 registered published-prior completion; 4 anatomical modeled boundary or mirrored recovery; 5 still unresolved; 6 a source-reviewed correction of a previously assigned identity. Code 1 means a preserved symmetric derivative, not unchanged raw Allen ground truth. Hovering in the 2D viewer reports this distinction; Show changes isolates additions and corrections.

The previous Co1 source face 26 was assigned entirely to LSp despite continuing into the superficial dl ribbon. The corrected division uses the source contour and an explicitly inferred LSp–dl cutoff, with exact donor/target and allowance-mask records. This corrects the derivative while preserving the original source files.

The left comparison panel is the frozen v2 map. The optional raw drawing is shown through its CC/axis affine; the nonrigid bilateral idealization is not imposed on the drawing. It is a source-context view, not a claim of exact pixel correspondence. Original images, native interpreted masks and v2 maps remain separate and unchanged.

## Reconstruction and geometry checks

The full volume has 795 planes in `[z,y,x]` order, with 5.94µm nominal XY samples and nonuniform Z steps no greater than 40µm. High-resolution reference maps use 2.97µm XY. Co2–Co3 uses 20µm Z sampling to resolve the narrow tract at the surface partition; the remaining intervals use steps no greater than 40µm. All 34 volume anchors are exact every-second samples of their corresponding completed high-resolution maps. C1–C8, T1–T13, L1–L6, S1–S4 and Co1–Co3 retain exact names.

Adjacent anchors use shared regularized semantic registration, ordered nested dorsal laminae, a coupled dorsal-column core/shell, and matched small-region components. The thin dl white-matter tract shares the interpolated gray-matter boundary: its label is the difference between nested gray-plus-dl and gray support domains, rather than an independently translated thin mask. This prevents the cancellations detected in the rejected initial volume. Intermediate anatomy is inferred. All 795 sampled planes have exact bilateral identity symmetry, CC centered at X=Y=0, a connected canal, and no enclosed background holes. No intermediate ID is introduced unless present at an adjacent endpoint. All 1,670 tested common-region/hemisphere paths connect between adjacent anchors, both in the voxel graph and in the actual tetrahedral material partition. The latter check verifies a positive-volume path rather than a corner-only contact. Endpoint-coverage advisories are retained in the continuity report and should not be mistaken for proof that every tiny branch forms one body.

The Blender surfaces use a common tetrahedral material partition. Adjacent regions share identical interface vertices with opposite orientations, so their positive-volume interiors are disjoint under the verified injective map. The exact exported geometry is checked for closed oriented two-manifold boundaries and exact physical anchor reslices. This is a shared-partition and injectivity certificate, not an exhaustive triangle-pair intersection search. Piecewise-linear surfaces do not imply mathematically smooth curvature or anatomical ground truth between reference levels. Small source/digitization components remain quantified rather than being erased to make each ID a single object. In particular, the very thin Co2 DL reference has a sampling-scale interruption of about 6.6µm between high-resolution pixel centers; source review found no additional broad missing sector. Its principal 3D path is connected, and the component audits retain the small fragments explicitly.

The Blender file contains all region meshes. The internal-region render hides lf, vf and unresolved tissue to reveal the actual inner structures; the full named-region and complete-envelope renders are separate. The scientific poster uses the internal render and labels that visibility choice. Categorical colors are fixed, with no generated or painted anatomy.

## Viewing gray and white matter

The 3D viewer provides separate gray-matter, white-matter and all-named-tissue views. Gray matter is the union of 60 existing lamina and nucleus IDs, including the named lamina 9 motoneuron pools, IML and IMM. White matter contains nine existing tract, fasciculus, funiculus and commissure IDs. These are display groups; they do not add an overlapping aggregate parcel, merge anatomical identities, or change any color or voxel. The central canal and dorsal root remain separate structures available in the all-tissue view.

Gray-colored unresolved tissue is a different category from anatomical gray matter. The unresolved-tissue toggle controls that uncertainty label only. The older v2 viewer called this toggle “Gray tissue,” which was misleading. The current viewer names it explicitly and opens with gray matter exposed. The group map and direct per-level coverage audit are provided under `gray_matter_review/`; the full volume retains 31,551,110 gray-matter voxels. Every printed P56 gray parcel has positive support in its matching derived reference and exact volume anchor. This coverage check does not resolve the partially assigned margins listed above.

The 3D renderer uses the same visibility mask for rendering and selection. Its bounded iteration limit covers the entire physical volume diagonal at every quality setting, including end-on views of caudal structures. Gray-only baseline Blender images use the original 60 regional meshes with other objects hidden for display.

## Surface display and resolution options

The 3D viewer now defaults to Smooth categorical surfaces with Balanced quality. Fast preview uses the existing every-second-XY volume; Balanced and High use the identical full label volume. High increases render pixel density and refines ray sampling. All three retain all 795 physical Z planes. Higher display quality does not increase the biological information in the source drawings.

Smooth display interpolates one-hot membership weights for neighboring categorical labels and assigns each point to a single winning identity. Background and hidden labels remain competitors, and the winning identity selects the unchanged palette color. Numeric anatomical IDs are never averaged. This is a shared exclusive display partition, with CPU selection following the same rule; it is a different geometric interpolation from the certified tetrahedral Blender mesh. The Exact voxel boundaries option and the sampled reference inset remain available. The original integer label data are unchanged.

The preview preserves every global ID and every named anchor occurrence, including all 591 printed gray-matter occurrences, but loses 35 tiny region–plane occurrences between anchors and 108 small named anchor fragments. Use the full grid for absence checks and measurements. See the [quality guide](smoothing_review/README.md), [resolution audit](resolution_review/README.md), and [reference integrity check](smoothing_review/reference_immutability.json).

A separate [conservative Blender smoothing variant](smoothing_mesh_review/README.md) applies one injective map to all shared mesh interfaces. All 72 identities and the original mesh connectivity are retained, with measured exported vertex movement below 3.41µm in XY and 7.01µm in Z and the central canal axis fixed. Reslicing the actual exported geometry still reproduces all 34 sampled reference grids exactly. This empirical sampled agreement does not mean continuous contours or mesh volumes are unchanged. Use the exact source for measurements. The Blender derivative and browser categorical interpolation are different surface representations; neither changes the original label volume.

## Data and efficient HTML access

`sections/P56/{level}/labels.uint16.png` and `labels.uint16.bin.gz` contain the same little-endian uint16 labels in C order `[y,x]`. `accepted.labels.uint16.png` is the unchanged v2 comparison map. `evidence.uint8.png` and `.bin.gz` hold evidence codes on the same grid. `section.json` identifies all hashes, transformations, counts and uncertainty.

`volume/labels.npy.gz` is the portable complete integer volume:

```python
import gzip, numpy as np
with gzip.open('volume/labels.npy.gz', 'rb') as f:
    labels = np.load(f)  # uint16[z, y, x], official IDs
```

`volume.json` supplies nominal millimeter coordinates. X increases image-right, Y image-down/ventral, and Z caudally. Use `zCoordinatesMm` for Z; it is nonuniform. Histological deformation, missing serial sections and physical segment boundaries are not independently corrected. End caps outside the first/last reference are computational closures.

The full HTML label payload transfers 2,809,408 compressed bytes; preview transfers 1,240,846. Full decoded storage is 146,191,755 uint8 transport indices. The lookup table recovers the original uint16 IDs losslessly. The chunked API reads 16-plane blocks and retains at most two chunks, about 5.61MiB of voxel buffers.

```js
import {SpinalAtlas} from './browser_data/atlas-loader.mjs';
const atlas = await SpinalAtlas.open(new URL('./browser_data/', location.href));
const c1 = await atlas.level('C1');
const id = await atlas.sampleMm(0, 0, c1.zMm); // CC:3023
```

The local NeuroFlow edition uses the same IDs and exact named anchors. A separate uniform 20µm Z annotation supports its affine reslicer. Its grayscale template is synthetic occupancy, not measured histology. Exact region meshes load only when selected and are released on deselection. The public NeuroFlow website has no custom atlas/SAM importer in the inspected version; this deliverable adapts the local application rather than claiming a supported public upload format.

## Sources and verification

- [Allen Mouse Spinal Cord Atlas](https://mousespinal.brain-map.org/imageseries/showref.html), Allen Institute for Brain Science. [Reference methods and anatomy vocabulary](https://mousespinal.brain-map.org/spinal/common/content/ReferenceAtlas.pdf).
- [SpinalJ atlas dataset v1](https://data.mendeley.com/datasets/4rrggzv5d5/1), DOI 10.17632/4rrggzv5d5.1, CC BY 4.0; [SpinalJ software](https://github.com/felixfiederling/SpinalJ). Registered geometry and boundaries in this derivative are modified. Keep this attribution and evidence description when sharing.
- [NeuroFlow](https://guangweizhang.com/Tools/neuroflow/) application, locally adapted without changing the public site.

Quantitative and visual reports record the actual artifact hashes under `audit/completed_sections_validation/`, `volume/`, `symmetry_review/final_volume/`, `mesh_validation/full_validation/`, browser QA, and `blender/roundtrip_validation.json`. The release archive hashes every packaged file and rechecks decoded integer data and ZIP contents.

Raw integer volume SHA256: `39d8805af268bd55feecfe8d02fe04eda001ac546b6e53d1c057ee70b1143135`.
