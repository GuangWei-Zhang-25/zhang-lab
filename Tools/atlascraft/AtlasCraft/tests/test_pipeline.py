import copy
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from atlascraft.demo import demo_manifest, write_demo
from atlascraft.inputs import load_input
from atlascraft.pipeline import run_pipeline
from atlascraft.multiplane import fuse_volumes
from atlascraft.server import create_app


def small_manifest():
    m = demo_manifest()
    m['sections'] = m['sections'][:3]
    for section in m['sections']:
        section['labels'] = np.asarray(section['labels'])[::2, ::2].tolist()
    m['spacing_xy_mm'] = [.08, .08]
    return m


def test_png_zip_and_inline_have_identical_labels(tmp_path):
    p = write_demo(tmp_path / 'input')
    direct = load_input(p)
    inline = load_input(demo_manifest())
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for f in p.parent.iterdir():
            z.write(f, f.name)
    zipped = load_input(archive)
    assert np.array_equal(direct.labels, inline.labels)
    assert direct.hashes['input_labels_sha256'] == zipped.hashes['input_labels_sha256']
    assert 'labels' not in inline.manifest['sections'][0]


@pytest.mark.parametrize('mutation', ['uncurated', 'float_labels', 'bad_order', 'missing_id', 'nan_scale'])
def test_reject_invalid_curated_input(mutation):
    m = small_manifest()
    if mutation == 'uncurated': m['curated'] = False
    if mutation == 'float_labels': m['sections'][0]['labels'][0][0] = 1.5
    if mutation == 'bad_order': m['sections'][1]['z_mm'] = -1
    if mutation == 'missing_id': m['sections'][0]['labels'][0][0] = 99
    if mutation == 'nan_scale': m['spacing_xy_mm'][0] = float('nan')
    with pytest.raises(ValueError): load_input(m)


def test_zip_path_traversal_rejected(tmp_path):
    p = tmp_path / 'bad.zip'
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('manifest.json', json.dumps(small_manifest()))
        z.writestr('../escape.txt', 'bad')
    with pytest.raises(ValueError): load_input(p)
    assert not (tmp_path.parent / 'escape.txt').exists()


def test_full_pipeline_preserves_anchors_and_writes_portable_files(tmp_path):
    m = small_manifest()
    result = run_pipeline(m, tmp_path / 'output', options={'alignment': 'translation', 'interpolation': 'signed_distance', 'subdivisions': 2})
    folder = Path(result['output_dir'])
    meta = json.loads((folder / 'metadata.json').read_text())
    with np.load(folder / 'atlas.npz') as output, np.load(folder / 'aligned_anchors.npz') as anchors:
        assert np.array_equal(output['labels'][meta['anchor_indices']], anchors['labels'])
        assert set(np.unique(output['labels'])) <= {0, 1, 2, 3, 65535}
    original = np.load(folder / 'original_anchors.npz')['labels']
    assert np.array_equal(original, np.asarray([s['labels'] for s in m['sections']], np.uint16))
    assert meta['integrity']['aligned_anchors_exact']
    assert meta['human_review']['output_anatomically_accepted'] is False
    assert (folder / 'viewer.html').stat().st_size > 20000
    assert (folder / 'atlas.nii.gz').exists()
    assert len(json.loads((folder / 'boundaries.json').read_text())['sections']) == 3
    assert all(not Path(v).is_absolute() for k,v in meta['viewer_artifacts'].items() if isinstance(v,str))
    with pytest.raises(ValueError): run_pipeline(m, folder)


def test_nonuniform_z_stays_exact(tmp_path):
    m = small_manifest()
    m['sections'][2]['z_mm'] = 1.1
    result = run_pipeline(m, tmp_path / 'output', options={'alignment':'none','interpolation':'signed_distance','subdivisions':2})
    folder = Path(result['output_dir'])
    z = np.load(folder / 'atlas.npz')['z_coordinates_mm']
    assert np.allclose(z, [0., .2, .4, .75, 1.1])
    assert not (folder / 'atlas.nii.gz').exists()


class FakeAgent:
    def __init__(self): self.calls = 0
    def complete(self, messages, tools):
        assert 'Outer compartment' not in json.dumps(messages)
        name = ['validate_curated_references', 'extract_boundaries_and_assign_regions', 'align_interpolate_reconstruct',
                'inspect_geometric_quality', 'export_atlas_and_viewer'][self.calls]
        self.calls += 1
        return {'role':'assistant', 'content':None, 'tool_calls':[{'id':f'call_{self.calls}','type':'function','function':{'name':name,'arguments':'{}'}}]}


