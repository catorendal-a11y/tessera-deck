"""HD product renders of the Tessera console with the panel in it. Run with Blender 5.2 or newer:

    blender -b --factory-startup --python-exit-code 1 -P hardware/make_render.py -- [--res 3840x2160] [--samples 512]
            [--shots hero,user,side,back,detail] [--screen docs/images/panel-main.png] [--color 2d3034] [--no-render]

Needs tessera-enclosure-render.obj and .json, which export_render_mesh.py writes from the CAD model (FreeCAD).
Adds the panel in its factory housing from the manufacturer's sizes (outline 181.80 x 113.72, picture 155.01 x 86.72,
slab 8.00, raised box 124.66 x 74.67 that ends 16.38 behind the glass, posts on 166.00 x 99.00) with a real panel
screen as the picture, four 10 mm rubber feet, a USB-C cable out through the arch, a studio and five cameras.
Saves tessera-console.blend and renders/<shot>.png next to this script. Built in metres; the CAD sizes are mm.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--out', default=str(HERE))
parser.add_argument('--res', default='3840x2160')
parser.add_argument('--samples', type=int, default=512)
parser.add_argument('--shots', default='hero,user,side,back,detail')
parser.add_argument('--screen', default=str(HERE.parent / 'docs' / 'images' / 'panel-main.png'))
parser.add_argument('--color', default='2d3034', help='the printed shell, sRGB hex')
parser.add_argument('--no-render', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

MM = 0.001
W, H, T = 181.80, 113.72, 8.00                     # the housed panel (drawing)
PIC_W, PIC_H = 155.01, 86.72                       # the picture, centred
BOX_W, BOX_H, BOX_DEEP, JACK_DEEP = 124.66, 74.67, 16.38, 20.38
POSTS_X, POSTS_Z, POST_D, POST_END = 166.0, 99.0, 4.6, 13.0
GLASS, CORNER = 0.7, 3.0                           # cover glass thickness, corner radius of the housing
DESK = -2.0                                        # 3 mm feet, 1 mm of them in the recess
CABLE_R = 2.0

info = json.loads((HERE / 'tessera-enclosure-render.json').read_text(encoding='utf-8'))
across, out_of_glass, up = (Vector(info[k]) for k in ('across', 'out_of_glass', 'up'))
into = -out_of_glass
origin = Vector(info['glass_centre']) - up * (H / 2)
# Panel frame, as in make_enclosure.py: x across, y into the shell from the glass, z up the panel; mm in, metres out.
FRAME = Matrix.Scale(MM, 4) @ Matrix.Translation(origin) @ Matrix((
    (across.x, into.x, up.x, 0), (across.y, into.y, up.y, 0), (across.z, into.z, up.z, 0), (0, 0, 0, 1)))
WORLD_MM = Matrix.Scale(MM, 4)


def srgb(hex_):
    def channel(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (channel(hex_[0:2]), channel(hex_[2:4]), channel(hex_[4:6]), 1.0)


def principled(name, color, roughness, metallic=0.0):
    mat = bpy.data.materials.new(name)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = srgb(color) if isinstance(color, str) else color
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    return mat, bsdf


def link(mat, a, b):
    mat.node_tree.links.new(a, b)


def node(mat, kind, **values):
    n = mat.node_tree.nodes.new(kind)
    for key, value in values.items():
        if key in n.inputs:
            n.inputs[key].default_value = value
        else:
            setattr(n, key, value)
    return n


def shell_material():
    """Matte PLA, printed standing up: 0.2 mm layer lines across Z and softly rounded edges at render time."""
    mat, bsdf = principled('Shell PLA', args.color, 0.58)
    bsdf.inputs['Specular IOR Level'].default_value = 0.45
    coord = node(mat, 'ShaderNodeTexCoord')
    wave = node(mat, 'ShaderNodeTexWave', bands_direction='Z', wave_profile='SIN', Scale=0.314 / 0.0002, Distortion=0.0)
    link(mat, coord.outputs['Object'], wave.inputs['Vector'])
    bevel = node(mat, 'ShaderNodeBevel', Radius=0.00035, samples=8)
    bump = node(mat, 'ShaderNodeBump', Strength=0.6, Distance=0.00006)
    link(mat, wave.outputs['Fac'], bump.inputs['Height'])
    link(mat, bevel.outputs['Normal'], bump.inputs['Normal'])
    link(mat, bump.outputs['Normal'], bsdf.inputs['Normal'])
    noise = node(mat, 'ShaderNodeTexNoise', Scale=900.0, Detail=2.0)
    ramp = node(mat, 'ShaderNodeMapRange', **{'To Min': 0.52, 'To Max': 0.64})
    link(mat, coord.outputs['Object'], noise.inputs['Vector'])
    link(mat, noise.outputs['Fac'], ramp.inputs['Value'])
    link(mat, ramp.outputs['Result'], bsdf.inputs['Roughness'])
    return mat


def glass_material(screen):
    """Black cover glass; the panel's own screen shows through it inside the picture area (the UVs), black outside."""
    mat, bsdf = principled('Cover glass and screen', (0.004, 0.0045, 0.005, 1), 0.035)
    bsdf.inputs['IOR'].default_value = 1.52
    image = node(mat, 'ShaderNodeTexImage', extension='CLIP', interpolation='Cubic')
    image.image = bpy.data.images.load(str(screen))
    image.image.pack()
    link(mat, node(mat, 'ShaderNodeUVMap').outputs['UV'], image.inputs['Vector'])
    link(mat, image.outputs['Color'], bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value = 1.6
    return mat


def mesh_object(name, bm, material, smooth_angle=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material)
    if smooth_angle is not None:
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(smooth_angle))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def bevel(ob, width_mm, segments=3):
    mod = ob.modifiers.new('Bevel', 'BEVEL')
    mod.width = width_mm * MM
    mod.segments = segments
    mod.limit_method = 'ANGLE'
    mod.harden_normals = True
    return mod


