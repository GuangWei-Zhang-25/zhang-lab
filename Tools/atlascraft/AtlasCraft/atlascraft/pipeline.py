"""Callable AtlasCraft workflow; all geometry is computed by bounded local tools."""
from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import time

import numpy as np
from skimage.measure import find_contours

from .inputs import load_input


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _schema(name, description, properties=None):
    properties = properties or {}
    return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties,
                           'required': list(properties), 'additionalProperties': False}}}


PIPELINE_TOOLS = [
    _schema('validate_curated_references', 'Validate the human-curated categorical maps, identities, ordering and physical scale. Required first.'),
    _schema('extract_boundaries_and_assign_regions', 'Extract structured contours and attach the human-provided region IDs. Requires validated references; never invents region identities.'),
    _schema('align_interpolate_reconstruct', 'Call bounded registration, interpolation and labelled 3D reconstruction tools. Requires extracted boundaries.'),
    _schema('inspect_geometric_quality', 'Read measured alignment quality, unresolved tissue and corrections. Requires reconstruction.'),
    _schema('retry_alignment', 'Try an alternative bounded registration search; accept only if measured geometric quality improves. Maximum two agent retries.',
            {'max_shift_px': {'type': 'integer', 'minimum': 0, 'maximum': 64},
             'max_rotation_deg': {'type': 'number', 'minimum': 0, 'maximum': 20}}),
    _schema('export_atlas_and_viewer', 'Export the volume, evidence, audit report and offline 3D viewer. Requires quality inspection; output still awaits human anatomical review.')
]


