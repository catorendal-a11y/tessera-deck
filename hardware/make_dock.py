"""Desk dock for the GUITION JC1060P470C in its factory housing. Run inside Blender:

    blender -b --factory-startup --python-exit-code 1 -P hardware/make_dock.py -- [--out folder] [--slab 10] [--tilt 30]

The panel drops in from the top and leans back against two uprights; the dock is open behind it, so the raised
box on the back, the ports, the flex cables and the USB cable stay free.

Sizes come from the manufacturer's structure drawing (JC1060P470C_I_W_Y, 3-Structure_Diagram in
github.com/wegi1/ESP32P4-JC1060P470C-I_W_Y): outline 181.80 x 113.72, picture 155.01 x 86.72, slab 8.00 thick,
raised box 124.66 x 74.67 (centred, 8.38 deep, 20.38 over all), four posts with 2.00 holes on 166.00 x 99.00.
The uprights sit between the box and the corner posts. The diameter of the posts is not in the drawing.
All sizes are millimetres; the model is built in metres and exported at scale 1000.
"""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

parser = argparse.ArgumentParser()
parser.add_argument('--out', default=str(Path(__file__).resolve().parent))
parser.add_argument('--width', type=float, default=181.80, help='outline of the housed panel (seller data)')
parser.add_argument('--height', type=float, default=113.72, help='outline of the housed panel (seller data)')
parser.add_argument('--slab', type=float, default=8.0, help='thickness of the flat part (drawing: 8.00)')
parser.add_argument('--clearance', type=float, default=0.5, help='gap around the panel on each side')
parser.add_argument('--tilt', type=float, default=30.0, help='degrees the screen leans back from upright')
parser.add_argument('--box', type=float, default=124.66, help='width of the raised box on the back (drawing)')
parser.add_argument('--posts', type=float, default=166.0, help='distance between the corner posts (drawing)')
parser.add_argument('--post-d', type=float, default=6.0, help='ASSUMED: diameter of a corner post; measure it')
parser.add_argument('--depth', type=float, default=105.0, help='depth of the foot print')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

MM = 0.001
W, H, T, C = args.width, args.height, args.slab, args.clearance
WALL, LIP, BACK = 3.0, 2.5, 3.0          # side wall, front lip and back frame thickness
LIP_H, SIDE_H, FRAME_H = 6.0, 42.0, 82.0  # how far the lip, the side walls and the back frame reach up the panel
BASE, RIB = 3.0, 4.0
x_in, x_out = W / 2 + C, W / 2 + C + WALL
y_front, y_back = -C - LIP, T + C + BACK   # device frame: y = 0 is the glass, y = T the back of the slab


def box(name, x0, x1, y0, y1, z0, z1):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(((x1 - x0) * MM, (y1 - y0) * MM, (z1 - z0) * MM)), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(((x0 + x1) / 2 * MM, (y0 + y1) / 2 * MM, (z0 + z1) / 2 * MM)), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def union(target, other):
    mod = target.modifiers.new('bool', 'BOOLEAN')
    mod.operation, mod.solver, mod.object = 'UNION', 'MANIFOLD', other
    with bpy.context.temp_override(object=target, active_object=target, selected_objects=[target]):
        assert bpy.ops.object.modifier_apply(modifier=mod.name) == {'FINISHED'}
    bpy.data.objects.remove(other, do_unlink=True)


