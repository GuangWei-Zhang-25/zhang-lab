"""Small synthetic atlas; no third-party anatomical images are distributed."""
from pathlib import Path
import json
import numpy as np
from scipy.ndimage import rotate, shift
from PIL import Image


def demo_manifest():
    y, x = np.mgrid[:64, :64]
    sections = []
    for i, (dy, dx, angle) in enumerate([(0, 0, 0), (4, -5, 6), (-3, 4, -5), (3, 2, 3), (-2, -3, -4)]):
        radius = 22 - abs(i-2)*1.5
        a = np.zeros((64, 64), np.uint16)
        a[((x-32)/radius)**2 + ((y-31)/(radius*.85))**2 < 1] = 1
        a[((x-25)/8)**2 + ((y-32)/10)**2 < 1] = 2
        a[((x-39)/7)**2 + ((y-31)/9)**2 < 1] = 3
        a[((x-32)/3)**2 + ((y-21)/3)**2 < 1] = 65535
        a = shift(rotate(a, angle, reshape=False, order=0), (dy, dx), order=0)
        sections.append({'name': f'Curated section {i+1}', 'z_mm': i*.4, 'labels': a.tolist()})
    return {'schema': 'atlascraft-input-v1', 'name': 'AtlasCraft synthetic demonstration', 'curated': True,
            'coordinate_system': 'Synthetic image X/Y and section Z in millimetres; not real anatomy',
            'spacing_xy_mm': [.04, .04], 'sections': sections,
            'labels': [{'id': 0, 'name': 'Outside', 'color': '#000000'},
                       {'id': 1, 'name': 'Outer compartment', 'color': '#78bbae'},
                       {'id': 2, 'name': 'Compartment A', 'color': '#ea947d'},
                       {'id': 3, 'name': 'Compartment B', 'color': '#e2bf64'},
                       {'id': 65535, 'name': 'Unresolved tissue', 'color': '#b8b3c7'}],
            'sources': [{'citation': 'Procedural geometric demonstration created for AtlasCraft. No biological validation implied.',
                         'license': 'Synthetic example; no third-party atlas source.'}]}


def write_demo(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = demo_manifest()
    for i, section in enumerate(manifest['sections']):
        filename = f'section_{i+1:02d}.png'
        Image.fromarray(np.asarray(section.pop('labels'), np.uint16)).save(folder / filename)
        section['file'] = filename
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return folder / 'manifest.json'