def rounded_rect(x0, x1, z0, z1, r, steps=12):
    points = []
    for cx, cz, start in ((x1 - r, z0 + r, -90), (x1 - r, z1 - r, 0), (x0 + r, z1 - r, 90), (x0 + r, z0 + r, 180)):
        for i in range(steps + 1):
            a = math.radians(start + 90 * i / steps)
            points.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    return points


def prism(outline, y0, y1, uv=None):
    """A solid in the panel frame: the outline (x, z) between y0 and y1. uv(x, z) maps every corner, if given."""
    bm = bmesh.new()
    face = bm.faces.new([bm.verts.new((x, y0, z)) for x, z in outline])
    top = bmesh.ops.extrude_face_region(bm, geom=[face])['geom']
    bmesh.ops.translate(bm, vec=(0, y1 - y0, 0), verts=[v for v in top if isinstance(v, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if uv:
        layer = bm.loops.layers.uv.new('UVMap')
        for f in bm.faces:
            for loop in f.loops:
                loop[layer].uv = uv(loop.vert.co.x, loop.vert.co.z)
    bm.transform(FRAME)
    return bm


def cylinder(radius, depth, place, segments=64):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius, depth=depth, matrix=place)
    return bm


def box(x0, x1, y0, y1, z0, z1):
    return prism([(x0, z0), (x1, z0), (x1, z1), (x0, z1)], y0, y1)


def import_enclosure(material):
    before = set(bpy.data.objects)
    result = bpy.ops.wm.obj_import(filepath=str(HERE / 'tessera-enclosure-render.obj'), forward_axis='Y', up_axis='Z')
    assert result == {'FINISHED'}, result
    ob = next(o for o in bpy.data.objects if o not in before)
    ob.name = ob.data.name = 'Console'
    ob.data.transform(WORLD_MM)
    ob.matrix_world = Matrix.Identity(4)
    ob.data.materials.clear()
    ob.data.materials.append(material)
    return ob


def build_panel(mats):
    half_w, pic_x0, pic_z0 = W / 2, -PIC_W / 2, (H - PIC_H) / 2
    outline = rounded_rect(-half_w, half_w, 0, H, CORNER)
    glass = mesh_object('Panel glass', prism(outline, 0, GLASS, uv=lambda x, z: ((x - pic_x0) / PIC_W, (z - pic_z0) / PIC_H)), mats['glass'])
    housing = mesh_object('Panel housing', prism(outline, GLASS + 0.02, T), mats['housing'], smooth_angle=30)
    bevel(housing, 0.6)
    back = mesh_object('Panel back box', box(-BOX_W / 2, BOX_W / 2, T - 0.1, BOX_DEEP, (H - BOX_H) / 2, (H + BOX_H) / 2), mats['housing'], smooth_angle=30)
    bevel(back, 1.0)
    jack = mesh_object('Ethernet jack', box(8, 26, BOX_DEEP - 0.1, JACK_DEEP, 52, 68), mats['steel'], smooth_angle=30)
    bevel(jack, 0.3, 2)
    posts = bmesh.new()
    for sx in (-1, 1):
        for z in ((H - POSTS_Z) / 2, (H + POSTS_Z) / 2):
            depth = POST_END - T + 0.1
            place = Matrix.Translation((sx * POSTS_X / 2, T - 0.1 + depth / 2, z)) @ Matrix.Rotation(math.radians(90), 4, 'X')
            bmesh.ops.create_cone(posts, cap_ends=True, segments=32, radius1=POST_D / 2, radius2=POST_D / 2, depth=depth, matrix=place)
    posts.transform(FRAME)
    mesh_object('Panel corner posts', posts, mats['housing'], smooth_angle=40)
    plug_x, plug_z = BOX_W / 2 - 13, 75.2                       # the upper USB-C socket, as make_enclosure.py checks it
    plug = mesh_object('USB-C plug', prism(rounded_rect(plug_x - 6, plug_x + 6, plug_z - 3.25, plug_z + 3.25, 3.0, 8), BOX_DEEP + 0.02, BOX_DEEP + 22), mats['plug'], smooth_angle=40)
    bevel(plug, 0.5)
    relief = cylinder(2.6, 8, Matrix.Translation((plug_x, BOX_DEEP + 26, plug_z)) @ Matrix.Rotation(math.radians(90), 4, 'X'), 32)
    relief.transform(FRAME)
    mesh_object('USB-C strain relief', relief, mats['cable'], smooth_angle=40)
    return [glass, housing, back], FRAME @ Vector((plug_x, BOX_DEEP + 29.5, plug_z)), FRAME @ Vector((plug_x, BOX_DEEP + 45, plug_z))


def build_feet(material):
    bm = bmesh.new()
    for x, y, _ in info['feet']:
        bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=5.0, radius2=5.0, depth=2.97,
                              matrix=Matrix.Translation((x, y, DESK + 0.01 + 2.97 / 2)))
    bm.transform(WORLD_MM)
    ob = mesh_object('Rubber feet', bm, material, smooth_angle=40)
    bevel(ob, 0.7, 4)


def build_cable(start, bend, material):
    """From the plug, down inside the shell, out through the arch at the foot of the back and away over the desk."""
    lie = (DESK + CABLE_R + 0.05) * MM
    arch_y = info['arch']['max'][1] * MM
    back_y = info['box']['max'][1] * MM
    points = [start, bend, Vector((bend.x - 0.006, bend.y + 0.0015, 0.020)), Vector((0.022, arch_y + 0.004, lie)),
              Vector((0.0, back_y - 0.004, lie)), Vector((0.0, back_y + 0.025, lie)), Vector((-0.03, back_y + 0.07, lie)),
              Vector((-0.10, back_y + 0.16, lie)), Vector((-0.22, back_y + 0.34, lie)), Vector((-0.32, back_y + 0.55, lie))]
    curve = bpy.data.curves.new('USB cable', 'CURVE')
    curve.dimensions = '3D'
    curve.bevel_depth = CABLE_R * MM
    curve.bevel_resolution = 6
    curve.resolution_u = 32
    curve.use_fill_caps = True
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    for i, p in enumerate(points):
        before, after = points[max(i - 1, 0)], points[min(i + 1, len(points) - 1)]
        tangent = (after - before) * (0.15 if 1 <= i <= 3 else 0.22)   # tight inside the shell, clear of the back wall
        if i == 0:
            tangent = (points[1] - points[0]) * 0.4
        if abs(p.z - lie) < 1e-6:
            tangent.z = 0.0                                     # lies flat on the desk, never dips into it
        bp = spline.bezier_points[i]
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = 'FREE'
        bp.handle_left, bp.handle_right = p - tangent, p + tangent
    curve.materials.append(material)
    ob = bpy.data.objects.new('USB cable', curve)
    bpy.context.scene.collection.objects.link(ob)


def build_studio(material):
    """A round infinity cove: a flat floor that bends up into a wall all round, so every camera sees a seamless set."""
    floor, cove, profile = 0.8, 0.5, [(0.0, 0.0)]
    profile += [(floor * i / 8, 0.0) for i in range(1, 9)]
    profile += [(floor + cove * math.cos(math.radians(-90 + 90 * i / 16)), cove + cove * math.sin(math.radians(-90 + 90 * i / 16))) for i in range(1, 17)]
    profile += [(floor + cove, cove + 0.12)]          # low, so the glass reflects the dark room above it
    bm = bmesh.new()
    verts = [bm.verts.new((r, 0, z + DESK * MM)) for r, z in profile]
    edges = [bm.edges.new((a, b)) for a, b in zip(verts[:-1], verts[1:], strict=True)]
    bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1), angle=math.tau, steps=128, use_merge=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = mesh_object('Studio cove', bm, material, smooth_angle=60)
    ob.data.update()
    floor_face = min(ob.data.polygons, key=lambda p: p.center.length)
    if floor_face.normal.z < 0:
        ob.data.flip_normals()
    return ob