def keep(ob, point, normal):
    """Cut a convex part flat: keep what lies behind the plane and close the cut."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=Vector(point) * MM,
                                 plane_no=Vector(normal), clear_outer=True)
    edges = [e for e in cut['geom_cut'] if isinstance(e, bmesh.types.BMEdge)]
    if edges:
        bmesh.ops.edgeloop_fill(bm, edges=edges)
    assert all(e.is_manifold for e in bm.edges), f'{ob.name}: the cut was not closed'
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()


# --- the cradle, in the panel's own frame -------------------------------------------------------------------
u_in = args.box / 2 + 2.5                          # an upright starts clear of the raised box ...
u_out = args.posts / 2 - args.post_d / 2 - 1.0     # ... and ends clear of the corner post
assert u_out - u_in >= 8, 'no room for the uprights between the box and the posts'
cradle = [
    box('floor', -x_out, x_out, y_front, y_back, -40, 0),                  # thick: cut flat by the desk later
    box('lip', -x_out, x_out, y_front, -C, -2, LIP_H),
    box('upright_left', -u_out, -u_in, T + C, y_back, -2, FRAME_H),
    box('upright_right', u_in, u_out, T + C, y_back, -2, FRAME_H),
    box('wall_left', -x_out, -x_in, y_front, y_back, -2, SIDE_H),
    box('wall_right', x_in, x_out, y_front, y_back, -2, SIDE_H),
    box('return_left', -x_out, -x_in + 4, y_front, -C, -2, SIDE_H),          # 4 mm over the bezel, clear of the picture
    box('return_right', x_in - 4, x_out, y_front, -C, -2, SIDE_H),
]
for x in (-u_out + RIB / 2, -u_in - RIB / 2, u_in + RIB / 2, u_out - RIB / 2):
    cradle.append(box('rib', x - RIB / 2, x + RIB / 2, y_back - 0.5, y_back + 140, -40, FRAME_H))

# lean it back and lift it so that the pocket's rear corner sits one base thickness above the desk
tilt = Matrix.Rotation(-math.radians(args.tilt), 4, 'X')
corner = tilt @ Vector((0, (T + C) * MM, 0))
lift = Matrix.Translation(Vector((0, 0, BASE * MM - corner.z)))
front = min(((lift @ tilt) @ Vector((0, y * MM, z * MM))).y for y in (y_front, y_back) for z in (-40, 0, SIDE_H)) / MM
for ob in cradle:
    ob.data.transform(lift @ tilt)
# a base frame ties the ribs together and keeps the dock from tipping when a key is pressed
back = front + args.depth
cradle += [box('base_front', -x_out, x_out, front, front + 40, -5, BASE), box('base_back', -x_out, x_out, back - 14, back + 5, -5, BASE),
           box('base_left', -x_out, -x_out + 14, front, back + 5, -5, BASE), box('base_right', x_out - 14, x_out, front, back + 5, -5, BASE),
           box('base_rail_left', -u_out, -u_in, front, back + 5, -5, BASE), box('base_rail_right', u_in, u_out, front, back + 5, -5, BASE)]
for ob in cradle:                                          # every part is cut by the same two planes, so they overlap, never just touch
    keep(ob, (0, 0, 0), (0, 0, -1))                        # nothing below the desk
    keep(ob, (0, back, 0), (0, 1, 0))                      # nothing behind the foot print
dock = cradle[0]
dock.name = 'TesseraDock'
for ob in cradle[1:]:
    union(dock, ob)

bm = bmesh.new()
bm.from_mesh(dock.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)             # points the solver left 0.01 mm apart
bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges)
bmesh.ops.triangulate(bm, faces=bm.faces)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
assert all(e.is_manifold for e in bm.edges), 'the dock is not watertight'
bm.to_mesh(dock.data)
volume = bm.calc_volume()
bm.free()

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
for ob in bpy.context.scene.objects:
    ob.select_set(ob is dock)
bpy.context.view_layer.objects.active = dock
bpy.ops.wm.stl_export(filepath=str(out / 'tessera-dock.stl'), export_selected_objects=True, global_scale=1000.0)
bpy.ops.wm.save_as_mainfile(filepath=str(out / 'tessera-dock.blend'))
size = dock.dimensions / MM
print(f'@@JSON@@ {{"size_mm": [{size.x:.1f}, {size.y:.1f}, {size.z:.1f}], "tris": {len(dock.data.polygons)}, '
      f'"volume_cm3": {volume * 1e6:.1f}, "pla_grams": {volume * 1e6 * 1.24:.0f}}}')
