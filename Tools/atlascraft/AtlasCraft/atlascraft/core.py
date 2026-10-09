"""Bounded reconstruction of a parallel stack of curated categorical sections.

This module does not detect or validate anatomy. Labels are unsigned identifiers:
0 is background and 65535 is unresolved tissue, never an anatomical landmark.
Physical coordinates use x rightward, y downward, and the supplied z positions.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage as ndi

UNKNOWN = 65535
_MAX_INPUT_VOXELS = 16_000_000
_MAX_OUTPUT_VOXELS = 32_000_000
_MAX_PLANE_PIXELS = 1_000_000
_DEFAULTS = {
    "alignment": "rigid", "max_shift_px": 24.0, "max_rotation_deg": 12.0,
    "subdivisions": 4, "max_correction_rounds": 2, "min_overlap_dice": 0.55,
    "interpolation": "shared_warp",
}


def _validate(labels, positions, spacing, options):
    if not isinstance(labels, np.ndarray) or labels.dtype != np.uint16:
        raise ValueError("labels must be a uint16 NumPy array [sections, height, width]; convert validated integer labels explicitly.")
    if labels.ndim != 3 or not 1 <= labels.shape[0] <= 128 or min(labels.shape[1:]) < 2:
        raise ValueError("labels must have 1–128 sections and height/width >= 2.")
    if labels.size > _MAX_INPUT_VOXELS or max(labels.shape[1:]) > 2048:
        raise ValueError("Input exceeds the 16,000,000-voxel / 2048-pixel section limit; use an explicitly coarser curated input.")
    if len(np.unique(labels)) > 512:
        raise ValueError("This bounded implementation supports at most 512 distinct source identifiers.")
    try:
        p = np.asarray(positions, dtype=np.float64)
        s = np.asarray(spacing, dtype=np.float64)
    except (ValueError, TypeError) as exc:
        raise ValueError("positions_mm and spacing_xy_mm must be finite numeric arrays.") from exc
    with np.errstate(over="ignore", invalid="ignore"):
        differences = np.diff(p) if p.ndim == 1 else np.array([np.nan])
    if p.shape != (len(labels),) or not np.isfinite(p).all() or not np.isfinite(differences).all() or np.any(differences <= 0):
        raise ValueError("positions_mm must contain one finite, strictly increasing value per section.")
    if s.shape != (2,) or not np.isfinite(s).all() or np.any(s <= 0):
        raise ValueError("spacing_xy_mm must contain positive finite [sx, sy] values.")
    if options is not None and not isinstance(options, dict):
        raise ValueError("options must be a dictionary or None.")
    opt = dict(_DEFAULTS)
    if options:
        invalid = set(options) - set(opt)
        if invalid:
            raise ValueError("Unknown core option(s): " + ", ".join(sorted(map(str, invalid))))
        opt.update(options)
    if opt["alignment"] not in ("rigid", "translation", "none"):
        raise ValueError("alignment must be rigid, translation or none.")
    if opt["interpolation"] not in ("shared_warp", "signed_distance"):
        raise ValueError("interpolation must be shared_warp or signed_distance.")
    for key, lo, hi in (("max_shift_px", 0, 128), ("max_rotation_deg", 0, 45), ("min_overlap_dice", 0, 1)):
        v = opt[key]
        if isinstance(v, (bool, str)) or not isinstance(v, (int, float, np.number)) or not np.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f"{key} must be a finite number between {lo} and {hi}.")
        opt[key] = float(v)
    for key, lo, hi in (("subdivisions", 1, 32), ("max_correction_rounds", 0, 5)):
        v = opt[key]
        if isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)) or not lo <= v <= hi:
            raise ValueError(f"{key} must be an integer between {lo} and {hi}.")
        opt[key] = int(v)
    if opt["alignment"] != "rigid":
        opt["max_rotation_deg"] = 0.0
    return p.copy(), s.copy(), opt


def _canvas(shape, spacing, options):
    h, w = shape
    # A physical bounding circle contains every rotation, including anisotropic pixels.
    # Use tight extrema over the allowed angle range, then add the translation bound.
    sx, sy = spacing
    a = math.radians(options["max_rotation_deg"])
    shift_bound = options["max_shift_px"] if options["alignment"] != "none" else 0.0
    angles = np.linspace(-a, a, 181) if a else np.array([0.0])
    x = (w - 1) * sx / 2
    y = (h - 1) * sy / 2
    xmax = max(abs(x * math.cos(t)) + abs(y * math.sin(t)) for t in angles)
    ymax = max(abs(y * math.cos(t)) + abs(x * math.sin(t)) for t in angles)
    pad_x = int(math.ceil(max(0, xmax / sx - (w - 1) / 2) + shift_bound)) + 2
    pad_y = int(math.ceil(max(0, ymax / sy - (h - 1) / 2) + shift_bound)) + 2
    return (h + 2 * pad_y, w + 2 * pad_x), (pad_y, pad_x)


def _forward_matrix(angle, spacing):
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    sx, sy = spacing
    return np.array([[c, s * sx / sy], [-s * sy / sx, c]], dtype=float)


def _resample(source, params, shape, padding, spacing):
    """Nearest-neighbour, input-pixel-centre to padded output-pixel-centre map."""
    angle, dy, dx = params
    fwd = _forward_matrix(angle, spacing)
    inverse = np.linalg.inv(fwd)
    center = (np.array(source.shape, float) - 1) / 2
    target_center = center + np.array(padding) + [dy, dx]
    offset = center - inverse @ target_center
    return ndi.affine_transform(source, inverse, offset=offset, output_shape=shape,
                                order=0, mode="constant", cval=0, prefilter=False)


def _known(a):
    return (a != 0) & (a != UNKNOWN)


def _dice(a, b):
    denom = int(np.count_nonzero(a)) + int(np.count_nonzero(b))
    return float(2 * np.count_nonzero(a & b) / denom) if denom else None


def _overlap(a, b):
    ids = sorted((set(map(int, np.unique(a))) & set(map(int, np.unique(b)))) - {0, UNKNOWN})
    region = [_dice(a == rid, b == rid) for rid in ids]
    union = _dice(_known(a), _known(b))
    macro = float(np.mean(region)) if region else None
    # No shared named identity means no defensible semantic registration objective.
    score = 0.8 * macro + 0.2 * union if macro is not None else None
    return {"dice": score, "shared_label_mean_dice": macro, "known_tissue_dice": union,
            "shared_named_labels": len(ids)}


def _penalty(params, opt):
    angle, dy, dx = params
    return 0.002 * ((dy * dy + dx * dx) / max(opt["max_shift_px"] ** 2, 1) +
                    angle ** 2 / max(opt["max_rotation_deg"] ** 2, 1))


def _valid_params(p, opt):
    return abs(p[0]) <= opt["max_rotation_deg"] + 1e-9 and max(abs(p[1]), abs(p[2])) <= opt["max_shift_px"] + 1e-9


def _components(source):
    result = []
    # Keep a record of every 8-connected source component, including unresolved tissue.
    for rid in np.unique(source):
        if rid == 0:
            continue
        comp, count = ndi.label(source == rid, structure=np.ones((3, 3), np.uint8))
        for idx, box in enumerate(ndi.find_objects(comp), 1):
            if box is None:
                continue
            coords = np.array(np.nonzero(comp[box] == idx), dtype=float)
            coords += np.array([box[0].start, box[1].start])[:, None]
            result.append((int(rid), coords))
    return result


def _preserves_components(source, candidate, params, padding, spacing, components):
    center = (np.array(source.shape, float) - 1) / 2
    fwd = _forward_matrix(params[0], spacing)
    translation = center + np.array(padding) + params[1:]
    for rid, coords in components:
        mapped = np.rint(fwd @ (coords - center[:, None]) + translation[:, None]).astype(int)
        inside = ((mapped[0] >= 0) & (mapped[0] < candidate.shape[0]) &
                  (mapped[1] >= 0) & (mapped[1] < candidate.shape[1]))
        if not inside.all() or not np.any(candidate[mapped[0], mapped[1]] == rid):
            return False
    return True


def _bounded_registration(labels, shape, padding, spacing, opt, warnings, corrections):
    params = [(0.0, 0.0, 0.0) for _ in labels]
    anchors = np.stack([_resample(a, params[0], shape, padding, spacing) for a in labels])
    originals = anchors.copy()
    components = [_components(a) for a in labels] if opt["alignment"] != "none" else []

    def try_candidates(section, proposals, neighbors, stage):
        current = params[section]
        def score(image, par):
            values = [_overlap(anchors[n], image)["dice"] for n in neighbors]
            valid = [v for v in values if v is not None]
            return (float(np.mean(valid)) - _penalty(par, opt)) if valid else None
        current_score = score(anchors[section], current)
        if current_score is None:
            corrections.append({"stage": stage, "section": section, "accepted": False,
                                "reason": "No shared named labels; transform remains unchanged."})
            return
        candidates = sorted(set(tuple(float(v) for v in p) for p in proposals))
        best, best_image, best_score = current, anchors[section], current_score
        for p in candidates:
            if not _valid_params(p, opt) or p == current:
                continue
            image = _resample(labels[section], p, shape, padding, spacing)
            value = score(image, p)
            improving = value is not None and value > best_score + 1e-8
            if improving and not _preserves_components(labels[section], image, p, padding, spacing, components[section]):
                corrections.append({"stage": stage, "section": section, "candidate": list(p),
                                    "accepted": False, "reason": "Candidate would erase a source connected component."})
                continue
            if improving:
                best, best_image, best_score = p, image, value
        accepted = best_score > current_score + 1e-8
        corrections.append({"stage": stage, "section": section, "accepted": accepted,
                            "objective_before": current_score, "objective_after": best_score,
                            "candidate_count": len(candidates), "from": list(current), "to": list(best),
                            "reason": "Strict regularized overlap improvement." if accepted else "No candidate improved the regularized overlap objective."})
        if accepted:
            params[section], anchors[section] = best, best_image

    if opt["alignment"] != "none":
        for i in range(1, len(labels)):
            angles = [0.0] if opt["alignment"] == "translation" else np.linspace(-opt["max_rotation_deg"], opt["max_rotation_deg"], 7)
            proposals = [params[i]]
            ref = _known(anchors[i - 1])
            if ref.any() and _known(anchors[i]).any():
                target = np.array(ndi.center_of_mass(ref))
                for angle in angles:
                    rotated = _resample(labels[i], (float(angle), 0, 0), shape, padding, spacing)
                    center = np.array(ndi.center_of_mass(_known(rotated)))
                    dy, dx = np.rint(np.clip(target - center, -opt["max_shift_px"], opt["max_shift_px"]))
                    proposals.extend([(float(angle), float(dy), float(dx)), (float(angle), 0.0, 0.0)])
            try_candidates(i, proposals, [i - 1], "initial_candidates")
            # Bounded deterministic local refinement; no stochastic optimizer.
            for step in (4.0, 2.0, 1.0):
                a, y, x = params[i]
                proposals = [(a, y + dy, x + dx) for dy in (-step, 0, step) for dx in (-step, 0, step)]
                if opt["alignment"] == "rigid":
                    proposals.extend((a + da, y, x) for da in (-step, step))
                try_candidates(i, proposals, [i - 1], f"initial_refine_{step:g}")
        # Re-evaluate against both adjacent sections, keeping section zero as the gauge.
        for turn in range(opt["max_correction_rounds"]):
            for i in range(1, len(labels)):
                step = 1.0 / (2 ** turn)
                a, y, x = params[i]
                proposals = [(a, y + dy, x + dx) for dy in (-step, 0, step) for dx in (-step, 0, step)]
                if opt["alignment"] == "rigid":
                    proposals.extend((a + da, y, x) for da in (-step, step))
                neighbors = [j for j in (i - 1, i + 1) if 0 <= j < len(labels)]
                try_candidates(i, proposals, neighbors, f"self_correction_round_{turn + 1}")
    for i in range(1, len(labels)):
        m = _overlap(anchors[i - 1], anchors[i])
        if m["dice"] is None or m["dice"] < opt["min_overlap_dice"]:
            warnings.append({"code": "low_alignment_confidence", "pair": [i - 1, i],
                             "dice": m["dice"], "message": "No shared named evidence or adjacent overlap is below threshold; anatomical review is required."})
    return originals, anchors, params


def _signed_distance(mask, spacing):
    if not mask.any():
        return None
    return (ndi.distance_transform_edt(mask, sampling=spacing[::-1]) -
            ndi.distance_transform_edt(~mask, sampling=spacing[::-1])).astype(np.float32)


def _flow(a, b, opt, corrections):
    """Source shared-map estimator, with generic (not spinal) safety constraints."""
    from ._vendor import common_warp as cw
    common = (set(map(int, np.unique(a))) & set(map(int, np.unique(b)))) - {0, UNKNOWN}
    if not common:
        return None, {"accepted": False, "reason": "No common named region supports flow estimation."}
    if np.array_equal(a, b):
        return None, {"accepted": False, "reason": "Identical anchors need no deformation."}
    # Bound one-hot optimization memory while retaining every sampled named identity.
    step = max(1, int(math.ceil(max(a.shape) / 96)))
    small_a, small_b = a[::step, ::step].copy(), b[::step, ::step].copy()
    small_a[small_a == UNKNOWN] = 0
    small_b[small_b == UNKNOWN] = 0
    if min(small_a.shape) < 8:
        return None, {"accepted": False, "reason": "Flow grid is too small for the source multiscale estimator."}
    sampled_common = (set(map(int, np.unique(small_a))) & set(map(int, np.unique(small_b)))) - {0}
    if not sampled_common:
        return None, {"accepted": False, "reason": "No shared named region survives the bounded flow-estimation grid."}
    raw, _ = cw.propose_flow(small_a, small_b, canal_label=None)
    yy, xx = np.mgrid[:a.shape[0], :a.shape[1]].astype(float)
    flow = np.stack([ndi.map_coordinates(f, [yy / step, xx / step], order=1, mode="nearest", prefilter=False) * step for f in raw]).astype(np.float32)
    sigma = max(1.0, min(a.shape) / 40)
    flow = np.stack([ndi.gaussian_filter(f, sigma) for f in flow])
    length = np.hypot(*flow)
    # The same finite bound applies to the additional nonrigid displacement.
    bound = opt["max_shift_px"]
    if bound == 0:
        return None, {"accepted": False, "reason": "The configured displacement bound is zero."}
    flow *= np.minimum(1, bound / np.maximum(length, 1e-12))
    edge = np.minimum.reduce([yy, xx, a.shape[0] - 1 - yy, a.shape[1] - 1 - xx])
    taper = np.clip(edge / max(3, min(a.shape) / 12), 0, 1)
    flow *= taper * taper * (3 - 2 * taper)
    strength = 1.0
    minimum = cw.partial_jacobian_min(flow)
    while minimum < 0.25 and strength > 1e-4:
        strength *= 0.7
        minimum = cw.partial_jacobian_min(flow * strength)
    if minimum < 0.25:
        return None, {"accepted": False, "reason": "No safe positive-Jacobian flow survived backtracking."}
    flow *= strength
    before = _overlap(a, b)["dice"]
    grid = np.stack([yy, xx])
    best = None
    best_score = before
    accepted_strength = None
    # Compare to zero and successively weaker candidates; never force a deformation.
    for amount in (1.0, 0.5, 0.25):
        candidate = flow * amount
        warped = ndi.map_coordinates(b, grid + candidate, order=0, mode="constant", cval=0, prefilter=False)
        after = _overlap(a, warped)["dice"]
        penalty = 0.002 * float(np.mean(np.sum(candidate * candidate, axis=0))) / max(bound ** 2, 1)
        if after is not None and after - penalty > best_score + 1e-6:
            best, best_score, accepted_strength = candidate, after - penalty, amount
    report = {"accepted": best is not None, "objective_before": before, "objective_after": best_score,
              "flow_grid_stride": step, "flow_grid_shape": list(small_a.shape),
              "sampled_common_named_labels": len(sampled_common), "full_common_named_labels": len(common),
              "regularization": "Generic Gaussian smoothing, displacement bound, identity boundary, all-time positive cell Jacobian; no midline/canal pins.",
              "strength": float(strength * accepted_strength) if best is not None else 0.0,
              "minimum_all_partial_jacobian": float(cw.partial_jacobian_min(best)) if best is not None else 1.0,
              "reason": "Strict regularized named-label overlap improvement." if best is not None else "No safe candidate improved overlap; signed-distance interpolation used."}
    return best, report


def _interpolate_pair(a, b, fractions, spacing, flow):
    """Stream label distance fields: positive support only, no global tissue fill."""
    from ._vendor import common_warp as cw
    out = np.zeros((len(fractions), *a.shape), dtype=np.uint16)
    best = np.zeros((len(fractions), *a.shape), dtype=np.float32)
    coordinates = []
    residuals = []
    for t in fractions:
        weight = float(t * t * (3 - 2 * t))
        if flow is None:
            coordinates.append((None, None, weight))
        else:
            ca, residual = cw.inverse_partial(flow, weight)
            cb = ca + np.stack([cw.sampling(f, ca) for f in flow])
            coordinates.append((ca, cb, weight))
            residuals.append(float(residual))
    ids = sorted((set(map(int, np.unique(a))) | set(map(int, np.unique(b)))) - {0})
    # Named regions win exact score ties; unknown wins only when its own support is stronger.
    unit = float(min(spacing))
    for rid in ids:
        d0, d1 = _signed_distance(a == rid, spacing), _signed_distance(b == rid, spacing)
        r0 = float(d0.max()) if d0 is not None else 0
        r1 = float(d1.max()) if d1 is not None else 0
        for j, (ca, cb, w) in enumerate(coordinates):
            v0 = cw.sampling(d0, ca) if ca is not None and d0 is not None else d0
            v1 = cw.sampling(d1, cb) if cb is not None and d1 is not None else d1
            if d0 is None:
                q = w * v1 - (1 - w) * (r1 + unit)
                radius = r1
            elif d1 is None:
                q = (1 - w) * v0 - w * (r0 + unit)
                radius = r0
            else:
                q = (1 - w) * v0 + w * v1
                radius = (1 - w) * r0 + w * r1
            score = q / max(radius, unit)
            hit = score > best[j]
            out[j, hit], best[j, hit] = rid, score[hit]
    return out, max(residuals, default=0.0)


def build_volume(labels: np.ndarray, positions_mm, spacing_xy_mm, options: dict | None = None):
    """Return ``(volume, evidence, metadata, aligned_anchors)`` without modifying input.

    ``volume`` is uint16 [Z,Hout,Wout]; ``evidence`` is uint8, where 0 means
    background, 1 is a named aligned anchor, 2 is interpolated named tissue,
    3 is unresolved anchor tissue, and 4 is interpolated unresolved tissue.
    ``subdivisions=k`` divides EACH physical interval into k subintervals and
    retains both endpoints exactly; nonuniform z is never described as uniform.
    Only background0 and source-supported identities can be emitted. Rigid
    registration changes the raster geometry, so exact preservation means exact
    *aligned* anchors; original section rasters are not modified or overwritten.
    """
    positions, spacing, opt = _validate(labels, positions_mm, spacing_xy_mm, options)
    shape, padding = _canvas(labels.shape[1:], spacing, opt)
    nplanes = (len(labels) - 1) * opt["subdivisions"] + 1
    voxels = int(nplanes * shape[0] * shape[1])
    if shape[0] * shape[1] > _MAX_PLANE_PIXELS or voxels > _MAX_OUTPUT_VOXELS:
        raise ValueError(f"Padded reconstruction would require {voxels:,} voxels ({shape[0]}×{shape[1]} per plane); limits are 32,000,000 output voxels and 1,000,000 pixels per padded plane. Reduce subdivisions or use explicitly coarser curated sections.")
    # Coordinates and inverse maps are bounded too, not only the final uint16 output.
    working_bytes = voxels * 3 + labels.size * 16 + len(labels) * shape[0] * shape[1] * 4 + shape[0] * shape[1] * (96 + opt["subdivisions"] * 44)
    if working_bytes > 768_000_000:
        raise ValueError("Estimated reconstruction working memory exceeds 768 MB; reduce subdivisions or curated section dimensions.")
    corrections: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    original, anchors, transforms = _bounded_registration(labels, shape, padding, spacing, opt, warnings, corrections)
    before = [_overlap(original[i], original[i + 1]) for i in range(len(labels) - 1)]
    after = [_overlap(anchors[i], anchors[i + 1]) for i in range(len(labels) - 1)]
    del original
    z = []
    for i in range(len(labels) - 1):
        z.extend(float(positions[i] + (positions[i + 1] - positions[i]) * j / opt["subdivisions"]) for j in range(opt["subdivisions"]))
    z.append(float(positions[-1]))
    anchor_indices = [i * opt["subdivisions"] for i in range(len(labels))]
    # Force supplied values bit-for-bit rather than relying on arithmetic endpoints.
    for idx, value in zip(anchor_indices, positions):
        z[idx] = float(value)
    if not np.isfinite(z).all() or np.any(np.diff(z) <= 0):
        raise ValueError("Requested subdivisions are not representable as distinct floating-point z coordinates at the supplied position scale.")
    volume = np.zeros((nplanes, *shape), dtype=np.uint16)
    evidence = np.zeros(volume.shape, dtype=np.uint8)
    pair_reports = []
    for i, idx in enumerate(anchor_indices):
        volume[idx] = anchors[i]
        evidence[idx][_known(anchors[i])] = 1
        evidence[idx][anchors[i] == UNKNOWN] = 3
    for i in range(len(labels) - 1):
        a, b = anchors[i], anchors[i + 1]
        ids_a, ids_b = set(map(int, np.unique(a))) - {0}, set(map(int, np.unique(b))) - {0}
        disappeared, appeared = sorted(ids_a - ids_b), sorted(ids_b - ids_a)
        if disappeared or appeared:
            warnings.append({"code": "missing_region_transition", "pair": [i, i + 1],
                             "disappearing_labels": disappeared, "appearing_labels": appeared,
                             "message": "Adjacent curated label sets differ. Missing regions shrink/appear locally; no anatomical identity is inferred to fill gaps."})
        flow, flow_report = None, {"accepted": False, "reason": "Signed-distance interpolation selected."}
        if opt["interpolation"] == "shared_warp" and opt["subdivisions"] > 1:
            try:
                flow, flow_report = _flow(a, b, opt, corrections)
            except (RuntimeError, ValueError, FloatingPointError) as exc:
                flow_report = {"accepted": False, "reason": f"Source flow safety failure: {exc}; signed-distance fallback."}
                warnings.append({"code": "flow_fallback", "pair": [i, i + 1], "message": flow_report["reason"]})
            corrections.append({"stage": "shared_warp", "pair": [i, i + 1], **flow_report})
        fractions = [j / opt["subdivisions"] for j in range(1, opt["subdivisions"])]
        if fractions:
            try:
                planes, residual = _interpolate_pair(a, b, fractions, spacing, flow)
            except RuntimeError as exc:
                if flow is None:
                    raise
                warnings.append({"code": "inverse_warp_fallback", "pair": [i, i + 1], "message": f"Shared-map inverse failed safety check: {exc}; signed-distance fallback."})
                flow_report["accepted"] = False
                flow_report["reason"] = "Inverse safety failure; signed-distance fallback."
                for correction in reversed(corrections):
                    if correction.get("stage") == "shared_warp" and correction.get("pair") == [i, i + 1]:
                        correction["accepted"] = False
                        correction["reason"] = flow_report["reason"]
                        break
                flow = None
                planes, residual = _interpolate_pair(a, b, fractions, spacing, None)
            start = anchor_indices[i] + 1
            volume[start:start + len(fractions)] = planes
            evidence[start:start + len(fractions)][_known(planes)] = 2
            evidence[start:start + len(fractions)][planes == UNKNOWN] = 4
        else:
            residual = 0.0
        pair_reports.append({"pair": [i, i + 1], "method": "shared_warp" if flow is not None else "signed_distance", "flow": flow_report,
                             "maximum_inverse_residual_pixels": residual, "before": before[i], "after": after[i]})
    unknown = int(np.count_nonzero(volume == UNKNOWN))
    if np.any(labels == UNKNOWN):
        warnings.append({"code": "unresolved_tissue", "source_voxels": int(np.count_nonzero(labels == UNKNOWN)), "output_voxels": unknown,
                         "message": "65535 denotes unresolved tissue; excluded from registration objectives and retained as a source-supported interpolation identity."})
    if any(not _known(a).any() for a in labels):
        warnings.append({"code": "section_without_named_tissue", "sections": [i for i, a in enumerate(labels) if not _known(a).any()], "message": "A section has no named anatomical tissue; automatic alignment cannot establish anatomical correspondence."})
    valid_before = [m["dice"] for m in before if m["dice"] is not None]
    valid_after = [m["dice"] for m in after if m["dice"] is not None]
    metrics = {"mean_dice_before": float(np.mean(valid_before)) if valid_before else None,
               "mean_dice_after": float(np.mean(valid_after)) if valid_after else None,
               "min_dice_after": float(min(valid_after)) if valid_after else None,
               "flagged_pairs": sum(m["dice"] is None or m["dice"] < opt["min_overlap_dice"] for m in after),
               "input_sections": int(len(labels)), "output_voxels": voxels, "unknown_voxels": unknown,
               "correction_count": sum(bool(c.get("accepted")) for c in corrections),
               "dice_scope": "Adjacent aligned-anchor overlap before and after rigid/translation registration; pair flow objectives are reported separately.",
               "dice_definition": "0.8×mean Dice of shared named identities + 0.2×known-tissue-union Dice; excludes0/65535; null when no shared named identity."}
    matrices = []
    sx, sy = map(float, spacing)
    center_xy = np.array([(labels.shape[2] - 1) * sx / 2, (labels.shape[1] - 1) * sy / 2])
    for i, (angle, dy, dx) in enumerate(transforms):
        t = math.radians(angle)
        rotation = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
        offset = center_xy - rotation @ center_xy + [dx * sx, dy * sy]
        matrix = np.eye(3); matrix[:2, :2] = rotation; matrix[:2, 2] = offset
        matrices.append({"section": i, "rotation_deg": float(angle), "translation_xy_px": [float(dx), float(dy)],
                         "input_xy_mm_to_aligned_xy_mm": matrix.tolist()})
    metadata = {"schema_version": 1, "method": "Bounded semantic " + opt["alignment"] + " registration and " + opt["interpolation"] + " categorical interpolation",
                "options": opt, "z_coordinates_mm": z, "spacing_xy_mm": [sx, sy],
                "origin_xy_mm": [-padding[1] * sx, -padding[0] * sy], "padding_yx_px": list(padding),
                "input_shape_zyx": list(labels.shape), "output_shape_zyx": list(volume.shape),
                "anchor_indices": anchor_indices, "anchor_positions_mm": positions.tolist(),
                "transforms": matrices, "corrections": corrections, "warnings": warnings, "metrics": metrics,
                "pairs": pair_reports, "source_label_ids": list(map(int, np.unique(labels))),
                "output_label_ids": list(map(int, np.unique(volume))),
                "evidence_codes": {"0": "background", "1": "named_aligned_anchor", "2": "named_interpolated", "3": "unresolved_aligned_anchor", "4": "unresolved_interpolated"},
                "coordinate_convention": "Pixel centres: x=origin_x+column*sx, y=origin_y+row*sy; z from explicit z_coordinates_mm. Positive rotation is clockwise on a displayed x-right/y-down image. First section is the fixed registration gauge.",
                "alignment_scope": "Automatic engineering overlap check of curated categorical sections; no anatomical validation or boundary detection.",
                "limitations": ["Parallel sections only; supplied z positions and in-plane calibration are authoritative.",
                                "Nearest-neighbour rigid resampling can alter component pixel counts; every source component must retain support, and aligned anchor rasters are preserved exactly.",
                                "Flow uses a bounded coarse named-label grid, generic smoothing and identity-boundary Jacobian checks; no spinal midline or canal prior is applied.",
                                "Positive signed-distance support is conservative: unsupported gaps remain background. Appearance/disappearance is a geometric interpolation assumption, not inferred anatomy.",
                                "Exact normalized-score ties use ascending source identifier order; small interpolated structures may vanish between anchors.",
                                "No biological accuracy, topology or cross-specimen correspondence guarantee; flagged pairs require anatomical review."]}
    assert set(np.unique(volume)) <= set(np.unique(labels)) | {0}
    assert np.array_equal(volume[anchor_indices], anchors)
    return volume, evidence, metadata, anchors
