# Python and local HTTP API

## Python workflow

```python
from atlascraft import build_atlas

result = build_atlas(
    "examples/curated_sections.zip",
    "My_Atlas",
    options={"alignment": "rigid", "interpolation": "shared_warp", "subdivisions": 4},
    progress=lambda stage, detail: print(stage, detail),
)
print(result["viewer"])
```

`build_atlas(source, output_dir, *, api_token=None, model=None, api_base_url=None, api_style="responses", options=None, progress=None)` accepts a JSON/ZIP path or an inline manifest dictionary. It dispatches both input schemas. The destination must not already exist. It returns `name`, `output_dir`, `viewer`, `volume`, `report`, `shape_zyx`, `status` and `agent_used`. The status remains `awaiting_human_anatomical_review` after a successful build.

`agent_used` indicates that a provider was supplied; inspect `report.json` / `metadata.json` `agent_notes` to determine whether the provider completed orchestration or local fallback was used. Multi-plane runs record each series' orchestration in its `series_XX` folder.

## Bring your own provider

```python
from getpass import getpass
from atlascraft import build_atlas

result = build_atlas(
    "examples/curated_sections.zip",
    "My_Agent_Atlas",
    api_token=getpass("Provider API token: "),
    model="YOUR_TOOL_CAPABLE_MODEL",
    api_base_url="https://api.openai.com/v1",
    api_style="responses",
)
```

The helper creates and closes the provider for you. Omit all three of `api_token`, `model` and `api_base_url` for offline processing. Supplying any of them enables provider setup and requires both a model and base URL; an empty token supports an unauthenticated local provider. Replace the endpoint and model with your own provider settings. `api_style` is `responses` or `chat_completions`. A matching full endpoint is also accepted. HTTPS is required except for loopback HTTP; query strings, URL credentials and fragments are rejected. The key is carried in the Authorization header, excluded from configuration repr, and never written into pipeline artifacts. Do not serialize the configuration object into your own logs or result files.

No provider account, model access or live connection is verified by the package's mocked-provider tests.

The adapters follow the [official function-calling formats](https://developers.openai.com/api/docs/guides/function-calling). Select the format supported by your chosen model; Responses and Chat Completions support is not interchangeable for every model.

### Registered processing tools

The agent calls these local operations through a maximum 12-turn loop per parallel series:

1. `validate_curated_references`
2. `extract_boundaries_and_assign_regions`
3. `align_interpolate_reconstruct`
4. `inspect_geometric_quality`
5. Optional `retry_alignment`, then quality inspection
6. `export_atlas_and_viewer`

The local session enforces dependencies and rejects unregistered actions. Only `retry_alignment` takes arguments: integer `max_shift_px` from 0–64 and numeric `max_rotation_deg` from 0–20. At most two agent retries are allowed; a candidate replaces the current reconstruction only when its comparable mean geometric overlap improves. Other tools have empty argument objects. Neither tools nor agent assign new anatomical identities or approve output anatomy.

The built-in loop shares static instructions and numeric/boolean aggregate tool results. Images, label names, source descriptions, file paths and credentials are not placed in model messages. Provider failures or an incomplete loop lead to local deterministic completion with a recorded fallback.

### Custom Python adapters

For extension code, `run_pipeline(source, output_dir, *, options=None, provider=None, progress=None)` accepts a custom provider object. The simple `build_atlas` helper wraps this same workflow.

The built-in adapter is `HTTPProvider(ProviderConfig(base_url, model, api_key="", api_style="responses", timeout_seconds=30), client=None)` in `atlascraft.agent`. It makes one request per turn, with redirects and automatic retries disabled. An injected `httpx.Client` remains caller-owned; `close()` or a context manager closes a managed client. Use this lower-level interface to set a timeout or inject a transport.

Implement `AgentProvider.complete(messages, tools)` from `atlascraft.agent`. `tools` uses Chat Completions function schemas. Return a normalized assistant message, for example:

```python
{
    "role": "assistant",
    "content": None,
    "tool_calls": [{
        "id": "call_1",
        "type": "function",
        "function": {"name": "validate_curated_references", "arguments": "{}"}
    }]
}
```

Return an empty `tool_calls` list to stop. Custom adapters are trusted local Python code; maintain the same data boundary. The built-in HTTP adapter normalizes both remote formats and validates registered calls before returning them. Responses reasoning continuation is retained privately in memory.

`agent_review(provider, qa_summary)` is a separate optional recommendation helper using `ReviewProvider.review(summary)`. It returns `action` (`accept`, `retry_alignment` or `flag_review`), `reason` and bounded `parameters`. It does not execute a reconstruction or establish anatomical acceptance. The main pipeline uses the processing-tool loop above.

## Local HTTP API

Start `atlascraft serve`. Interactive route documentation is at `/api/docs`. The service binds to loopback; it is intended for a local browser or local client, not a public deployment.

| Method and route | Purpose |
| --- | --- |
| `GET /api/session` | Get the transient `session_token` |
| `GET /api/example` | Download an inline synthetic input |
| `GET /api/tools` | Read registered tool schemas; does not execute a tool |
| `POST /api/jobs` | Queue one complete workflow using multipart form data |
| `GET /api/jobs/{id}` | Poll status and progress |
| `GET /api/jobs/{id}/download` | Download the completed result ZIP |
| `GET /results/{id}/viewer.html` | Open the completed viewer |

Writes require the `X-AtlasCraft-Session` header from `/api/session`. Cross-origin requests are rejected. The following local example runs without a provider:

```python
import json
import time
import httpx

with httpx.Client(base_url="http://127.0.0.1:8766", timeout=60) as client:
    token = client.get("/api/session").json()["session_token"]
    with open("examples/curated_sections.zip", "rb") as handle:
        response = client.post(
            "/api/jobs",
            headers={"X-AtlasCraft-Session": token},
            files={"file": ("curated_sections.zip", handle, "application/zip")},
            data={"options": json.dumps({"subdivisions": 4})},
        )
    response.raise_for_status()
    job_id = response.json()["id"]
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"complete", "failed"}:
            break
        time.sleep(1)
    if job["status"] == "complete":
        archive = client.get(job["download"])
        archive.raise_for_status()
        with open("AtlasCraft_Result.zip", "wb") as handle:
            handle.write(archive.content)
    else:
        print(job["detail"])
```

Multipart fields are `file` (JSON/ZIP), `options` (JSON object), optional `provider` (JSON object with `base_url`, `model`, `api_key`, `api_style`), or `demo=true` instead of a file. The API does not accept a bare JSON request body for `/api/jobs`. One queued/running job is allowed; another submission returns 409. Invalid uploads return 400, oversized requests may return 413, and missing/not-ready results return 404. Job state and session tokens last for the server process; saved result directories persist on disk.
