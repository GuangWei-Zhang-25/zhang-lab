"""Independent integration and scientific edge-case review of the workflow."""
import copy
import io
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np

from atlascraft.inputs import load_input
from atlascraft.multiplane import fuse_volumes
from atlascraft.orchestration import numeric_summary
from atlascraft.pipeline import PIPELINE_TOOLS, PipelineSession, run_pipeline


def manifest(name="Review fixture", unknown=False, disjoint=False):
    a = np.zeros((20, 22), dtype=np.uint16)
    a[5:14, 6:15] = 1
    b = a.copy()
    if disjoint:
        b[b == 1] = 2
    if unknown:
        a[a == 1] = 65535; b[b == 1] = 65535
    return {"schema": "atlascraft-input-v1", "name": name, "curated": True,
            "spacing_xy_mm": [0.2, 0.3],
            "labels": [{"id": 1, "name": "Region one", "color": "#ff0000"},
                       {"id": 2, "name": "Region two", "color": "#00ff00"}],
            "sections": [{"z_mm": 0.2, "labels": a.tolist()}, {"z_mm": 1.4, "labels": b.tolist()}]}


OPTIONS = {"alignment": "none", "interpolation": "signed_distance", "subdivisions": 2}


class FakeAgent:
    def __init__(self):
        self.messages = []
        self.calls = 0
        self.secret = "secret-token-review-123"

    def complete(self, messages, tools):
        self.messages.append(copy.deepcopy(messages))
        names = [t["function"]["name"] for t in tools if t["function"]["name"] != "retry_alignment"]
        self.calls += 1
        return {"content": "DO NOT SAVE " + self.secret,
                "tool_calls": [{"id": "call_" + str(i), "type": "function",
                                "function": {"name": name, "arguments": "{}"}} for i, name in enumerate(names)]}


