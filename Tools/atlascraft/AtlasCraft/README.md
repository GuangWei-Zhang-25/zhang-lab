# AtlasCraft

AtlasCraft turns **human-curated 2D label maps** into a labelled 3D atlas with an offline viewer and an auditable reconstruction record. It extracts boundaries, attaches your regional identities, aligns parallel sections, interpolates between them and exports the result for anatomical review.

You can run the complete workflow locally without an API key. An optional user-configured agent calls the registered processing tools and can request bounded alignment retries. The agent does not identify anatomy in raw scans or approve the reconstructed anatomy.

## Start the local application

Use Python **3.10 or later**. On macOS, open `Launch_AtlasCraft.command`; on Windows, open `Launch_AtlasCraft.bat`. The first launch creates a local environment and installs dependencies. Later launches reuse it.

To install manually on macOS, Linux or Windows, open a terminal in the extracted AtlasCraft folder and create a virtual environment:

```bash
python3 -m venv .venv
```

On Windows, use `py -3 -m venv .venv` instead. Activate it with `source .venv/bin/activate` on macOS/Linux, or `.venv\Scripts\activate` in Windows Command Prompt. Then:

```bash
python -m pip install .
atlascraft serve
```

The application opens at **http://127.0.0.1:8766**. Leave the terminal open while using it. Choose **Try synthetic example**, or upload your JSON/ZIP input. When processing finishes, open the 3D atlas or download the complete result. `atlascraft serve --port 8767 --runs my_runs --no-browser` changes the port, result location and automatic browser opening. If the default port is occupied, use another port, for example `atlascraft serve --port 8797`.

Dependency installation may require internet access. Reconstruction and the exported viewer work offline after installation; only the optional agent connection needs its configured provider.

## Use one Python call

```python
from atlascraft import build_atlas

result = build_atlas("examples/curated_sections.zip", "My_Python_Atlas")
print(result["viewer"])
```

To enable agent tool orchestration, pass your own `api_token`, `model` and `api_base_url` to this same function. Omit all provider fields for offline operation. See the [API guide](docs/API.md) for the complete call and custom-adapter interface.

## Prepare your references

Supply categorical PNG, TIFF or NPY sections on a common canvas with a common XY pixel scale, an ordered physical Z coordinate for each section and a registry of regional IDs. Flat-colour RGB images require an explicit colour-to-ID registry. Set `curated: true` after reviewing the labels, orientation, ordering and scale. Use **0** for outside tissue and **65535** for unresolved tissue.

Start from `examples/curated_sections/manifest.json`, upload `examples/curated_sections.zip`, or use the self-contained `examples/curated_sections_inline.json`. To create another editable example folder:

```bash
atlascraft example --output My_Input_Example
```

Raw histological images, scanned atlas plates and antialiased drawings need curation into categorical maps before import. See [Input format](docs/INPUT_FORMAT.md) for the exact schema, coordinates and limits.

## Run from the command line

```bash
atlascraft demo --output My_Demo
atlascraft run examples/curated_sections.zip --output My_Atlas
atlascraft run examples/curated_sections_inline.json --output My_Atlas_Unwarped --alignment none --interpolation signed_distance --subdivisions 4
```

Choose a **new output directory** for each run; existing results are not overwritten. `subdivisions=4` inserts three intermediate planes per source interval and retains its endpoints. Defaults are rigid alignment and shared-warp interpolation with geometric checks and a signed-distance fallback.

## Connect your own agent

In the local application, enable **Connect my AI agent API**, choose **OpenAI Responses** or **OpenAI-compatible Chat Completions**, and enter your provider base URL, model name and token. No paid model is selected for you. Your provider must support the selected function-calling format.

For command-line use, set these process environment variables and add `--agent`:

| Variable | Meaning |
| --- | --- |
| `ATLASCRAFT_API_BASE_URL` | API prefix, such as `https://api.openai.com/v1` |
| `ATLASCRAFT_MODEL` | A tool-capable model available in your account |
| `ATLASCRAFT_API_KEY` | Your provider credential; may be empty for an unauthenticated local provider |
| `ATLASCRAFT_API_STYLE` | `responses` (default) or `chat_completions` |

```bash
atlascraft run examples/curated_sections.zip --output My_Agent_Atlas --agent
```

`.env.example` is a template; AtlasCraft does not load `.env` files automatically. Provider settings are held in process memory, and credentials are not written to the result. The built-in orchestration sends static instructions and aggregate geometric results, not images, label names or source text. If a provider fails or stops early, local tools finish the workflow and record the fallback. Check `agent_notes` in `report.json` to see what occurred.

## Inspect and review the result

Open `viewer.html` directly in a modern browser. Rotate, zoom and pan the surface preview; search or isolate regions; inspect orthogonal native-label slices and the reconstruction record. The surface meshes are display previews. Use `atlas.npz` and its physical coordinates for quantitative analysis.

The output also includes original and aligned anchors, extracted boundaries, transforms, correction logs, checksums and `review.json`. Anatomical acceptance starts as **false**. Inspect these records, correct your input maps or settings and run again as needed. The application does not pause for a separate approval at every processing stage or record an expert sign-off through the viewer.

## Combine reference orientations

Coronal, horizontal, sagittal and oblique **series** can share a world grid when you supply and review one rigid 4×4 local-to-world transform per series. Conflicting regional labels remain unresolved; the software does not infer cross-plane anatomical placement.

```bash
atlascraft run examples/multiplane_inline.json --output My_Multiplane_Demo
```

This example intentionally contains contradictory synthetic references to demonstrate conflict reporting. It is not a biological benchmark. See [Input format](docs/INPUT_FORMAT.md#multi-plane-series).

## More information

- [Python and local HTTP API](docs/API.md)
- [Methods, output files and implementation limits](docs/METHODS_AND_LIMITS.md)
- [Licensing and source attribution](LICENSING.md)
- [Editable Figure 1 workflow](figure1/Figure1_AtlasCraft_Workflow_a-h.svg)

The shareable package contains synthetic examples, not bundled source anatomy. Distribute the package as a website download for users to run locally with their own inputs and optional provider account. The loopback application is not a public hosted service. Original third-party atlases remain available from their providers and retain their own terms.
