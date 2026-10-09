"""Self-contained, offline 3-D and native-label slice viewer.

Mesh extraction is deliberately a bounded display preview. The original arrays
are embedded separately and remain the only source for slice lookup values.
"""
from __future__ import annotations

import base64
import colorsys
import gzip
import html
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
from scipy import ndimage
from skimage.measure import marching_cubes


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _safe_json(value: Any) -> str:
    # A JSON script element must not be terminable by names supplied by users.
    return json.dumps(_jsonable(value), ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace(
                          "&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _compressed(array: np.ndarray) -> str:
    return base64.b64encode(gzip.compress(array.tobytes(order="C"), compresslevel=6, mtime=0)).decode("ascii")


def _coordinate_at(indices: np.ndarray, centers: np.ndarray, singleton_step: float = 1.0) -> np.ndarray:
    """Piecewise-linear physical position, including half-voxel boundary extrapolation."""
    indices = np.asarray(indices, dtype=np.float64)
    centers = np.asarray(centers, dtype=np.float64)
    if len(centers) == 1:
        return centers[0] + indices * singleton_step
    result = np.interp(indices, np.arange(len(centers)), centers)
    result = np.where(indices < 0, centers[0] + indices * (centers[1] - centers[0]), result)
    return np.where(indices > len(centers) - 1,
                    centers[-1] + (indices - len(centers) + 1) * (centers[-1] - centers[-2]), result)


def _edges(centers: np.ndarray, singleton_step: float) -> np.ndarray:
    if len(centers) == 1:
        return np.array([centers[0] - singleton_step / 2, centers[0] + singleton_step / 2])
    return np.r_[centers[0] - (centers[1] - centers[0]) / 2,
                 (centers[:-1] + centers[1:]) / 2,
                 centers[-1] + (centers[-1] - centers[-2]) / 2]


def _color(label: int, supplied: dict) -> str:
    color = supplied.get(str(label), supplied.get(label))
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return color.lower()
    if label == 65535:
        return "#a8afb0"
    if label == 0:
        return "#f6f4ec"
    rgb = colorsys.hsv_to_rgb((label * 0.61803398875) % 1, 0.49, 0.78)
    return "#" + "".join(f"{round(v * 255):02x}" for v in rgb)


def _surface_preview(volume: np.ndarray, xyz: tuple[np.ndarray, ...],
                     singleton_z_step: float, max_axis: int = 100,
                     triangle_budget: int = 450_000,
                     spacing_xy: tuple[float, float] = (1.0, 1.0)) -> tuple[list[dict], dict]:
    x, y, z = xyz
    native_bounds = [_edges(x, spacing_xy[0]), _edges(y, spacing_xy[1]), _edges(z, singleton_z_step)]
    attempts = []
    for resolution in (max_axis, 76, 56, 40, 28, 20, 12):
        if resolution > max_axis:
            continue
        sampled = [np.unique(np.r_[np.arange(0, n, max(1, int(np.ceil(n / resolution)))), n - 1])
                   for n in volume.shape]
        coarse = volume[np.ix_(*sampled)]
        boxes = ndimage.find_objects(coarse, max_label=int(coarse.max()))
        meshes = []
        faces_total = 0
        preview_xyz = (x[sampled[2]], y[sampled[1]], z[sampled[0]])
        for label in np.unique(coarse):
            label = int(label)
            if label == 0:
                continue
            box = boxes[label - 1]
            mask = np.pad((coarse[box] == label).astype(np.uint8), 1)
            vertices, faces, _, _ = marching_cubes(mask, level=0.5, allow_degenerate=False)
            vertices += np.array([s.start - 1 for s in box])
            physical = np.column_stack([
                _coordinate_at(vertices[:, 2], preview_xyz[0], spacing_xy[0]),
                _coordinate_at(vertices[:, 1], preview_xyz[1], spacing_xy[1]),
                _coordinate_at(vertices[:, 0], preview_xyz[2], singleton_z_step),
            ])
            for axis in range(3):
                physical[:, axis] = np.clip(physical[:, axis], native_bounds[axis][0], native_bounds[axis][-1])
            # The ZYX -> XYZ permutation reverses orientation.
            faces = faces[:, [0, 2, 1]].astype("<u4")
            physical = physical.astype("<f4")
            tri = physical[faces]
            face_normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            normals = np.zeros_like(physical)
            for corner in range(3):
                np.add.at(normals, faces[:, corner], face_normals)
            lengths = np.linalg.norm(normals, axis=1)
            normals /= np.maximum(lengths[:, None], 1e-12)
            meshes.append({"label": label, "vertices": physical, "normals": normals.astype("<f4"), "faces": faces})
            faces_total += len(faces)
            if faces_total > triangle_budget:
                break
        attempts.append({"shape_zyx": list(coarse.shape), "triangles": faces_total})
        if faces_total <= triangle_budget:
            present = set(map(int, np.unique(volume))) - {0}
            return meshes, {
                "kind": "Categorical marching-cubes display preview; not a measurement mesh",
                "native_shape_zyx": list(volume.shape), "preview_shape_zyx": list(coarse.shape),
                "sampling_indices_zyx": [a.tolist() for a in sampled],
                "triangles": faces_total, "regions_with_surfaces": len(meshes),
                "labels_without_preview_surface": sorted(present - {m["label"] for m in meshes}),
                "physical_nonuniform_z_used": True, "native_slice_arrays_unchanged": True,
                "boundary_note": "Preview sampling can simplify or miss small structures. End surfaces are computational closures at the displayed grid boundary.",
            }
    raise ValueError("Unable to create a bounded surface preview; try a smaller reconstruction extent.")


def _write_ply(path: Path, meshes: list[dict], colors: dict) -> None:
    vertex_count = sum(len(m["vertices"]) for m in meshes)
    face_count = sum(len(m["faces"]) for m in meshes)
    header = ("ply\nformat binary_little_endian 1.0\n"
              "comment AtlasCraft display preview; coordinates are physical XYZ millimetres\n"
              "comment Downsampled categorical surfaces; not a native measurement mesh\n"
              f"element vertex {vertex_count}\nproperty float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\nproperty ushort label_id\n"
              f"element face {face_count}\nproperty list uchar int vertex_indices\nend_header\n")
    vertex_dtype = np.dtype([("xyz", "<f4", 3), ("rgb", "u1", 3), ("label", "<u2")])
    face_dtype = np.dtype([("count", "u1"), ("indices", "<i4", 3)])
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        for mesh in meshes:
            a = np.zeros(len(mesh["vertices"]), dtype=vertex_dtype)
            a["xyz"] = mesh["vertices"]
            c = colors[str(mesh["label"])].lstrip("#")
            a["rgb"] = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
            a["label"] = mesh["label"]
            f.write(a.tobytes())
        offset = 0
        for mesh in meshes:
            a = np.zeros(len(mesh["faces"]), dtype=face_dtype)
            a["count"] = 3
            a["indices"] = mesh["faces"] + offset
            f.write(a.tobytes())
            offset += len(mesh["vertices"])


def write_viewer(output_dir: Path, volume: np.ndarray, evidence: np.ndarray,
                 metadata: dict, label_names: dict, label_colors: dict) -> dict:
    """Write one self-contained viewer plus a coloured PLY surface preview/report.

    Arrays use ZYX indexing. ``spacing_xy_mm`` and ``origin_xy_mm`` are [X,Y];
    ``z_coordinates_mm`` gives strictly increasing native plane centers.
    No API provider or internet connection is used.
    """
    volume = np.asarray(volume)
    evidence = np.asarray(evidence)
    if volume.ndim != 3 or volume.dtype != np.uint16 or not all(volume.shape):
        raise ValueError("Viewer labels must be a nonempty uint16 ZYX array.")
    if evidence.shape != volume.shape or evidence.dtype != np.uint8:
        raise ValueError("Viewer evidence must be uint8 with the same ZYX shape.")
    spacing = np.asarray(metadata.get("spacing_xy_mm", [1.0, 1.0]), dtype=float)
    origin = np.asarray(metadata.get("origin_xy_mm", [0.0, 0.0]), dtype=float)
    z = np.asarray(metadata.get("z_coordinates_mm", np.arange(volume.shape[0])), dtype=float)
    if spacing.shape != (2,) or origin.shape != (2,) or not np.all(np.isfinite(spacing)) or np.any(spacing <= 0) or not np.all(np.isfinite(origin)):
        raise ValueError("Viewer requires finite positive XY spacing and finite XY origin.")
    if z.shape != (volume.shape[0],) or not np.all(np.isfinite(z)) or np.any(np.diff(z) <= 0):
        raise ValueError("Viewer Z coordinates must be finite, strictly increasing native plane centers.")
    single_z_step = float(metadata.get("spacing_z_mm", min(spacing)))
    if not np.isfinite(single_z_step) or single_z_step <= 0:
        raise ValueError("Single-plane Z thickness must be positive.")
    x = origin[0] + np.arange(volume.shape[2]) * spacing[0]
    y = origin[1] + np.arange(volume.shape[1]) * spacing[1]
    meshes, summary = _surface_preview(volume, (x, y, z), single_z_step,
                                       spacing_xy=tuple(spacing))
    ids, counts = np.unique(volume, return_counts=True)
    names = {str(int(i)): str(label_names.get(str(int(i)), label_names.get(int(i),
            "Outside" if i == 0 else "Unresolved occupied tissue" if i == 65535 else f"Label {int(i)}"))) for i in ids}
    colors = {str(int(i)): _color(int(i), label_colors) for i in ids}
    regions = [{"id": int(i), "name": names[str(int(i))], "color": colors[str(int(i))],
                "voxels": int(n), "has_surface": int(i) in {m["label"] for m in meshes}} for i, n in zip(ids, counts)]
    payload = {"shape": list(volume.shape), "spacing_xy_mm": spacing.tolist(),
               "origin_xy_mm": origin.tolist(), "z": z.tolist(),
               "edges": [_edges(x, spacing[0]).tolist(), _edges(y, spacing[1]).tolist(), _edges(z, single_z_step).tolist()],
               "labels": _compressed(volume.astype("<u2", copy=False)), "evidence": _compressed(evidence),
               "regions": regions, "preview": summary, "metadata": _jsonable(metadata),
               "meshes": [{"id": m["label"], "vertices": _compressed(m["vertices"]),
                           "normals": _compressed(m["normals"]), "faces": _compressed(m["faces"])} for m in meshes]}
    static = Path(__file__).parent / "static"
    template = (static / "viewer.html").read_text(encoding="utf-8")
    title = str(metadata.get("title", metadata.get("name", "Your reconstructed atlas")))
    replacements = {"TITLE": html.escape(title), "CSS": (static / "viewer.css").read_text(),
                    "DATA": _safe_json(payload), "SCRIPT": (static / "viewer.js").read_text()}
    # Substitute only original template slots; dataset text may literally contain
    # strings such as {{SCRIPT}} and must not be interpreted as another slot.
    content = re.sub(r"\{\{(TITLE|CSS|DATA|SCRIPT)\}\}", lambda m: replacements[m.group(1)], template)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    viewer_path = output_dir / "viewer.html"
    ply_path = output_dir / "surfaces_preview.ply"
    report_path = output_dir / "viewer_summary.json"
    viewer_path.write_text(content, encoding="utf-8")
    _write_ply(ply_path, meshes, colors)
    report_path.write_text(json.dumps(_jsonable(summary), indent=2) + "\n")
    # Relative names survive the pipeline's atomic staging-directory rename.
    return {"viewer_html": viewer_path.name, "surface_preview_ply": ply_path.name,
            "viewer_summary": report_path.name, "surface_preview": summary}
