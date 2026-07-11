# Neuropixels Planner (HTML)

Interactive, zero-install Neuropixels trajectory planner built on the **Allen Mouse
Brain CCFv3** atlas with the **Qiu 2018** live-brain transform. Runs entirely in a
browser from a local file — no server, no install, cross-platform.

## Use
Double-click **`index.html`** (Chrome / Edge / Firefox / Safari).

- **Drag empty space** = orbit · **wheel** = zoom · **Shift-drag** = pan
- **Click the brain** to drop the entry point on the surface
- **Drag the orange tip ball** to aim the probe and set depth in one motion
- **Drag the cyan entry ball** to slide the entry across the surface
- **Depth fine-tune** slider, or the tip drag, set insertion depth

The left panel returns, live, in the chosen coordinate frame (relative to bregma):
Entry AP/ML, Target AP/ML/DV, **target region**, **depth along probe**, **ML tilt**,
**AP tilt**, angle from vertical, plus a plain-language "set the arm" instruction and
the ordered list of brain regions the track passes through (with depth spans).

Region labels use the Allen **316 "summary structures"** (cortical areas, hippocampal
subfields, thalamic / midbrain / hypothalamic nuclei, …), not just coarse divisions.
Only the regions the probe crosses are highlighted; use the **search box** to find and
pin any region, or **Show all region surfaces** to browse the whole set.

## Coordinate frames
- **Qiu2018 in-vivo** (default) — live-brain estimate. Bregma at CCF (AP 5400, DV 440,
  ML 5700 µm), −5° pitch correction, scaling AP×1.031, ML×0.952, DV×0.885.
- **CCF stereotaxic** — raw perfused-atlas → flat-skull (5° pitch, DV×0.9434).

A fresh/reset probe is **stereotaxic-vertical** (reads ~0° on the arm). Numbers are
planning *estimates* — always cross-check against your stereotaxic atlas.

## Files
- `index.html` — the app (inline logic).
- `assets/three.min.js` — 3D engine (three.js r128).
- `assets/ccf_data.js` — embedded, gzipped+base64 Allen CCFv3 meshes (root shell + 316
  summary structures, ~5.8 MB), inflated in-browser via `DecompressionStream`.
- `pack_meshes.py`, `summary_structs.json`, `assets/meshes/` — the structure list,
  source meshes, and the script that builds `ccf_data.js`. Only needed to
  regenerate/retune the structure set; you can delete `assets/meshes/` to save disk
  once `ccf_data.js` is built.

## Regenerate mesh data
```
python pack_meshes.py        # rewrites assets/ccf_data.js from assets/meshes/*.obj
```
`summary_structs.json` is the Allen "Brain – Summary Structures" set (id 167587189).
To use a different/finer set, refetch IDs from the Allen API, download the matching
`.../structure_meshes/{id}.obj` files, and adjust `FINE_GRID` (decimation) in
`pack_meshes.py`. Lower `FINE_GRID` = finer meshes but a larger data file.

Geometry © Allen Institute for Brain Science, CCFv3 (2017).
