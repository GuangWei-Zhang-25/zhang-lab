"""Integrate curated series with expert-supplied placement in a common 3D frame.

This module does not estimate anatomical orientation. Contradictory source labels
remain unresolved; agreement is a consistency measure, not proof of correctness.
"""
from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import zipfile

import numpy as np

from .inputs import MAX_ARCHIVE_BYTES, _safe_relative


def is_multiplane(source):
    if isinstance(source, dict):
        return source.get('schema') == 'atlascraft-multiplane-v1'
    p = Path(source)
    if p.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Input exceeds 256 MB.')
    if p.suffix.lower() == '.zip':
        with zipfile.ZipFile(p) as z:
            info = z.getinfo('manifest.json')
            if info.file_size > MAX_ARCHIVE_BYTES:
                raise ValueError('Manifest exceeds 256 MB.')
            m = json.loads(z.read('manifest.json'))
    else:
        m = json.loads(p.read_text())
    return isinstance(m, dict) and m.get('schema') == 'atlascraft-multiplane-v1'


def _rigid_matrix(value):
    m = np.asarray(value, dtype=float)
    if m.shape != (4, 4) or not np.all(np.isfinite(m)) or not np.allclose(m[3], [0, 0, 0, 1]):
        raise ValueError('Every series needs a finite 4×4 local-to-world transform.')
    if not np.allclose(m[:3, :3].T @ m[:3, :3], np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(m[:3, :3]), 1, atol=1e-6):
        raise ValueError('Series transforms must be proper rigid rotations and translations in millimetres, without reflection or scale.')
    return m


def fuse_volumes(volumes, metadata, transforms, shape_zyx, spacing_xyz_mm, origin_xyz_mm):
    """Nearest-label sampling into a supplied world grid; disagreements ->65535."""
    shape = np.asarray(shape_zyx)
    spacing, origin = np.asarray(spacing_xyz_mm, float), np.asarray(origin_xyz_mm, float)
    if shape.shape != (3,) or shape.dtype.kind not in 'ui' or np.any(shape < 2) or np.any(shape > 2048) or np.prod(shape) > 16_777_216:
        raise ValueError('World grid must have 2–2048 voxels per axis and at most 16,777,216 voxels.')
    if spacing.shape != (3,) or origin.shape != (3,) or not np.all(np.isfinite(spacing)) or not np.all(np.isfinite(origin)) or np.any(spacing <= 0):
        raise ValueError('World grid needs positive finite XYZ spacing and finite XYZ origin.')
    if not 2 <= len(volumes) <= 8 or len(metadata) != len(volumes) or len(transforms) != len(volumes):
        raise ValueError('Fuse 2–8 reconstructed series with one transform each.')
    result = np.zeros(tuple(shape), np.uint16)
    coverage = np.zeros(tuple(shape), np.uint8)
    conflicts = np.zeros(tuple(shape), bool)
    source_unknown = np.zeros(tuple(shape), bool)
    yy, xx = np.mgrid[:shape[1], :shape[2]]
    world = np.ones((4, xx.size), float)
    world[0] = origin[0] + xx.ravel()*spacing[0]
    world[1] = origin[1] + yy.ravel()*spacing[1]
    for volume, meta, transform in zip(volumes, metadata, transforms):
        inv = np.linalg.inv(_rigid_matrix(transform))
        zs = np.asarray(meta['z_coordinates_mm'])
        sx, sy = meta['spacing_xy_mm']
        ox, oy = meta['origin_xy_mm']
        for k in range(shape[0]):
            world[2] = origin[2] + k*spacing[2]
            local = inv @ world
            x = (local[0]-ox)/sx
            y = (local[1]-oy)/sy
            valid = (x >= -.5) & (x < volume.shape[2]-.5) & (y >= -.5) & (y < volume.shape[1]-.5) & (local[2] >= zs[0]-1e-9) & (local[2] <= zs[-1]+1e-9)
            idx = np.flatnonzero(valid)
            if not len(idx):
                continue
            zi = np.searchsorted(zs, local[2, idx]).clip(0, len(zs)-1)
            left = np.maximum(zi-1, 0)
            zi = np.where(abs(zs[left]-local[2, idx]) <= abs(zs[zi]-local[2, idx]), left, zi)
            sampled = volume[zi, np.floor(y[idx]+.5).astype(int).clip(0, volume.shape[1]-1), np.floor(x[idx]+.5).astype(int).clip(0, volume.shape[2]-1)]
            idx, sampled = idx[sampled != 0], sampled[sampled != 0]
            current = result[k].ravel()
            coverage[k].ravel()[idx] += 1
            source_unknown[k].ravel()[idx[sampled == 65535]] = True
            disagreement = (current[idx] != 0) & (current[idx] != sampled) & (current[idx] != 65535) & (sampled != 65535)
            conflicts[k].ravel()[idx[disagreement]] = True
            # Keep the first named vote until all series have been compared.
            # An unresolved vote must not hide later named disagreements.
            empty = (current[idx] == 0) & (sampled != 65535)
            current[idx[empty]] = sampled[empty]
    result[conflicts | source_unknown] = 65535
    evidence = np.zeros(tuple(shape), np.uint8)
    evidence[coverage == 1] = 1
    evidence[coverage >= 2] = 2
    evidence[conflicts] = 3
    evidence[source_unknown & ~conflicts] = 4
    return result, evidence, coverage, conflicts