def aim(ob, target):
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat('-Z', 'Y').to_euler()


def area_light(name, location, target, size, energy, color=(1, 1, 1), skip=None):
    """A soft box. skip: a collection of objects it must not light (light linking), so it never shows in the glass."""
    light = bpy.data.lights.new(name, 'AREA')
    light.shape = 'RECTANGLE'
    light.size, light.size_y = size
    light.energy = energy
    light.color = color
    ob = bpy.data.objects.new(name, light)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = location
    aim(ob, target)
    if skip is not None:
        ob.light_linking.receiver_collection = skip


def unlit(objects):
    skip = bpy.data.collections.new('Not lit by key and fill')
    for ob in objects:
        skip.objects.link(ob)
    for entry in skip.collection_objects:
        entry.light_linking.link_state = 'EXCLUDE'
    return skip


CENTRE = Vector((0.0, 0.060, 0.050))
SHOTS = {   # azimuth from the front (degrees, + to the right), elevation, distance (m), lens (mm), f-stop, what to focus on
    'hero': (-34, 21, 0.64, 70, 8.0, 'glass'),
    'user': (0, 40, 0.68, 70, 8.0, 'glass'),
    'side': (-90, 9, 1.05, 135, 11.0, 'centre'),
    'back': (152, 18, 0.74, 70, 6.3, 'centre'),
    'detail': (-26, 20, 0.26, 100, 3.5, 'mark'),
}


