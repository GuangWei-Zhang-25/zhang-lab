# AtlasCraft source and reuse

This distribution contains AtlasCraft software and procedural synthetic examples. It does not include original plates or datasets from the Allen Institute, Maryland Sea Grant, SpinalJ, or other third-party atlas providers. No ownership of those resources is claimed.

Users retain the provenance, attribution, licences and reuse conditions of their input sources. Public access to a source, or NIH support for this project, does not itself change a third party's licence. Enter source citations, URLs and licence descriptions in the input manifest; AtlasCraft carries those records into its output metadata. Reconstruction does not grant additional rights over underlying reference materials.

The project owner has not yet designated a software licence for the original AtlasCraft code. This package does not silently apply an open-source licence or represent institutional approval. Choose the applicable software licence before advertising an unrestricted public code release.

The two numerical primitives in `atlascraft/_vendor/` are preserved from the original Atlas Craft local toolkit in this workspace. The generic pipeline wraps those primitives with explicit geometric checks; it does not bundle the entire source-specific spinal reconstruction recipe or claim to reproduce all published experiments.

Runtime dependencies (NumPy, SciPy, Pillow, scikit-image, HTTPX, FastAPI, Uvicorn, python-multipart and NiBabel) are installed separately by Python's package manager. Their own licence notices and conditions remain applicable. The package embeds no external JavaScript libraries, fonts, web services or atlas images in its standalone viewer.