class PipelineSession:
    def __init__(self, source, folder, options, progress):
        self.source, self.folder, self.options = source, folder, dict(options or {})
        self.progress = progress or (lambda stage, detail: None)
        self.stage = 0
        self.trace = []
        self.agent_notes = []
        self.retry_count = 0
        self.started = time.monotonic()

    def _notify(self, stage, detail):
        self.progress(stage, detail)

    def validate(self):
        if self.stage >= 1:
            return self.summary()
        self._notify('validate', 'Checking curated sections, region IDs and physical coordinates')
        self.data = load_input(self.source)
        write_json(self.folder / 'source_manifest.json', self.data.manifest)
        write_json(self.folder / 'input_hashes.json', self.data.hashes)
        np.savez_compressed(self.folder / 'original_anchors.npz', labels=self.data.labels,
                            positions_mm=self.data.positions_mm, spacing_xy_mm=self.data.spacing_xy_mm)
        self.stage = 1
        return self.summary()

    def boundaries(self):
        if self.stage < 1:
            raise ValueError('Validate the curated references first.')
        if self.stage >= 2:
            return self.summary()
        self._notify('boundaries', 'Extracting boundaries and attaching curated regional identities')
        records = []
        sx, sy = self.data.spacing_xy_mm
        # This is extraction from curated categorical maps, not unvalidated image segmentation.
        for i, (plane, z) in enumerate(zip(self.data.labels, self.data.positions_mm)):
            regions = []
            for ident in np.unique(plane):
                if ident == 0:
                    continue
                mask = plane == ident
                contours = find_contours(np.pad(mask, 1), .5)
                regions.append({'id': int(ident), 'name': self.data.label_names[str(int(ident))],
                                'pixel_count': int(mask.sum()),
                                'contours_xy_mm': [[[(float(p[1])-1)*sx, (float(p[0])-1)*sy] for p in c] for c in contours]})
            records.append({'section_index': i, 'z_mm': float(z), 'regions': regions})
        write_json(self.folder / 'boundaries.json', {'coordinate_frame': 'original input pixel-centre frame; contours in millimetres',
                                                    'identity_source': 'human-curated label registry', 'sections': records})
        self.stage = 2
        return self.summary()

    def reconstruct(self):
        if self.stage < 2:
            raise ValueError('Extract the curated boundaries and identities first.')
        if self.stage >= 3:
            return self.summary()
        from .core import build_volume
        self._notify('reconstruct', 'Aligning sections, checking corrections and reconstructing the volume')
        self.volume, self.evidence, self.metadata, self.aligned = build_volume(
            self.data.labels, self.data.positions_mm, self.data.spacing_xy_mm, self.options)
        self.stage = 3
        return self.summary()

    def audit(self):
        if self.stage < 3:
            raise ValueError('Reconstruct the volume first.')
        self._notify('audit', 'Checking category integrity, anchor fidelity and inferred tissue')
        source_ids = set(np.unique(self.data.labels))
        if not set(np.unique(self.volume)) <= source_ids | {0, 65535}:
            raise RuntimeError('Category integrity failed: an unsupported label entered the reconstruction.')
        indices = self.metadata['anchor_indices']
        if not np.array_equal(self.volume[indices], self.aligned):
            raise RuntimeError('Aligned anchor fidelity failed.')
        self.metadata['integrity'] = {'category_ids_preserved': True, 'aligned_anchors_exact': True,
                                      'original_anchors_preserved': True, 'original_labels_sha256': self.data.hashes['input_labels_sha256']}
        self.stage = max(self.stage, 4)
        return self.summary()

    def retry(self, args):
        if self.stage < 4 or self.stage >= 5:
            raise ValueError('Retry only after quality inspection and before export.')
        if self.retry_count >= 2:
            raise ValueError('The two agent retry limit has been reached.')
        if set(args) != {'max_shift_px', 'max_rotation_deg'}:
            raise ValueError('Retry needs exactly max_shift_px and max_rotation_deg.')
        shift, rotation = args['max_shift_px'], args['max_rotation_deg']
        if type(shift) is not int or not 0 <= shift <= 64 or type(rotation) not in (int, float) or not np.isfinite(rotation) or not 0 <= rotation <= 20:
            raise ValueError('Retry exceeds the conservative registration bounds.')
        from .core import build_volume
        self._notify('retry', 'Testing the agent’s bounded registration proposal')
        opts = dict(self.options, **args)
        candidate = build_volume(self.data.labels, self.data.positions_mm, self.data.spacing_xy_mm, opts)
        old_score = self.metadata.get('metrics', {}).get('mean_dice_after', 0.)
        new_score = candidate[2].get('metrics', {}).get('mean_dice_after', 0.)
        comparable = isinstance(old_score, (int, float)) and isinstance(new_score, (int, float))
        accepted = comparable and np.isfinite(old_score) and np.isfinite(new_score) and new_score > old_score + 1e-6
        log = {'kind': 'agent_registration_retry', 'parameters': args, 'accepted': bool(accepted),
               'score_before': old_score, 'score_candidate': new_score,
               'reason': 'Improved comparable geometric score.' if accepted else 'No comparable improvement; current result retained.'}
        previous = list(self.metadata.get('agent_corrections', []))
        if accepted:
            self.volume, self.evidence, self.metadata, self.aligned = candidate
            self.options = opts
        self.metadata['agent_corrections'] = previous + [log]
        self.retry_count += 1
        self.audit()
        return dict(self.summary(), candidate_accepted=bool(accepted))

    def summary(self):
        summary = {'stage': self.stage, 'completed': self.stage >= 5}
        if hasattr(self, 'data'):
            summary['input_sections'] = int(len(self.data.labels))
            summary['input_shape_zyx'] = list(self.data.labels.shape)
        if hasattr(self, 'metadata'):
            summary.update({'metrics': self.metadata.get('metrics', {}),
                            'warning_count': len(self.metadata.get('warnings', [])),
                            'output_voxels': int(self.volume.size),
                            'unknown_voxels': int(np.count_nonzero(self.volume == 65535)),
                            'agent_retries_remaining': 2 - self.retry_count})
        return summary

    def export(self):
        if self.stage < 4:
            raise ValueError('Inspect geometric quality before export.')
        if self.stage >= 5:
            return self.summary()
        from .viewer import write_viewer
        self._notify('export', 'Building the offline 3D viewer, data exports and review record')
        from . import __version__
        self.metadata.update({'schema': 'atlascraft-output-v2', 'software_version': __version__, 'name': self.data.manifest.get('name', 'AtlasCraft atlas'),
            'label_names': self.data.label_names, 'label_colors': self.data.label_colors,
            'coordinate_system': self.data.manifest.get('coordinate_system', 'user-provided section coordinates'),
            'sources': self.data.manifest.get('sources', []), 'requested_options': self.options,
            'human_review': {'input_curated': True, 'output_anatomically_accepted': False},
            'agent_notes': self.agent_notes,
            'volume_sha256': hashlib.sha256(self.volume.astype('<u2').tobytes()).hexdigest(),
            'interpretation': 'Alignment quality and interpolation are computational measures. Human experts must validate reconstructed anatomy. No missing anatomical identity is assigned by the agent.'})
        np.savez_compressed(self.folder / 'atlas.npz', labels=self.volume, evidence=self.evidence,
            z_coordinates_mm=self.metadata['z_coordinates_mm'], spacing_xy_mm=self.metadata['spacing_xy_mm'],
            origin_xy_mm=self.metadata.get('origin_xy_mm', [0., 0.]))
        np.savez_compressed(self.folder / 'aligned_anchors.npz', labels=self.aligned,
                            z_coordinates_mm=self.data.positions_mm, anchor_indices=self.metadata['anchor_indices'])
        # Standard NIfTI requires uniform Z spacing. Preserve nonuniform coordinates
        # exactly in NPZ; never silently regularize them in a medical image export.
        z = np.asarray(self.metadata['z_coordinates_mm'])
        if np.allclose(np.diff(z), np.diff(z)[0], rtol=1e-7, atol=1e-10):
            import nibabel as nib
            affine = np.diag([*self.data.spacing_xy_mm, float(z[1]-z[0]), 1.])
            affine[:3, 3] = [*self.metadata.get('origin_xy_mm', [0., 0.]), float(z[0])]
            img = nib.Nifti1Image(self.volume.transpose(2, 1, 0), affine)
            img.header.set_xyzt_units('mm')
            img.set_qform(affine, code=0)
            img.set_sform(affine, code=0)  # Generic atlas frame is not a known RAS anatomy frame.
            # Retain actual affine as sform aligned-anatomical, explicitly documented frame.
            img.set_sform(affine, code=2)
            nib.save(img, self.folder / 'atlas.nii.gz')
            self.metadata['nifti_export'] = 'Uniform Z; sform stores the user-defined image XYZ frame in mm. Anatomical RAS/LPS orientation is not established.'
        else:
            self.metadata['nifti_export'] = 'Omitted because Z is nonuniform. atlas.npz and viewer preserve exact physical coordinates.'
        artifacts = write_viewer(self.folder, self.volume, self.evidence, self.metadata,
                                 self.data.label_names, self.data.label_colors)
        self.metadata['viewer_artifacts'] = artifacts
        self.metadata['runtime_seconds'] = round(time.monotonic()-self.started, 3)
        write_json(self.folder / 'metadata.json', self.metadata)
        write_json(self.folder / 'report.json', {'status': 'awaiting_human_anatomical_review',
            'integrity': self.metadata['integrity'], 'metrics': self.metadata.get('metrics', {}),
            'warnings': self.metadata.get('warnings', []), 'corrections': self.metadata.get('corrections', []),
            'agent_corrections': self.metadata.get('agent_corrections', []), 'agent_notes': self.agent_notes})
        write_json(self.folder / 'review.json', {'output_anatomically_accepted': False,
            'volume_sha256': self.metadata['volume_sha256'], 'reviewer': None,
            'checks': ['Verify source orientation, scale and region registry.', 'Inspect all transformed anchors against original anchors.',
                       'Review interpolated boundaries, appearance/disappearance of regions and unresolved tissue.',
                       'Examine alignment warnings and accepted/rejected corrections.'], 'note': 'An AI agent cannot sign anatomical acceptance.'})
        self.stage = 5
        return self.summary()

    def call(self, name, args):
        if not isinstance(args, dict):
            raise ValueError('Tool arguments must be an object.')
        mapping = {'validate_curated_references': self.validate, 'extract_boundaries_and_assign_regions': self.boundaries,
                   'align_interpolate_reconstruct': self.reconstruct, 'inspect_geometric_quality': self.audit,
                   'export_atlas_and_viewer': self.export}
        if name == 'retry_alignment':
            result = self.retry(args)
        elif name in mapping and not args:
            result = mapping[name]()
        else:
            raise ValueError('Unknown tool or unsupported arguments.')
        self.trace.append({'tool': name, 'arguments': args, 'result': result})
        return result

    def finish_locally(self):
        for tool in PIPELINE_TOOLS:
            name = tool['function']['name']
            if name != 'retry_alignment':
                self.call(name, {})