def cameras():
    glass = Vector(info['glass_centre']) * MM
    mark = Vector((0.0, 0.0062, 0.0163))                       # the tile mark in the chin
    focus = {'glass': glass, 'centre': CENTRE, 'mark': mark}
    made = {}
    for name, (az, el, dist, lens, fstop, aim_at) in SHOTS.items():
        target = mark + Vector((0.010, 0.0015, 0.0035)) if name == 'detail' else CENTRE
        a, e = math.radians(az), math.radians(el)
        cam = bpy.data.cameras.new(name)
        cam.lens, cam.sensor_width, cam.clip_start, cam.clip_end = lens, 36.0, 0.01, 20.0
        cam.dof.use_dof = True
        cam.dof.aperture_fstop = fstop
        ob = bpy.data.objects.new(f'Camera {name}', cam)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = target + dist * Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        aim(ob, target)
        cam.dof.focus_distance = (focus[aim_at] - ob.location).length
        made[name] = ob
    return made


def use_gpu(scene):
    scene.render.engine = 'CYCLES'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('OPTIX', 'HIP', 'CUDA', 'ONEAPI', 'METAL'):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        found = [d for d in prefs.devices if d.type == kind]
        if not found:
            continue
        discrete = [d for d in found if not d.name.endswith('Graphics')] or found   # skip the integrated GPU when there is a card
        for d in prefs.devices:
            d.use = d in discrete
        scene.cycles.device = 'GPU'
        return f'{kind}: ' + ', '.join(d.name for d in discrete)
    scene.cycles.device = 'CPU'
    return 'CPU'


