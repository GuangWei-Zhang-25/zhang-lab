"""Scientific invariants of the generic curated-section reconstruction core."""
import json
import unittest
from unittest import mock

import numpy as np
from scipy import ndimage as ndi

from atlascraft.core import build_volume


def section(size=48):
    a = np.zeros((size, size), dtype=np.uint16)
    a[8:35, 10:20] = 11
    a[23:35, 20:34] = 11
    a[11:20, 26:34] = 27
    a[30:34, 27:31] = 38
    return a


class CoreTests(unittest.TestCase):
    def test_translation_improves_and_preserves_inputs_and_anchors(self):
        a = section()
        b = ndi.shift(a, (4, -5), order=0, mode="constant", cval=0, prefilter=False)
        labels = np.stack([a, b])
        original = labels.copy()
        volume, evidence, meta, anchors = build_volume(labels, [0.2, 1.7], [0.02, 0.03], {
            "alignment": "translation", "interpolation": "signed_distance"})
        self.assertGreater(meta["metrics"]["mean_dice_after"], 0.98)
        self.assertGreater(meta["metrics"]["mean_dice_after"], meta["metrics"]["mean_dice_before"])
        np.testing.assert_array_equal(labels, original)
        np.testing.assert_array_equal(volume[meta["anchor_indices"]], anchors)
        self.assertEqual(volume.dtype, np.uint16)
        self.assertEqual(evidence.dtype, np.uint8)
        self.assertTrue(set(np.unique(volume)) <= set(np.unique(labels)))
        np.testing.assert_allclose(meta["transforms"][1]["translation_xy_px"], [5.0, -4.0], atol=0.5)
        json.dumps(meta, allow_nan=False)
        for c in meta["corrections"]:
            if c.get("accepted"):
                self.assertGreater(c["objective_after"], c["objective_before"])

    def test_rotation_improves_without_erasing_components(self):
        a = section(64)
        a[41:46, 17:27] = 49
        b = ndi.rotate(a, 8, reshape=False, order=0, mode="constant", cval=0, prefilter=False)
        _, _, meta, anchors = build_volume(np.stack([a, b]), [0, 1], [1, 1], {
            "interpolation": "signed_distance", "max_shift_px": 12})
        self.assertGreater(meta["metrics"]["mean_dice_after"], meta["metrics"]["mean_dice_before"] + 0.10)
        self.assertGreater(meta["metrics"]["mean_dice_after"], 0.9)
        self.assertLessEqual(abs(meta["transforms"][1]["rotation_deg"]), 12)
        for source, aligned in zip([a, b], anchors):
            self.assertEqual(set(np.unique(source)), set(np.unique(aligned)))

    def test_nonuniform_positions_and_physical_padding(self):
        a = section()
        labels = np.stack([a, a, a])
        volume, evidence, meta, anchors = build_volume(labels, [-2.4, -1.1, 3.2], [0.01, 0.05], {
            "alignment": "none", "subdivisions": 3, "interpolation": "signed_distance"})
        self.assertEqual(meta["anchor_indices"], [0, 3, 6])
        self.assertEqual([meta["z_coordinates_mm"][i] for i in meta["anchor_indices"]], [-2.4, -1.1, 3.2])
        self.assertFalse(np.allclose(np.diff(meta["z_coordinates_mm"]), np.diff(meta["z_coordinates_mm"])[0]))
        py, px = meta["padding_yx_px"]
        self.assertAlmostEqual(meta["origin_xy_mm"][0] + px * .01, 0)
        self.assertAlmostEqual(meta["origin_xy_mm"][1] + py * .05, 0)
        np.testing.assert_array_equal(anchors[:, py:py + a.shape[0], px:px + a.shape[1]], labels)
        np.testing.assert_array_equal(volume[meta["anchor_indices"]], anchors)
        self.assertTrue(np.all(evidence[0][anchors[0] != 0] == 1))
        self.assertTrue(np.all(evidence[1][volume[1] != 0] == 2))

    def test_missing_region_does_not_fill_background(self):
        a, b = np.zeros((32, 32), np.uint16), np.zeros((32, 32), np.uint16)
        a[7:12, 7:12] = 11
        b[22:27, 22:27] = 27
        volume, _, meta, anchors = build_volume(np.stack([a, b]), [0, 2], [1, 1], {
            "alignment": "none", "interpolation": "signed_distance"})
        self.assertIsNone(meta["metrics"]["mean_dice_after"])
        self.assertTrue(any(w["code"] == "missing_region_transition" for w in meta["warnings"]))
        self.assertTrue(any(w["code"] == "low_alignment_confidence" for w in meta["warnings"]))
        self.assertEqual(int(volume[2].sum()), 0)
        self.assertTrue(set(np.unique(volume)) <= {0, 11, 27})
        self.assertLessEqual(max(np.count_nonzero(p) for p in volume), 25)

    def test_unknown_is_retained_but_never_an_alignment_landmark(self):
        a, b = section(), section()
        a[37:43, 10:20] = 65535
        b[37:43, 22:32] = 65535
        volume, evidence, meta, _ = build_volume(np.stack([a, b]), [0, 1], [1, 1], {
            "alignment": "translation", "interpolation": "signed_distance"})
        self.assertEqual(meta["metrics"]["mean_dice_before"], 1)
        self.assertEqual(meta["metrics"]["mean_dice_after"], 1)
        self.assertEqual(meta["transforms"][1]["translation_xy_px"], [0, 0])
        self.assertTrue(np.any(evidence == 3))
        self.assertTrue(np.all(evidence[volume == 65535] >= 3))
        self.assertTrue(any(w["code"] == "unresolved_tissue" for w in meta["warnings"]))
        c = np.zeros((24, 24), np.uint16);c[7:12, 8:15] = 65535
        _, _, m, _ = build_volume(np.stack([c, c]), [0, 1], [1, 1])
        self.assertIsNone(m["metrics"]["mean_dice_after"])
        json.dumps(m, allow_nan=False)

    def test_single_pixel_identity_and_original_component_survive(self):
        a = section()
        a[4, 4] = 101
        a[40, 40] = 11  # separate single-pixel component of an existing identity
        b = ndi.shift(a, (2, 2), order=0, mode="constant", cval=0, prefilter=False)
        _, _, _, aligned = build_volume(np.stack([a, b]), [0, 1], [1, 1], {
            "alignment": "translation", "interpolation": "signed_distance"})
        self.assertEqual(np.count_nonzero(aligned[1] == 101), 1)
        self.assertEqual(ndi.label(aligned[1] == 11, np.ones((3, 3)))[1], 2)

    def test_shared_warp_default_is_safe_and_anchor_exact(self):
        a = section(40)
        b = a.copy();b[11:20, 26:34] = 0;b[13:22, 25:33] = 27
        volume, _, meta, anchors = build_volume(np.stack([a, b]), [0.0, 0.8], [0.03, 0.03], {
            "alignment": "translation", "max_shift_px": 6, "max_correction_rounds": 0})
        self.assertEqual(meta["options"]["interpolation"], "shared_warp")
        self.assertEqual(len(meta["pairs"]), 1)
        np.testing.assert_array_equal(volume[meta["anchor_indices"]], anchors)
        self.assertTrue(set(np.unique(volume)) <= set(np.unique(a)) | set(np.unique(b)))
        report = meta["pairs"][0]
        self.assertEqual(report["method"], "shared_warp")
        self.assertTrue(report["flow"]["accepted"])
        if report["flow"]["accepted"]:
            self.assertGreaterEqual(report["flow"]["minimum_all_partial_jacobian"], .25)
            self.assertGreater(report["flow"]["objective_after"], report["flow"]["objective_before"])
            self.assertLessEqual(report["maximum_inverse_residual_pixels"], 1.01e-4)
        json.dumps(meta, allow_nan=False)

    def test_shared_warp_failure_explicitly_falls_back(self):
        a = section(32);b = a.copy();b[12:18, 25:29] = 27
        with mock.patch("atlascraft.core._flow", side_effect=RuntimeError("synthetic safety failure")):
            _, _, meta, _ = build_volume(np.stack([a, b]), [0, 1], [1, 1], {"alignment": "none"})
        self.assertEqual(meta["pairs"][0]["method"], "signed_distance")
        self.assertTrue(any(w["code"] == "flow_fallback" for w in meta["warnings"]))

    def test_anisotropic_rotation_uses_physical_coordinates(self):
        from atlascraft.core import _resample
        a = section(64)
        # A 2:1 pixel aspect ratio must be honoured by the physical rigid map.
        b = _resample(a, (8, 0, 0), a.shape, (0, 0), [0.04, 0.02])
        _, _, meta, _ = build_volume(np.stack([a, b]), [0, 1], [.04, .02], {
            "max_shift_px": 8, "interpolation": "signed_distance"})
        self.assertGreater(meta["metrics"]["mean_dice_after"], .89)
        rotation = np.asarray(meta["transforms"][1]["input_xy_mm_to_aligned_xy_mm"])[:2, :2]
        np.testing.assert_allclose(rotation.T @ rotation, np.eye(2), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(rotation), 1)

    def test_unknown_or_label3023_has_no_special_named_weight(self):
        a = section(40)
        b = a.copy(); b[11:20, 26:34] = 0; b[13:22, 25:33] = 27
        labels = np.stack([a, b])
        renamed = labels.copy(); renamed[labels == 11] = 3023
        options = {"alignment": "translation", "max_shift_px": 6, "max_correction_rounds": 0}
        original = build_volume(labels, [0, 1], [1, 1], options)
        other = build_volume(renamed, [0, 1], [1, 1], options)
        restored = other[0].copy(); restored[restored == 3023] = 11
        np.testing.assert_array_equal(original[0], restored)
        self.assertAlmostEqual(original[2]["metrics"]["mean_dice_after"], other[2]["metrics"]["mean_dice_after"])

    def test_inverse_failure_retracts_accepted_flow_log(self):
        import atlascraft.core as core
        a = section(40); b = a.copy(); b[11:20, 26:34] = 0; b[13:22, 25:33] = 27
        actual = core._interpolate_pair
        def fail_for_flow(a, b, fractions, spacing, flow):
            if flow is not None:
                raise RuntimeError("synthetic inverse safety failure")
            return actual(a, b, fractions, spacing, flow)
        with mock.patch("atlascraft.core._interpolate_pair", side_effect=fail_for_flow):
            _, _, meta, _ = build_volume(np.stack([a, b]), [0, 1], [1, 1], {
                "alignment": "translation", "max_shift_px": 6, "max_correction_rounds": 0})
        self.assertEqual(meta["pairs"][0]["method"], "signed_distance")
        logs = [c for c in meta["corrections"] if c["stage"] == "shared_warp"]
        self.assertTrue(logs)
        self.assertFalse(logs[0]["accepted"])
        self.assertTrue(any(w["code"] == "inverse_warp_fallback" for w in meta["warnings"]))

    def test_validation_and_memory_limits(self):
        a = np.stack([section(), section()])
        cases = [(a.astype(np.int32), [0, 1], [1, 1], {}),
                 (a, [1, 1], [1, 1], {}), (a, [1, 0], [1, 1], {}),
                 (a, [0, np.nan], [1, 1], {}), (a, [-1e308, 1e308], [1, 1], {}), (a, [0, 1], [0, 1], {}),
                 (a, [0, 1], [1, 1], {"subdivisions": True}),
                 (a, [0, 1], [1, 1], {"subdivisions": 1.5}),
                 (a, [0, 1], [1, 1], {"max_shift_px": -1}),
                 (a, [0, 1], [1, 1], {"max_rotation_deg": np.inf}),
                 (a, [0, 1], [1, 1], {"unexpected": 1}),
                 (a, [0, 1], [1, 1], {"alignment": "deformable"})]
        for args in cases:
            with self.subTest(args=args[-1]):
                with self.assertRaises(ValueError): build_volume(*args)
        large = np.zeros((2, 1000, 1000), np.uint16)
        with self.assertRaisesRegex(ValueError, "Padded reconstruction"):
            build_volume(large, [0, 1], [1, 1])

    def test_empty_single_section_is_well_defined(self):
        a = np.zeros((1, 16, 20), np.uint16)
        volume, evidence, meta, aligned = build_volume(a, [7], [.2, .4])
        self.assertEqual(volume.shape[0], 1)
        self.assertEqual(meta["z_coordinates_mm"], [7])
        self.assertEqual(np.count_nonzero(volume), 0)
        self.assertEqual(np.count_nonzero(evidence), 0)
        self.assertEqual(meta["metrics"]["flagged_pairs"], 0)
        self.assertIsNone(meta["metrics"]["mean_dice_after"])
        np.testing.assert_array_equal(volume, aligned)

    def test_deterministic_repeated_build(self):
        a = np.stack([section(), section()])
        opt = {"alignment": "translation", "interpolation": "signed_distance"}
        first, second = build_volume(a, [0, 1], [1, 1], opt), build_volume(a, [0, 1], [1, 1], opt)
        np.testing.assert_array_equal(first[0], second[0])
        self.assertEqual(first[2], second[2])


if __name__ == "__main__":
    unittest.main()
