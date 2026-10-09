"""Example: call AtlasCraft as a function, with an optional user-provided API token."""
from pathlib import Path
import os
from atlascraft import run_pipeline
from atlascraft.agent import HTTPProvider, ProviderConfig

source = Path(__file__).parent / 'curated_sections' / 'manifest.json'
output = Path.cwd() / 'My_AtlasCraft_Result'
if os.environ.get('ATLASCRAFT_API_BASE_URL'):
    with HTTPProvider(ProviderConfig(
        base_url=os.environ['ATLASCRAFT_API_BASE_URL'],
        model=os.environ['ATLASCRAFT_MODEL'],
        api_key=os.environ.get('ATLASCRAFT_API_KEY', ''),
        api_style=os.environ.get('ATLASCRAFT_API_STYLE', 'responses'),
    )) as agent:
        result = run_pipeline(source, output, provider=agent)
else:
    result = run_pipeline(source, output)
print('Open:', result['viewer'])
