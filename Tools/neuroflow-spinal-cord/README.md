# NeuroFlow 8 · Spinal cord web edition

Open index.html locally, or upload this entire folder to HTTPS static hosting. Keep meshes/, viewer2d/, viewer3d/ and provenance/ together with the HTML.

All 72 region IDs and colors are retained. Display meshes are reduced with quadric edge-collapse simplification to a target of 20,000 triangles per region; small meshes are preserved. These surfaces are display aids and can differ from full-resolution boundaries. Atlas annotations, reference images, coordinates, registration and quantification are unchanged. The original atlas fingerprint identifies the measurement atlas; mesh-manifest.json separately identifies the reduced surfaces.

The full-resolution edition remains in ../spinal-cord-v8/ for separate sharing. Do not mix its mesh files with this edition: the embedded manifests verify payload checksums.

See provenance/atlas-methods.md for scientific provenance and limitations. mesh-report.json records source hashes, bounds and reduction counts. Rebuild with scripts/build-spinal-web.py after building the full edition (Python with numpy and fast-simplification is needed only for building).

## Ready-to-use package

1. Extract `spinal-cord-web.zip`.
2. Open `spinal-cord-web/index.html` in a current Chrome or Edge browser. No installation is required.
3. For online use, upload the contents together to an HTTPS static-hosting directory and link to its `index.html`. Meshes load individually when selected in Visualizer → Structures.
4. Use Save project to retain your images, annotations, alignment and results; use Load project to reopen them.

The web package is about 59 MB unpacked, with about 30 MB of display meshes. The 1.3 GB full-resolution mesh set is separate and is not needed for this edition. Smaller downloads do not change the annotation volume's runtime memory requirements.

Verification covers all seven workflow steps, measurement and coordinate exports, project round-trips, automatic learning, channel selection, TIFF import, both reference viewers, and checksums for all 72 meshes over local-file and HTTP loading. Tests use synthetic data; this is a software-functionality check. See `release-verification.json` and `MANIFEST.json` for the release checks and file hashes.
