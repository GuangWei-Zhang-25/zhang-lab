"""AtlasCraft command line entry points."""
import argparse
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog='atlascraft', description='Curated 2D atlas references to an audited interactive 3D atlas.')
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve', help='Open the local AtlasCraft application')
    serve.add_argument('--port', type=int, default=8766)
    serve.add_argument('--runs', default='runs')
    serve.add_argument('--no-browser', action='store_true')
    demo = sub.add_parser('demo', help='Build the synthetic demonstration without an API token')
    demo.add_argument('--output', default='AtlasCraft_Demo')
    example = sub.add_parser('example', help='Write an editable manifest and curated PNG example')
    example.add_argument('--output', default='AtlasCraft_Input_Example')
    run = sub.add_parser('run', help='Reconstruct a JSON/ZIP input')
    run.add_argument('input')
    run.add_argument('--output', required=True)
    run.add_argument('--agent', action='store_true', help='Use API credentials from ATLASCRAFT_* environment variables')
    run.add_argument('--alignment', choices=['rigid', 'translation', 'none'], default='rigid')
    run.add_argument('--interpolation', choices=['shared_warp', 'signed_distance'], default='shared_warp')
    run.add_argument('--subdivisions', type=int, default=4)
    args = parser.parse_args(argv)
    if args.command == 'serve':
        import uvicorn
        from .server import create_app
        if not 1024 <= args.port <= 65535:
            parser.error('Choose a port from 1024 to 65535.')
        if not args.no_browser:
            import threading
            import webbrowser
            threading.Timer(1.0, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
        print(f'AtlasCraft: http://127.0.0.1:{args.port} — leave this window open.')
        uvicorn.run(create_app(args.runs), host='127.0.0.1', port=args.port, access_log=False)
        return
    if args.command == 'example':
        from .demo import write_demo
        print(write_demo(args.output).resolve())
        return
    from .pipeline import run_pipeline
    provider = None
    if args.command == 'demo':
        from .demo import demo_manifest
        source, options = demo_manifest(), {'subdivisions': 4}
    else:
        source = args.input
        options = {'alignment': args.alignment, 'interpolation': args.interpolation, 'subdivisions': args.subdivisions}
        if args.agent:
            from .agent import ProviderConfig, HTTPProvider
            provider = HTTPProvider(ProviderConfig(
                base_url=os.environ.get('ATLASCRAFT_API_BASE_URL', ''), model=os.environ.get('ATLASCRAFT_MODEL', ''),
                api_key=os.environ.get('ATLASCRAFT_API_KEY', ''), api_style=os.environ.get('ATLASCRAFT_API_STYLE', 'responses')))
    try:
        result = run_pipeline(source, args.output, options=options, provider=provider,
                              progress=lambda stage, message: print(f'[{stage}] {message}', flush=True))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'AtlasCraft could not complete the input: {exc}\n')
    finally:
        if provider is not None:
            provider.close()


if __name__ == '__main__':
    main()