def test_agent_really_calls_pipeline_tools(tmp_path):
    agent = FakeAgent()
    result = run_pipeline(small_manifest(), tmp_path / 'output', options={'alignment':'none','subdivisions':1}, provider=agent)
    assert agent.calls == 5
    meta = json.loads((Path(result['output_dir']) / 'metadata.json').read_text())
    assert meta['agent_notes'][0]['status'] == 'completed'
    assert meta['agent_notes'][0]['tool_calls'] == 5


def test_provider_failure_completes_locally_without_saving_secret(tmp_path):
    class Broken:
        def complete(self, *args): raise RuntimeError('secret-test-token-DO-NOT-SAVE')
    result = run_pipeline(small_manifest(), tmp_path / 'output', options={'alignment':'none','subdivisions':1}, provider=Broken())
    p = Path(result['output_dir'])
    assert json.loads((p/'metadata.json').read_text())['agent_notes'][0]['status'] == 'provider_failed'
    assert not any(b'secret-test-token-DO-NOT-SAVE' in f.read_bytes() for f in p.iterdir() if f.is_file())


def test_conflicting_multiplane_labels_become_unresolved():
    a = np.ones((3,4,5), np.uint16)
    b = a.copy(); b[1,2,3] = 2
    meta = {'z_coordinates_mm':[0,1,2], 'spacing_xy_mm':[1,1], 'origin_xy_mm':[0,0]}
    result, evidence, coverage, conflict = fuse_volumes([a,b],[meta,meta],[np.eye(4),np.eye(4)],a.shape,[1,1,1],[0,0,0])
    assert result[1,2,3] == 65535
    assert conflict.sum() == 1
    assert np.all(coverage == 2)
    assert evidence[1,2,3] == 3


def test_crossplane_known_rotation_and_physical_coordinates():
    a = np.zeros((3,4,5), np.uint16); a[1,2,3] = 7
    meta = {'z_coordinates_mm':[0,1,2], 'spacing_xy_mm':[1,1], 'origin_xy_mm':[0,0]}
    rot = np.array([[0,-1,0,4],[1,0,0,0],[0,0,1,0],[0,0,0,1]],float)
    result, _, coverage, conflict = fuse_volumes([a,a],[meta,meta],[rot,rot],[3,6,6],[1,1,1],[0,0,0])
    assert result[1,3,2] == 7
    assert coverage[1,3,2] == 2
    assert not conflict.any()


def test_local_api_rejects_cross_origin_and_missing_session(tmp_path):
    app = create_app(tmp_path/'runs')
    with TestClient(app) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert 'AtlasCraft' in page.text
        assert client.post('/api/jobs').status_code == 403
        assert client.get('/',headers={'host':'evil.test'}).status_code == 403
        assert client.post('/api/jobs',headers={'x-atlascraft-session':app.state.session_token,'origin':'https://evil.test'}).status_code == 403
        assert client.get('/api/example').json()['schema'] == 'atlascraft-input-v1'

@pytest.mark.parametrize('style', ['responses','chat_completions'])
def test_http_adapter_orchestrates_real_pipeline_without_token_in_artifacts(tmp_path, style):
    import httpx
    from atlascraft.agent import HTTPProvider, ProviderConfig
    sequence = ['validate_curated_references','extract_boundaries_and_assign_regions','align_interpolate_reconstruct','inspect_geometric_quality','export_atlas_and_viewer']
    counter = []
    def handler(request):
        body = json.loads(request.content)
        assert request.headers['authorization'] == 'Bearer local-test-secret'
        assert 'local-test-secret' not in request.content.decode()
        assert 'Outer compartment' not in request.content.decode()
        name = sequence[len(counter)]
        counter.append(name)
        if style == 'responses':
            return httpx.Response(200,json={'status':'completed','output':[{'type':'function_call','id':f'fc_{len(counter)}','call_id':f'call_{len(counter)}','name':name,'arguments':'{}'}]})
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':f'call_{len(counter)}','type':'function','function':{'name':name,'arguments':'{}'}}]}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = HTTPProvider(ProviderConfig('https://example.test/v1','user-model','local-test-secret',style),client=client)
        result = run_pipeline(small_manifest(),tmp_path/'output',options={'alignment':'none','subdivisions':1},provider=provider)
    assert counter == sequence
    p = Path(result['output_dir'])
    meta = json.loads((p/'metadata.json').read_text())
    assert meta['agent_notes'][0]['status'] == 'completed'
    assert not any(b'local-test-secret' in f.read_bytes() for f in p.iterdir() if f.is_file())


def test_one_function_build_api(tmp_path):
    from atlascraft import build_atlas
    result = build_atlas(small_manifest(),tmp_path/'output',options={'alignment':'none','subdivisions':1})
    assert Path(result['viewer']).exists()
    with pytest.raises(ValueError): build_atlas(small_manifest(),tmp_path/'other',api_token='unused')