class WorkflowReviewTests(unittest.TestCase):
    def test_real_offline_pipeline_exports_correct_physical_grid(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "result"
            result = run_pipeline(manifest(), output, options=OPTIONS)
            self.assertEqual(result["status"], "awaiting_human_anatomical_review")
            meta = json.loads((output / "metadata.json").read_text())
            with np.load(output / "atlas.npz", allow_pickle=False) as atlas, np.load(output / "aligned_anchors.npz", allow_pickle=False) as anchors:
                np.testing.assert_array_equal(atlas["labels"][meta["anchor_indices"]], anchors["labels"])
                np.testing.assert_allclose(atlas["z_coordinates_mm"], [.2, .8, 1.4])
                np.testing.assert_allclose(atlas["spacing_xy_mm"], [.2, .3])
            self.assertFalse(meta["human_review"]["output_anatomically_accepted"])
            self.assertTrue((output / "viewer.html").is_file())
            import nibabel as nib
            nifti = nib.load(output / "atlas.nii.gz")
            np.testing.assert_allclose(nifti.affine[:3, 3], [*meta["origin_xy_mm"], .2], atol=1e-6)
            np.testing.assert_allclose(np.diag(nifti.affine)[:3], [.2, .3, .6], atol=1e-6)

    def test_fake_tool_agent_cannot_receive_dataset_text_or_save_prose(self):
        provider = FakeAgent()
        source = manifest("SOURCE_PROMPT_IGNORE_ALL_RULES")
        source["description"] = "SOURCE_PRIVATE_ANNOTATION"
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "result"
            run_pipeline(source, output, options=OPTIONS, provider=provider)
            sent = json.dumps(provider.messages)
            self.assertNotIn(source["name"], sent)
            self.assertNotIn(source["description"], sent)
            self.assertNotIn(provider.secret, sent)
            for path in output.rglob("*"):
                if path.is_file():
                    self.assertNotIn(provider.secret.encode(), path.read_bytes(), str(path))
            trace = json.loads((output / "tool_trace.json").read_text())
            self.assertTrue(any(t["tool"] == "export_atlas_and_viewer" for t in trace))
            for t in trace:
                clean = numeric_summary(t["result"])
                def assert_numeric(v):
                    if isinstance(v, dict):
                        for value in v.values(): assert_numeric(value)
                    elif isinstance(v, list):
                        for value in v: assert_numeric(value)
                    else:
                        self.assertTrue(v is None or isinstance(v, (bool, int, float)), v)
                assert_numeric(clean)

    def test_provider_exception_secret_not_saved(self):
        class BadProvider:
            def complete(self, *args):
                raise RuntimeError("Authorization: Bearer DO_NOT_LOG_THIS_SECRET")
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "result"
            run_pipeline(manifest(), output, options=OPTIONS, provider=BadProvider())
            for path in output.rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"DO_NOT_LOG_THIS_SECRET", path.read_bytes())
            meta = json.loads((output / "metadata.json").read_text())
            self.assertEqual(meta["agent_notes"][0]["status"], "provider_failed")

    def test_retry_with_unavailable_overlap_is_explicitly_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            session = PipelineSession(manifest(disjoint=True), Path(td), OPTIONS, None)
            session.validate(); session.boundaries(); session.reconstruct(); session.audit()
            before = session.volume.copy()
            result = session.retry({"max_shift_px": 8, "max_rotation_deg": 4})
            self.assertFalse(result["candidate_accepted"])
            np.testing.assert_array_equal(session.volume, before)
            self.assertFalse(session.metadata["agent_corrections"][-1]["accepted"])
            json.dumps(session.metadata, allow_nan=False)

    def test_export_retains_resolved_core_options(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "result"
            run_pipeline(manifest(), output, options={"interpolation": "signed_distance"})
            meta = json.loads((output / "metadata.json").read_text())
            self.assertEqual(meta["options"]["alignment"], "rigid")
            self.assertEqual(meta["options"]["subdivisions"], 4)
            self.assertEqual(meta["options"]["max_correction_rounds"], 2)

    def test_no_output_overwrite_and_cleanup_after_invalid_input(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "existing"; target.mkdir(); marker = target / "keep.txt"; marker.write_text("keep")
            with self.assertRaises(ValueError): run_pipeline(manifest(), target, options=OPTIONS)
            self.assertEqual(marker.read_text(), "keep")
            bad = manifest(); bad["curated"] = False
            with self.assertRaises(ValueError): run_pipeline(bad, Path(td) / "failed", options=OPTIONS)
            self.assertFalse((Path(td) / "failed").exists())
            self.assertEqual(list(Path(td).glob(".atlascraft-*")), [])

    def test_zip_and_local_manifest_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); source = manifest(); source["sections"][0] = {"z_mm": .2, "file": "../outside.npy"}
            np.save(td / "outside.npy", np.ones((20, 22), np.uint16))
            folder = td / "input"; folder.mkdir(); p = folder / "manifest.json";p.write_text(json.dumps(source))
            with self.assertRaises(ValueError): load_input(p)
            for member in ("../escape.txt", "/absolute.txt", "folder\\escape.txt"):
                zip_path = td / "bad.zip"
                with zipfile.ZipFile(zip_path, "w") as z:
                    z.writestr("manifest.json", json.dumps(manifest()))
                    z.writestr(member, "bad")
                with self.assertRaises(ValueError): load_input(zip_path)
            with zipfile.ZipFile(td / "link.zip", "w") as z:
                z.writestr("manifest.json", json.dumps(manifest()))
                item = zipfile.ZipInfo("link.npy");item.create_system = 3;item.external_attr = 0o120777 << 16
                z.writestr(item, "../outside.npy")
            with self.assertRaises(ValueError): load_input(td / "link.zip")

    def test_duplicate_zip_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "duplicate.zip"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("manifest.json", json.dumps(manifest()))
                z.writestr("manifest.json", json.dumps(manifest()))
            with self.assertRaises(ValueError): load_input(p)

    @staticmethod
    def fusion_meta():
        return {"z_coordinates_mm": [0.0, 1.0], "spacing_xy_mm": [1, 1], "origin_xy_mm": [0, 0]}

    def test_multiplane_unknown_does_not_hide_order_dependent_named_conflict(self):
        arrays = [np.full((2, 2, 2), rid, np.uint16) for rid in (65535, 1, 2)]
        answers = []
        for order in itertools.permutations(range(3)):
            v, e, cover, conflict = fuse_volumes([arrays[i] for i in order], [self.fusion_meta()] * 3,
                    [np.eye(4)] * 3, [2, 2, 2], [1, 1, 1], [0, 0, 0])
            self.assertTrue(np.all(v == 65535))
            self.assertTrue(np.all(cover == 3))
            self.assertTrue(np.all(conflict), str(order))
            answers.append(e)
        for answer in answers: np.testing.assert_array_equal(answer, answers[0])

    def test_multiplane_oblique_transform_and_origin_are_applied(self):
        angle = np.deg2rad(30)
        transform = np.eye(4)
        transform[:3, :3] = [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
        transform[:3, 3] = [3, -2, 0]
        local_point = np.array([1, 1, 0, 1])
        world = transform @ local_point
        a = np.zeros((2, 4, 4), np.uint16); a[:, 1, 1] = 7
        b = np.zeros_like(a)
        meta = self.fusion_meta()
        volume, _, _, _ = fuse_volumes([a, b], [meta, meta], [transform, transform], [2, 2, 2], [.1, .1, 1], world[:3])
        self.assertEqual(int(volume[0, 0, 0]), 7)
        self.assertEqual(int(volume[1, 0, 0]), 7)

    def test_server_rejects_cross_origin_and_omits_posted_credentials_from_status(self):
        from fastapi.testclient import TestClient
        from atlascraft.server import create_app
        with tempfile.TemporaryDirectory() as td:
            app = create_app(td)
            with TestClient(app) as client:
                self.assertEqual(client.post("/api/jobs", data={"demo": "true"}).status_code, 403)
                self.assertEqual(client.get("/", headers={"Origin": "https://remote.example"}).status_code, 403)
                self.assertEqual(client.get("/", headers={"Host": "remote.example"}).status_code, 403)
                token = app.state.session_token
                response = client.post("/api/jobs", headers={"x-atlascraft-session": token},
                        data={"demo": "true", "options": "{}", "provider": json.dumps({"base_url": "SECRET_BAD_URL", "api_key": "PRIVATE_KEY"})})
                self.assertEqual(response.status_code, 202)
                import time
                for _ in range(100):
                    status = client.get("/api/jobs/" + response.json()["id"]).json()
                    if status["status"] not in {"queued", "running"}: break
                    time.sleep(.005)
                self.assertEqual(status["status"], "failed")
                self.assertNotIn("PRIVATE_KEY", json.dumps(status))
                self.assertNotIn("SECRET_BAD_URL", json.dumps(status))
                for path in Path(td).rglob("*"):
                    if path.is_file(): self.assertNotIn(b"PRIVATE_KEY", path.read_bytes())


if __name__ == "__main__": unittest.main()