def run_pipeline(source, output_dir, *, options=None, provider=None, progress=None):
    """Build an atlas from curated maps with optional API-driven tool orchestration.

    ``source`` is a JSON/ZIP path or inline manifest. ``provider`` is an
    HTTPProvider or an adapter implementing complete(messages, tools). The
    credential is held in that object and is never written to output files.
    Returns a JSON-safe artifact summary. Existing output directories are refused.
    """
    from .multiplane import is_multiplane, run_multiplane
    if is_multiplane(source):
        return run_multiplane(source, output_dir, options=options, provider=provider, progress=progress)
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise ValueError('Choose a new output directory; existing results are never overwritten.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='.atlascraft-', dir=destination.parent))
    session = PipelineSession(source, work, options, progress)
    try:
        if provider is not None:
            from .orchestration import orchestrate
            session._notify('agent', 'Connecting your selected agent to the AtlasCraft tools')
            try:
                orchestration = orchestrate(provider, PIPELINE_TOOLS, session.call,
                    context={'objective': 'Run the complete curated atlas reconstruction workflow. Inspect quality before export. Use bounded retries only when needed.'}, max_turns=12)
                session.agent_notes.append(orchestration)
            except Exception:
                # Provider exceptions can contain Authorization headers or echoed secrets.
                session.agent_notes.append({'status': 'provider_failed', 'message': 'Agent unavailable or incompatible. Local deterministic tools completed the workflow; no provider response body was saved.'})
        session.finish_locally()
        write_json(work / 'tool_trace.json', session.trace)
        # Record orchestration outcome even if the export tool ran before the agent stopped.
        session.metadata['agent_notes'] = session.agent_notes
        write_json(work / 'metadata.json', session.metadata)
        report = json.loads((work / 'report.json').read_text())
        report['agent_notes'] = session.agent_notes
        write_json(work / 'report.json', report)
        hashes = {str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(work.rglob('*')) if p.is_file()}
        write_json(work / 'checksums.json', hashes)
        work.rename(destination)
        return {'name': session.metadata['name'], 'output_dir': str(destination),
                'viewer': str(destination / 'viewer.html'), 'volume': str(destination / 'atlas.npz'),
                'report': str(destination / 'report.json'), 'shape_zyx': list(session.volume.shape),
                'status': 'awaiting_human_anatomical_review', 'agent_used': provider is not None}
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
