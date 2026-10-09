"""Validated local inputs. Input files are data, never executable instructions."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import json
import re
import zipfile

import numpy as np
from PIL import Image

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_INPUT_VOXELS = 16_777_216


@dataclass
class AtlasInput:
    labels: np.ndarray
    positions_mm: np.ndarray
    spacing_xy_mm: list
    label_names: dict
    label_colors: dict
    manifest: dict
    hashes: dict


def _read_json(raw):
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError('Input exceeds 256 MB.')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('The manifest must be valid UTF-8 JSON.') from exc


def _safe_relative(name):
    p = Path(name)
    if not isinstance(name, str) or not name or p.is_absolute() or '..' in p.parts or '\\' in name:
        raise ValueError('Section paths must stay inside the input folder.')
    return p


def _categorical(array):
    a = np.asarray(array)
    if a.ndim != 2 or min(a.shape) < 8 or max(a.shape) > 2048:
        raise ValueError('Each label map must be a 2D grid, 8–2048 pixels per side.')
    if a.dtype.kind not in 'uib' or a.min() < 0 or a.max() > 65535:
        raise ValueError('Label maps must contain integer IDs from 0 to 65535, without antialiasing.')
    return a.astype(np.uint16)


def _image_labels(raw, suffix, colors):
    if suffix == '.npy':
        return _categorical(np.load(io.BytesIO(raw), allow_pickle=False))
    if suffix not in {'.png', '.tif', '.tiff'}:
        raise ValueError('Section files must be PNG, TIFF or NPY.')
    with Image.open(io.BytesIO(raw)) as image:
        if image.width > 2048 or image.height > 2048 or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Use one 8–2048 pixel label image per section.')
        # Indexed PNG pixels are categorical IDs; RGB is explicitly palette-mapped.
        a = np.asarray(image)
    if a.ndim == 3:
        if a.shape[2] not in {3, 4} or (a.shape[2] == 4 and np.any(a[..., 3] != 255)):
            raise ValueError('RGB label maps must have no transparency.')
        rgb = a[..., :3].astype(np.uint32)
        encoded = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
        palette = {int(color[1:], 16): int(ident) for ident, color in colors.items()}
        if len(palette) != len(colors):
            raise ValueError('RGB import requires a unique color for every label ID.')
        if not set(map(int, np.unique(encoded))) <= palette.keys():
            raise ValueError('RGB pixels include colors absent from the label registry. Export flat colors without antialiasing.')
        out = np.zeros(encoded.shape, dtype=np.uint16)
        for color in np.unique(encoded):
            out[encoded == color] = palette[int(color)]
        a = out
    return _categorical(a)


def load_input(source):
    """Read a manifest dict, local JSON path, or ZIP containing manifest.json.

    Sections require explicit physical Z positions and common XY pixel sampling.
    Labels 0 and 65535 mean outside and unresolved tissue respectively.
    """
    hashes = {}
    archive = None
    if isinstance(source, dict):
        manifest = source
        def read_file(name):
            raise ValueError('Inline requests must contain section labels arrays, not local file paths.')
    else:
        path = Path(source).resolve()
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('Input exceeds 256 MB.')
        raw = path.read_bytes()
        hashes['input_file_sha256'] = hashlib.sha256(raw).hexdigest()
        if path.suffix.lower() == '.zip':
            archive = zipfile.ZipFile(io.BytesIO(raw))
            infos = archive.infolist()
            if len(infos) > 512 or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
                raise ValueError('Archive has too many files or exceeds 256 MB when expanded.')
            names = [i.filename for i in infos]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate ZIP entries are not supported.')
            for item in infos:
                _safe_relative(item.filename)
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('ZIP symbolic links are not allowed.')
            if 'manifest.json' not in names:
                raise ValueError('Place manifest.json at the top level of the ZIP.')
            manifest = _read_json(archive.read('manifest.json'))
            def read_file(name):
                _safe_relative(name)
                try:
                    return archive.read(name)
                except KeyError as exc:
                    raise ValueError('A section file named in the manifest is missing.') from exc
        else:
            manifest = _read_json(raw)
            def read_file(name):
                candidate = (path.parent / _safe_relative(name)).resolve()
                if not candidate.is_relative_to(path.parent):
                    raise ValueError('A section resolves outside the input directory.')
                if candidate.stat().st_size > MAX_ARCHIVE_BYTES:
                    raise ValueError('Section exceeds 256 MB.')
                return candidate.read_bytes()
    try:
        if not isinstance(manifest, dict) or manifest.get('schema') != 'atlascraft-input-v1':
            raise ValueError('Use the atlascraft-input-v1 manifest schema from the example.')
        if manifest.get('curated') is not True:
            raise ValueError('Set curated:true only after manually reviewing the section identities, orientation and scale.')
        allowed = {'schema', 'name', 'curated', 'coordinate_system', 'spacing_xy_mm', 'sections', 'labels', 'sources', 'description'}
        if set(manifest) - allowed:
            raise ValueError('Manifest contains unsupported fields; see the input template.')
        name = manifest.get('name', 'Untitled atlas')
        if not isinstance(name, str) or not 1 <= len(name) <= 250:
            raise ValueError('Atlas name must be 1–250 characters.')
        spacing = np.asarray(manifest.get('spacing_xy_mm', []), dtype=float)
        if spacing.shape != (2,) or not np.all(np.isfinite(spacing)) or np.any(spacing <= 0):
            raise ValueError('spacing_xy_mm must contain two positive finite millimetre values, X then Y.')
        label_names = {'0': 'Outside', '65535': 'Unresolved tissue'}
        colors = {'0': '#000000', '65535': '#c6c7cf'}
        registry = manifest.get('labels', [])
        if not isinstance(registry, list) or len(registry) > 256:
            raise ValueError('Provide at most 256 label registry entries.')
        seen = set()
        for entry in registry:
            ident = entry.get('id')
            if type(ident) is not int or not 0 <= ident <= 65535 or ident in seen:
                raise ValueError('Registry IDs must be unique integers, 0–65535.')
            seen.add(ident)
            label_name = entry.get('name')
            if not isinstance(label_name, str) or not 1 <= len(label_name) <= 250:
                raise ValueError('Every registry label needs a name, up to 250 characters.')
            color = entry.get('color')
            if color is not None and (not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)):
                raise ValueError('Label colors must be #RRGGBB.')
            label_names[str(ident)] = label_name
            if color:
                colors[str(ident)] = color.lower()
        sections = manifest.get('sections')
        if not isinstance(sections, list) or not 2 <= len(sections) <= 128:
            raise ValueError('Provide 2–128 ordered curated sections.')
        arrays, positions, total = [], [], 0
        for i, section in enumerate(sections):
            if not isinstance(section, dict) or set(section) - {'name', 'z_mm', 'file', 'labels'}:
                raise ValueError('Each section accepts name, z_mm and exactly one of file or labels.')
            if ('file' in section) == ('labels' in section):
                raise ValueError('Every section needs exactly one file or labels array.')
            z = section.get('z_mm')
            if isinstance(z, bool) or not isinstance(z, (int, float)) or not np.isfinite(z):
                raise ValueError('Every section needs a finite z_mm coordinate.')
            positions.append(float(z))
            if 'labels' in section:
                arr = _categorical(section['labels'])
            else:
                raw = read_file(section['file'])
                hashes[f'section_{i:03d}_file_sha256'] = hashlib.sha256(raw).hexdigest()
                arr = _image_labels(raw, Path(section['file']).suffix.lower(), colors)
            if arrays and arr.shape != arrays[0].shape:
                raise ValueError('All sections need the same canvas size and XY scale; AtlasCraft aligns their contents.')
            total += arr.size
            if total > MAX_INPUT_VOXELS:
                raise ValueError('Input exceeds 16,777,216 label pixels. Crop or resample curated maps first.')
            arrays.append(arr)
        if not np.all(np.diff(positions) > 0):
            raise ValueError('Sections must be listed in strictly increasing physical Z order; no automatic reordering.')
        stack = np.stack(arrays)
        missing = set(map(int, np.unique(stack))) - {0, 65535} - seen
        if missing:
            raise ValueError(f'Add label names for these IDs: {sorted(missing)[:20]}')
        clean_manifest = json.loads(json.dumps(manifest))
        # Never duplicate large arrays in reports or exports.
        for i, section in enumerate(clean_manifest['sections']):
            section.pop('labels', None)
            section['sha256'] = hashlib.sha256(arrays[i].astype('<u2').tobytes()).hexdigest()
        hashes['input_labels_sha256'] = hashlib.sha256(stack.astype('<u2').tobytes()).hexdigest()
        return AtlasInput(stack, np.asarray(positions), spacing.tolist(), label_names, colors, clean_manifest, hashes)
    finally:
        if archive:
            archive.close()
