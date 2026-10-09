import base64
import gzip
import json
import re

import numpy as np
import pytest

from atlascraft.viewer import _coordinate_at, _surface_preview, write_viewer


def _payload(path):
    match = re.search(r'<script type="application/json" id="atlas-data">(.*?)</script>',
                      path.read_text(), re.S)
    return json.loads(match.group(1))


def test_nonuniform_surface_coordinates_and_native_labels(tmp_path):
    volume = np.zeros((3, 5, 6), dtype=np.uint16)
    volume[1, 1:4, 1:5] = 11
    volume[2, 2, 2] = 65535
    evidence = (volume > 0).astype(np.uint8) * 7
    meta = {"z_coordinates_mm": [0, 0.2, 1.0], "spacing_xy_mm": [0.1, 0.15],
            "origin_xy_mm": [-0.3, -0.4], "anchor_indices": [0, 2], "evidence_codes": {"7": "Reviewed source"}}
    artifacts = write_viewer(tmp_path, volume, evidence, meta, {"11": "Example", "65535": "Unresolved"}, {"11": "#123456"})
    payload = _payload(tmp_path / "viewer.html")
    restored = np.frombuffer(gzip.decompress(base64.b64decode(payload["labels"])), dtype="<u2").reshape(volume.shape)
    restored_evidence = np.frombuffer(gzip.decompress(base64.b64decode(payload["evidence"])), dtype="u1").reshape(volume.shape)
    np.testing.assert_array_equal(restored, volume)
    np.testing.assert_array_equal(restored_evidence, evidence)
    mesh = next(m for m in payload["meshes"] if m["id"] == 11)
    vertices = np.frombuffer(gzip.decompress(base64.b64decode(mesh["vertices"])), dtype="<f4").reshape(-1, 3)
    # A structure on Z index1 is bounded halfway toward actual physical neighbors:
    # (0+.2)/2=.1 and (.2+1)/2=.6, not uniformly spaced .1 and .3.
    assert vertices[:, 2].min() == pytest.approx(.1)
    assert vertices[:, 2].max() == pytest.approx(.6)
    assert payload["edges"][2] == pytest.approx([-.1, .1, .6, 1.4])
    assert any(r["id"] == 65535 and r["color"] == "#a8afb0" for r in payload["regions"])
    assert (tmp_path / "surfaces_preview.ply").read_bytes().startswith(b"ply\nformat binary_little_endian")
    assert artifacts["surface_preview"]["native_slice_arrays_unchanged"]
    assert artifacts["viewer_html"] == "viewer.html"
    assert artifacts["surface_preview_ply"] == "surfaces_preview.ply"
    assert artifacts["viewer_summary"] == "viewer_summary.json"


def test_untrusted_names_cannot_close_json_script(tmp_path):
    volume = np.ones((2, 3, 3), dtype=np.uint16)
    hostile = '</script><img src=x onerror="alert(1)">'
    write_viewer(tmp_path, volume, np.ones_like(volume, dtype=np.uint8),
                 {"title": hostile, "warnings": [hostile], "z_coordinates_mm": [0, 2]},
                 {"1": hostile}, {"1": "red; background:url(https://example.com)"})
    text = (tmp_path / "viewer.html").read_text()
    assert hostile not in text
    assert _payload(tmp_path / "viewer.html")["regions"][0]["name"] == hostile
    assert 'src="http' not in text and 'href="http' not in text
    assert '<title>&lt;/script&gt;' in text


def test_rejects_invalid_physical_grid(tmp_path):
    v = np.ones((3, 2, 2), dtype=np.uint16)
    with pytest.raises(ValueError, match="strictly increasing"):
        write_viewer(tmp_path, v, np.ones_like(v, dtype=np.uint8),
                     {"z_coordinates_mm": [0, 1, .5]}, {}, {})
    with pytest.raises(ValueError, match="same ZYX"):
        write_viewer(tmp_path, v, np.zeros((1, 1, 1), dtype=np.uint8), {}, {}, {})


def test_template_slot_text_stays_literal_data(tmp_path):
    v = np.ones((2, 3, 3), dtype=np.uint16)
    text = '{{SCRIPT}} {{DATA}} {{CSS}} {{TITLE}}'
    write_viewer(tmp_path, v, np.ones_like(v, dtype=np.uint8),
                 {'title': text, 'z_coordinates_mm': [0, 1]}, {'1': text}, {})
    assert _payload(tmp_path / 'viewer.html')['regions'][0]['name'] == text
    assert f'<title>{text} · AtlasCraft</title>' in (tmp_path / 'viewer.html').read_text()


def test_coordinate_extrapolation_and_single_plane():
    np.testing.assert_allclose(_coordinate_at(np.array([-.5, .5, 1.5, 2.5]), np.array([0., .2, 1.])), [-.1, .1, .6, 1.4])
    volume = np.ones((1, 1, 1), dtype=np.uint16)
    meshes, _ = _surface_preview(volume, (np.array([2.]), np.array([3.]), np.array([4.])), .8, spacing_xy=(.2, .4))
    vertices = meshes[0]["vertices"]
    np.testing.assert_allclose(vertices.min(axis=0), [1.9, 2.8, 3.6], atol=1e-6)
    np.testing.assert_allclose(vertices.max(axis=0), [2.1, 3.2, 4.4], atol=1e-6)