def run_multiplane(source, output_dir, *, options=None, provider=None, progress=None):
    from .pipeline import run_pipeline, write_json
    from .viewer import write_viewer
    notify = progress or (lambda *args: None)
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise ValueError('Choose a new output directory; existing results are never overwritten.')
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='.atlascraft-multiplane-', dir=target.parent))
    try:
        if isinstance(source, dict):
            manifest, base = source, None
        elif Path(source).suffix.lower() == '.zip':
            base = work / '_inputs'
            base.mkdir()
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                if len(infos) > 512 or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES or len({i.filename for i in infos}) != len(infos):
                    raise ValueError('Invalid or oversized multi-plane archive.')
                for info in infos:
                    rel = _safe_relative(info.filename)
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('ZIP symbolic links are not allowed.')
                    destination = base / rel
                    if info.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(info))
            manifest = json.loads((base / 'manifest.json').read_text())
        else:
            base = Path(source).resolve().parent
            manifest = json.loads(Path(source).read_text())
        if manifest.get('schema') != 'atlascraft-multiplane-v1' or manifest.get('placements_reviewed') is not True:
            raise ValueError('Multi-plane integration requires placements_reviewed:true and expert-supplied world transforms.')
        series = manifest.get('series', [])
        if not isinstance(series, list) or not 2 <= len(series) <= 8:
            raise ValueError('Provide 2–8 complementary atlas series.')
        grid = manifest.get('world_grid', {})
        volumes, metas, transforms, names, colors = [], [], [], {}, {}
        for i, item in enumerate(series):
            transform = _rigid_matrix(item.get('local_to_world'))
            transform = transform.tolist()
            source_manifest = item.get('input')
            if isinstance(source_manifest, str):
                if base is None:
                    raise ValueError('Inline multi-plane requests require inline series inputs.')
                source_manifest = (base / _safe_relative(source_manifest)).resolve()
                if not source_manifest.is_relative_to(base.resolve()):
                    raise ValueError('Series manifest must remain inside the input directory.')
            elif not isinstance(source_manifest, dict):
                raise ValueError('Every series needs an input manifest.')
            if is_multiplane(source_manifest):
                raise ValueError('Nested multi-plane collections are not supported.')
            notify('series', f'Reconstructing complementary series {i+1} of {len(series)}')
            result = run_pipeline(source_manifest, work / f'series_{i+1:02d}', options=options, provider=provider, progress=progress)
            with np.load(result['volume'], allow_pickle=False) as z:
                volumes.append(z['labels'])
            meta = json.loads((Path(result['output_dir']) / 'metadata.json').read_text())
            for ident, name in meta['label_names'].items():
                if ident in names and names[ident] != name:
                    raise ValueError('All series must use one manually reconciled region registry; the same ID has different names.')
                names[ident] = name
            colors.update(meta['label_colors'])
            metas.append(meta)
            transforms.append(transform)
        notify('fusion', 'Checking agreement across anatomical planes in the reviewed common frame')
        volume, evidence, coverage, conflicts = fuse_volumes(volumes, metas, transforms,
            grid.get('shape_zyx'), grid.get('spacing_xyz_mm'), grid.get('origin_xyz_mm'))
        spacing, origin = grid['spacing_xyz_mm'], grid['origin_xyz_mm']
        zcoords = (origin[2] + np.arange(volume.shape[0])*spacing[2]).tolist()
        count = int(conflicts.sum())
        from . import __version__
        metadata = {'schema': 'atlascraft-output-v2', 'software_version': __version__, 'name': manifest.get('name', 'AtlasCraft multi-plane atlas'),
            'method': 'expert-placed complementary series; nearest-label common-grid sampling; conservative agreement fusion',
            'z_coordinates_mm': zcoords, 'spacing_xy_mm': spacing[:2], 'origin_xy_mm': origin[:2],
            'shape_zyx': list(volume.shape), 'anchor_indices': [], 'label_names': names, 'label_colors': colors,
            'sources': [source for m in metas for source in m.get('sources', [])],
            'transforms': transforms, 'corrections': [],
            'warnings': [f'{count} voxels have conflicting regional identities across series and remain unresolved.'] if count else [],
            'metrics': {'input_series': len(series), 'output_voxels': int(volume.size), 'conflicting_voxels': count,
                        'overlap_voxels': int((coverage >= 2).sum()), 'unknown_voxels': int((volume == 65535).sum())},
            'evidence_codes': {'0': 'No non-background source support', '1': 'One reconstructed series', '2': 'Multiple agreeing reconstructed series', '3': 'Conflicting regional labels across series', '4': 'At least one source marks unresolved tissue'},
            'human_review': {'input_curated': True, 'placements_reviewed': True, 'output_anatomically_accepted': False},
            'volume_sha256': hashlib.sha256(volume.astype('<u2').tobytes()).hexdigest(),
            'limitations': ['Placements are supplied and reviewed by experts; no automatic anatomical orientation or cross-plane registration is claimed.',
                            'Common-grid resampling is categorical nearest-neighbour. Individual aligned source anchors remain exact in the per-series outputs.',
                            'Overlapping disagreement is retained as 65535; no majority vote or agent-invented identity resolves it.']}
        np.savez_compressed(work / 'atlas.npz', labels=volume, evidence=evidence, z_coordinates_mm=zcoords,
                            spacing_xy_mm=spacing[:2], origin_xy_mm=origin[:2])
        np.savez_compressed(work / 'crossplane_evidence.npz', coverage_count=coverage, conflicts=conflicts)
        metadata['viewer_artifacts'] = write_viewer(work, volume, evidence, metadata, names, colors)
        write_json(work / 'metadata.json', metadata)
        write_json(work / 'report.json', {'status': 'awaiting_human_anatomical_review', 'metrics': metadata['metrics'], 'warnings': metadata['warnings'], 'limitations': metadata['limitations']})
        write_json(work / 'review.json', {'output_anatomically_accepted': False, 'reviewer': None, 'volume_sha256': metadata['volume_sha256'], 'note': 'Review common-frame placement, per-series anchors and cross-plane conflicts. The agent cannot approve anatomy.'})
        if (work / '_inputs').exists():
            shutil.rmtree(work / '_inputs')
        write_json(work / 'checksums.json', {str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(work.rglob('*')) if p.is_file()})
        work.rename(target)
        return {'name': metadata['name'], 'output_dir': str(target), 'viewer': str(target / 'viewer.html'),
                'volume': str(target / 'atlas.npz'), 'report': str(target / 'report.json'),
                'shape_zyx': list(volume.shape), 'status': 'awaiting_human_anatomical_review', 'agent_used': provider is not None}
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
