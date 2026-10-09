"""Loopback-only application. Model credentials stay in transient process memory."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import secrets
import shutil
import threading
import uuid
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .inputs import MAX_ARCHIVE_BYTES


def create_app(runs_dir='runs'):
    root = Path(runs_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title='AtlasCraft', version='2.0.0', docs_url='/api/docs', redoc_url=None)
    token = secrets.token_urlsafe(32)
    jobs = {}
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='AtlasCraft')
    lock = threading.Lock()
    app.state.jobs = jobs
    app.state.session_token = token

    @app.middleware('http')
    async def local_only(request, call_next):
        host = request.headers.get('host', '').split(':')[0]
        if host not in {'127.0.0.1', 'localhost', 'testserver'}:
            return JSONResponse({'detail': 'AtlasCraft accepts local requests only.'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'Cross-origin requests are not allowed.'}, status_code=403)
        if request.method not in {'GET', 'HEAD'} and not secrets.compare_digest(request.headers.get('x-atlascraft-session', ''), token):
            return JSONResponse({'detail': 'Reload the AtlasCraft page to renew this local session.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.get('/', response_class=HTMLResponse)
    def index():
        html = (Path(__file__).parent / 'static' / 'app.html').read_text()
        return html.replace('__SESSION_TOKEN__', token)

    @app.get('/api/example')
    def example():
        from .demo import demo_manifest
        return JSONResponse(demo_manifest(), headers={'Content-Disposition': 'attachment; filename="AtlasCraft_Input_Example.json"'})

    @app.get('/api/session')
    def local_session():
        return {'session_token': token, 'scope': 'loopback application; X-AtlasCraft-Session header required for writes'}

    @app.get('/api/tools')
    def tools():
        from .pipeline import PIPELINE_TOOLS
        return {'tools': PIPELINE_TOOLS, 'note': 'Use Python run_pipeline(provider=...) to orchestrate these tools. POST /api/jobs starts a complete workflow.'}

    def run_job(ident, source, options, config):
        from .pipeline import run_pipeline
        provider = None
        def progress(stage, detail):
            with lock:
                jobs[ident].update(status='running', stage=stage, detail=detail)
        try:
            if config:
                from .agent import HTTPProvider, ProviderConfig
                provider = HTTPProvider(ProviderConfig(**config))
            result = run_pipeline(source, root / ident / 'result', options=options, provider=provider, progress=progress)
            archive = shutil.make_archive(str(root / ident / 'AtlasCraft_Result'), 'zip', result['output_dir'])
            with lock:
                jobs[ident].update(status='complete', stage='complete', detail='Ready for anatomical review',
                    shape_zyx=result['shape_zyx'], viewer=f'/results/{ident}/viewer.html', download=f'/api/jobs/{ident}/download')
        except ValueError as exc:
            # Input/option validation errors are useful; provider configuration errors are generic.
            message = 'Check the API base URL, model name and connection style.' if config and provider is None else str(exc)[:400]
            with lock:
                jobs[ident].update(status='failed', detail=message)
        except Exception:
            with lock:
                jobs[ident].update(status='failed', detail='The input could not be processed. Check file format, available memory and the input template. No provider response was logged.')
        finally:
            if provider:
                provider.close()
            if config:
                config.clear()

    @app.post('/api/jobs', status_code=202)
    async def create_job(request: Request):
        if int(request.headers.get('content-length', '0')) > MAX_ARCHIVE_BYTES + 65536:
            return JSONResponse({'detail': 'Upload exceeds 256 MB.'}, status_code=413)
        with lock:
            if any(j['status'] in {'queued', 'running'} for j in jobs.values()):
                return JSONResponse({'detail': 'Wait for the current atlas to finish before starting another.'}, status_code=409)
        try:
            form = await request.form(max_files=1, max_fields=4, max_part_size=MAX_ARCHIVE_BYTES)
            options = json.loads(str(form.get('options', '{}')))
            config = json.loads(str(form.get('provider', '{}')))
            if not isinstance(options, dict) or not isinstance(config, dict):
                raise ValueError('Options and provider configuration must be objects.')
            if set(config) - {'base_url', 'model', 'api_key', 'api_style'}:
                raise ValueError('Unsupported provider configuration.')
            ident = str(uuid.uuid4())
            folder = root / ident
            folder.mkdir()
            if str(form.get('demo', 'false')) == 'true':
                from .demo import demo_manifest
                source = demo_manifest()
            else:
                upload = form.get('file')
                if upload is None or not hasattr(upload, 'read'):
                    raise ValueError('Choose a JSON manifest or a ZIP of curated atlas sections.')
                suffix = Path(upload.filename or '').suffix.lower()
                if suffix not in {'.zip', '.json'}:
                    raise ValueError('Upload a .zip or .json file.')
                source = folder / ('input' + suffix)
                count = 0
                with source.open('wb') as handle:
                    while block := await upload.read(1024*1024):
                        count += len(block)
                        if count > MAX_ARCHIVE_BYTES:
                            raise ValueError('Upload exceeds 256 MB.')
                        handle.write(block)
                await upload.close()
            with lock:
                jobs[ident] = {'id': ident, 'status': 'queued', 'stage': 'queued', 'detail': 'Starting AtlasCraft'}
            pool.submit(run_job, ident, source, options, config)
            return {'id': ident, 'status': 'queued'}
        except (ValueError, TypeError):
            # Do not echo request parsing failures; a request may contain a token.
            return JSONResponse({'detail': 'Invalid upload. Use the provided JSON/ZIP template and valid settings.'}, status_code=400)

    @app.get('/api/jobs/{ident}')
    def job_status(ident: str):
        if ident not in jobs:
            return JSONResponse({'detail': 'Job not found.'}, status_code=404)
        with lock:
            return dict(jobs[ident])

    @app.get('/api/jobs/{ident}/download')
    def download(ident: str):
        if ident not in jobs or jobs[ident]['status'] != 'complete':
            return JSONResponse({'detail': 'Result is not ready.'}, status_code=404)
        return FileResponse(root / ident / 'AtlasCraft_Result.zip', filename='AtlasCraft_Result.zip')

    @app.get('/results/{ident}/{filename:path}')
    def result_file(ident: str, filename: str):
        if ident not in jobs or jobs[ident]['status'] != 'complete':
            return JSONResponse({'detail': 'Result is not ready.'}, status_code=404)
        base = (root / ident / 'result').resolve()
        candidate = (base / filename).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            return JSONResponse({'detail': 'File not found.'}, status_code=404)
        return FileResponse(candidate)

    return app
