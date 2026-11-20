"""Writes the console as a fine OBJ with the exact surface normals, for make_render.py. Run with FreeCAD:

    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" hardware\\scripts\\export_render_mesh.py

Reads guition/tessera-enclosure.FCStd (make_enclosure.py writes it) and writes, to render/:
    tessera-enclosure-render.obj   the body, millimetres; shared vertices, a normal per corner from the CAD surface
    tessera-enclosure-render.json  where the glass is, the foot centres and the cable arch, millimetres
The normals come from the surfaces themselves, so rounds shade smooth and flat faces stay flat.
"""
import json
import os
from pathlib import Path

import FreeCAD as App

HARDWARE = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('TESSERA_OUT') or HARDWARE / 'guition')
HERE = Path(os.environ.get('TESSERA_OUT') or HARDWARE / 'render')
DEFLECTION = 0.01          # mm the facets may stray from the surface

doc = App.openDocument(str(SOURCE / 'tessera-enclosure.FCStd'))
body = doc.getObject('Enclosure').Shape
body.tessellate(DEFLECTION)                      # meshes the whole solid once, so neighbouring faces share their edges

points, normals, faces, index = [], [], [], {}


def vertex(p):
    key = (round(p.x, 4), round(p.y, 4), round(p.z, 4))
    if key not in index:
        index[key] = len(points)
        points.append(key)
    return index[key]


for face in body.Faces:
    corners, triangles = face.tessellate(DEFLECTION)
    exact = []
    for p in corners:
        u, v = face.Surface.parameter(p)
        exact.append(face.normalAt(u, v))
    for a, b, c in triangles:
        side = (corners[b] - corners[a]).cross(corners[c] - corners[a])
        if side.Length < 1e-12:
            continue
        if side.dot(exact[a] + exact[b] + exact[c]) < 0:      # wind each facet the way its surface faces
            b, c = c, b
        row = []
        for k in (a, b, c):
            normals.append(exact[k])
            row.append((vertex(corners[k]) + 1, len(normals)))
        faces.append(row)

with open(HERE / 'tessera-enclosure-render.obj', 'w', encoding='ascii') as out:
    out.write('# Tessera console, millimetres, exact normals (export_render_mesh.py)\no Enclosure\n')
    out.writelines(f'v {x:.4f} {y:.4f} {z:.4f}\n' for x, y, z in points)
    out.writelines(f'vn {n.x:.5f} {n.y:.5f} {n.z:.5f}\n' for n in normals)
    out.write('s 1\n')
    out.writelines('f ' + ' '.join(f'{v}//{n}' for v, n in row) + '\n' for row in faces)

# --- where things are, for the parts make_render.py adds ----------------------------------------------------
panel = doc.getObject('PanelReference').Shape
glass = max((f for f in panel.Faces if f.Surface.TypeId == 'Part::GeomPlane'), key=lambda f: f.Area)
centre = glass.CenterOfMass
u, v = glass.Surface.parameter(centre)
out_of_glass = glass.normalAt(u, v)
up = max((e for e in glass.Edges), key=lambda e: abs((e.Vertexes[-1].Point - e.Vertexes[0].Point).z))
up = up.Vertexes[-1].Point - up.Vertexes[0].Point
up = up if up.z > 0 else -up
up.normalize()
across = up.cross(out_of_glass)
across.normalize()


def circles(name):
    sketch = doc.getObject(name)
    return [[e.Curve.Center.x, e.Curve.Center.y, e.Curve.Center.z] for e in sketch.Shape.Edges if e.Curve.TypeId == 'Part::GeomCircle']


arch = doc.getObject('CableArch').Shape.BoundBox
box = body.BoundBox
info = {
    'glass_centre': [centre.x, centre.y, centre.z], 'out_of_glass': [out_of_glass.x, out_of_glass.y, out_of_glass.z],
    'up': [up.x, up.y, up.z], 'across': [across.x, across.y, across.z], 'glass_area': glass.Area,
    'feet': circles('FootCentres'),
    'arch': {'min': [arch.XMin, arch.YMin, arch.ZMin], 'max': [arch.XMax, arch.YMax, arch.ZMax]},
    'box': {'min': [box.XMin, box.YMin, box.ZMin], 'max': [box.XMax, box.YMax, box.ZMax]},
}
(HERE / 'tessera-enclosure-render.json').write_text(json.dumps(info, indent=1), encoding='utf-8')
print(f'RESULT vertices {len(points)}, corners {len(normals)}, facets {len(faces)}, glass {glass.Area:.1f} mm2, '
      f'feet {len(info["feet"])}, size {box.XLength:.1f} x {box.YLength:.1f} x {box.ZLength:.1f}')