def settings(scene):
    width, height = (int(v) for v in args.res.lower().split('x'))
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = width, height, 100
    c = scene.cycles
    c.samples, c.adaptive_threshold, c.use_adaptive_sampling = args.samples, 0.008, True
    c.use_denoising = True
    c.denoiser = 'OPENIMAGEDENOISE'
    c.max_bounces, c.glossy_bounces, c.diffuse_bounces = 12, 6, 4
    c.sample_clamp_indirect, c.blur_glossy = 8.0, 0.5
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '8'
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    for look in ('AgX - Medium High Contrast', 'Medium High Contrast'):
        try:
            scene.view_settings.look = look
            break
        except TypeError:
            pass
    scene.view_settings.exposure = 0.0
    world = bpy.data.worlds.new('Studio') if not scene.world else scene.world
    scene.world = world
    background = next(n for n in world.node_tree.nodes if n.type == 'BACKGROUND')
    background.inputs['Color'].default_value = (0.018, 0.019, 0.021, 1)
    background.inputs['Strength'].default_value = 1.0


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    mats = {
        'shell': shell_material(),
        'glass': glass_material(Path(args.screen)),
        'housing': principled('Panel housing ABS', '151618', 0.42)[0],
        'steel': principled('Jack steel', (0.62, 0.62, 0.64, 1), 0.32, metallic=1.0)[0],
        'plug': principled('Plug plastic', '161718', 0.38)[0],
        'cable': principled('Cable TPE', '121314', 0.55)[0],
        'rubber': principled('Rubber feet', '0e0e0f', 0.85)[0],
        'studio': principled('Studio cove', '3a3c3f', 0.7)[0],
    }
    console = import_enclosure(mats['shell'])
    (glass, *_), start, bend = build_panel(mats)
    skip = unlit([glass])
    build_feet(mats['rubber'])
    build_cable(start, bend, mats['cable'])
    build_studio(mats['studio'])
    area_light('Key', (-0.45, -0.55, 0.62), CENTRE, (0.7, 0.5), 11, skip=skip)
    area_light('Fill', (0.66, -0.12, 0.18), CENTRE, (0.5, 0.5), 2.6, (1.0, 0.97, 0.93), skip=skip)
    area_light('Rim left', (-0.30, 0.60, 0.42), CENTRE, (0.6, 0.1), 12)
    area_light('Rim right', (0.32, 0.58, 0.44), CENTRE, (0.6, 0.1), 12)
    area_light('Top', (0.0, 0.25, 0.80), CENTRE, (0.7, 0.4), 4.5)
    area_light('Sheen', (0.55, -0.45, 0.55), CENTRE, (0.8, 0.12), 4)          # one soft gradient across the glass
    made = cameras()
    device = use_gpu(scene)
    settings(scene)
    scene.camera = made['hero']
    out = Path(args.out)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'tessera-console.blend'), compress=True)
    dims = console.dimensions / MM
    print(f'RESULT console {dims.x:.1f} x {dims.y:.1f} x {dims.z:.1f} mm, custom normals {console.data.has_custom_normals}, '
          f'triangles {sum(len(p.vertices) - 2 for p in console.data.polygons)}, device {device}')
    if args.no_render:
        return
    for name in [s for s in args.shots.split(',') if s]:
        scene.camera = made[name]
        scene.render.filepath = str(out / 'renders' / f'{name}.png')
        bpy.ops.render.render(write_still=True)
        print(f'RESULT wrote renders/{name}.png')


main()
