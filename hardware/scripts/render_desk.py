"""The desk scene of make_render.py (--scene desk). The console stands on an oak desk in front of a 27-inch monitor.
Around it are a tenkeyless keyboard with sculpted keycaps and legends, a mouse, a felt desk mat, a cup of coffee,
headphones and a snake plant.
A window lights it, and so does a dim room, which is Blender's bundled interior HDRI (CC0, Poly Haven).

make_render.py imports this inside Blender and lends it its helpers, sizes and options through __main__.
Sizes are in metres: x to the right, y away from you, z up. The desk top is where the console's feet stand.
"""
import math
from pathlib import Path

import __main__ as R
import bmesh
import bpy
from mathutils import Matrix, Vector

MM, TOP = R.MM, R.DESK * R.MM
DESK_X, DESK_Y, DESK_T, WALL_Y = (-0.80, 0.95), (-0.30, 0.50), 0.026, 0.53
MAT = 0.003                                          # the felt desk mat
CORD = 0.0018                                        # the keyboard cable's radius
U = 0.01905                                          # one keyboard unit
STAINS = ((-0.352, 0.203, 0.0398, 1.0), (-0.300, 0.150, 0.0398, 0.7))   # coffee rings: x, y, radius, how dark
SHOTS = {   # as make_render.SHOTS: azimuth, elevation, distance, lens, f-stop, focus on, aim at
    'desk': (-24, 15, 1.2, 45, 3.2, 'glass', Vector((0.09, 0.14, 0.13))),
    'desk_wide': (-14, 28, 1.4, 35, 8.0, 'glass', Vector((0.14, 0.18, 0.18))),
    'desk_close': (-38, 16, 0.50, 85, 4.0, 'glass', R.CENTRE + Vector((0.04, 0.0, 0.0))),
}


# --- materials ------------------------------------------------------------------------------------------------
def node(mat, kind, **values):
    return R.node(mat, kind, **values)


def ramp(mat, fac, stops):
    """A color ramp from fac through (position, sRGB hex) stops; returns its color output."""
    r = mat.node_tree.nodes.new('ShaderNodeValToRGB')
    elements = r.color_ramp.elements
    for _ in stops[2:]:
        elements.new(0.5)
    for element, (position, color) in zip(elements, stops, strict=True):
        element.position, element.color = position, R.srgb(color)
    R.link(mat, fac, r.inputs['Fac'])
    return r.outputs['Color']


def math_node(mat, operation, a, b=None):
    """A Math node; a and b are sockets or numbers. Returns its output."""
    n = node(mat, 'ShaderNodeMath', operation=operation)
    for socket, value in zip(n.inputs, (a, b), strict=False):
        if value is None:
            continue
        if isinstance(value, (int, float)):
            socket.default_value = value
        else:
            R.link(mat, value, socket)
    return n.outputs[0]


def mix_color(mat, factor, a, b):
    """Mix colour a into b by factor; the colours are sockets or sRGB hex. Returns the result."""
    mix = node(mat, 'ShaderNodeMix', data_type='RGBA')
    R.link(mat, factor, mix.inputs['Factor'])
    for socket, value in zip((s for s in mix.inputs if s.type == 'RGBA'), (a, b), strict=True):
        if isinstance(value, str):
            socket.default_value = R.srgb(value)
        else:
            R.link(mat, value, socket)
    return next(s for s in mix.outputs if s.type == 'RGBA')


def coffee_rings(mat, position):
    """How much the cup's old coffee rings darken the desk at position: a thin, wobbly dark edge, a faint inside."""
    wobble = node(mat, 'ShaderNodeTexNoise', Scale=30.0, Detail=2.0)
    patchy = node(mat, 'ShaderNodeTexNoise', Scale=180.0, Detail=4.0)
    R.link(mat, position, wobble.inputs['Vector'])
    R.link(mat, position, patchy.inputs['Vector'])
    gaps = node(mat, 'ShaderNodeTexNoise', Scale=22.0, Detail=1.0)
    R.link(mat, position, gaps.inputs['Vector'])
    patches = node(mat, 'ShaderNodeMapRange', **{'From Min': 0.35, 'From Max': 0.65, 'To Min': 0.35, 'To Max': 1.0})
    R.link(mat, patchy.outputs['Fac'], patches.inputs['Value'])
    broken = node(mat, 'ShaderNodeMapRange', interpolation_type='SMOOTHSTEP',
                  **{'From Min': 0.38, 'From Max': 0.58, 'To Min': 0.1, 'To Max': 1.0})
    R.link(mat, gaps.outputs['Fac'], broken.inputs['Value'])
    total = None
    for x, y, radius, strength in STAINS:
        distance = node(mat, 'ShaderNodeVectorMath', operation='DISTANCE')
        R.link(mat, position, distance.inputs[0])
        distance.inputs[1].default_value = (x, y, TOP)
        d = math_node(mat, 'ADD', distance.outputs['Value'], math_node(mat, 'MULTIPLY', math_node(mat, 'SUBTRACT', wobble.outputs['Fac'], 0.5), 0.003))
        edge = node(mat, 'ShaderNodeMapRange', interpolation_type='SMOOTHSTEP',
                    **{'From Min': 0.0005, 'From Max': 0.0024, 'To Min': 1.0, 'To Max': 0.0})
        R.link(mat, math_node(mat, 'ABSOLUTE', math_node(mat, 'SUBTRACT', d, radius)), edge.inputs['Value'])
        inside = math_node(mat, 'MULTIPLY', math_node(mat, 'LESS_THAN', d, radius), 0.18)
        ring = math_node(mat, 'MULTIPLY', math_node(mat, 'MAXIMUM', edge.outputs['Result'], inside), strength)
        total = ring if total is None else math_node(mat, 'MAXIMUM', total, ring)
    return math_node(mat, 'MULTIPLY', math_node(mat, 'MULTIPLY', total, patches.outputs['Result']), broken.outputs['Result'])


def wood_material():
    """Oiled oak: grain along x from stretched noise and fine wavy lines, a thin satin coat with smudges in it, and
    the rings an old cup of coffee left, and patches worn rougher."""
    mat, bsdf = R.principled('Desk oak', 'a87a4f', 0.45)
    bsdf.inputs['Coat Weight'].default_value = 0.3
    coord = node(mat, 'ShaderNodeTexCoord')
    mapping = node(mat, 'ShaderNodeMapping')
    mapping.inputs['Scale'].default_value = (0.35, 15.0, 15.0)
    R.link(mat, coord.outputs['Object'], mapping.inputs['Vector'])
    noise = node(mat, 'ShaderNodeTexNoise', Scale=5.0, Detail=12.0, Roughness=0.62, Distortion=1.2)
    lines = node(mat, 'ShaderNodeTexWave', bands_direction='Y', Scale=16.0, Distortion=10.0, Detail=4.0)
    R.link(mat, mapping.outputs['Vector'], noise.inputs['Vector'])
    R.link(mat, mapping.outputs['Vector'], lines.inputs['Vector'])
    grain = node(mat, 'ShaderNodeMath', operation='MULTIPLY_ADD')
    R.link(mat, lines.outputs['Fac'], grain.inputs[0])
    grain.inputs[1].default_value = 0.35
    R.link(mat, noise.outputs['Fac'], grain.inputs[2])
    wood = ramp(mat, grain.outputs['Value'], ((0.40, '8c6542'), (0.90, 'b98f62')))
    tone = node(mat, 'ShaderNodeTexNoise', Scale=1.4, Detail=2.0)
    R.link(mat, mapping.outputs['Vector'], tone.inputs['Vector'])
    darker = node(mat, 'ShaderNodeMapRange', **{'From Min': 0.3, 'From Max': 0.7, 'To Min': 0.0, 'To Max': 0.3})
    R.link(mat, tone.outputs['Fac'], darker.inputs['Value'])
    wood = mix_color(mat, darker.outputs['Result'], wood, '7a5434')
    stain = coffee_rings(mat, coord.outputs['Object'])
    R.link(mat, mix_color(mat, math_node(mat, 'MULTIPLY', stain, 0.85), wood, '4a2c17'), bsdf.inputs['Base Color'])
    bump = node(mat, 'ShaderNodeBump', Strength=0.08, Distance=0.0002)
    R.link(mat, grain.outputs['Value'], bump.inputs['Height'])
    R.link(mat, bump.outputs['Normal'], bsdf.inputs['Normal'])
    smudge = node(mat, 'ShaderNodeTexNoise', Scale=7.0, Detail=3.0)
    R.link(mat, coord.outputs['Object'], smudge.inputs['Vector'])
    coat = node(mat, 'ShaderNodeMapRange', **{'From Min': 0.35, 'From Max': 0.65, 'To Min': 0.12, 'To Max': 0.38})
    R.link(mat, smudge.outputs['Fac'], coat.inputs['Value'])
    R.link(mat, math_node(mat, 'ADD', coat.outputs['Result'], math_node(mat, 'MULTIPLY', stain, 0.3)), bsdf.inputs['Coat Roughness'])
    wear = node(mat, 'ShaderNodeTexNoise', Scale=2.5, Detail=4.0, Roughness=0.6)
    R.link(mat, coord.outputs['Object'], wear.inputs['Vector'])
    for socket, low, high in (('Roughness', 0.36, 0.60), ('Coat Weight', 0.34, 0.16)):
        worn = node(mat, 'ShaderNodeMapRange', **{'From Min': 0.35, 'From Max': 0.65, 'To Min': low, 'To Max': high})
        R.link(mat, wear.outputs['Fac'], worn.inputs['Value'])
        R.link(mat, worn.outputs['Result'], bsdf.inputs[socket])
    return mat


def matte_material(name, color, roughness, bump_scale, bump_strength, sheen=0.0):
    """A matte surface with a fine noise bump: felt, plaster, PBT keycaps, rubber."""
    mat, bsdf = R.principled(name, color, roughness)
    bsdf.inputs['Sheen Weight'].default_value = sheen
    noise = node(mat, 'ShaderNodeTexNoise', Scale=bump_scale, Detail=6.0)
    R.link(mat, node(mat, 'ShaderNodeTexCoord').outputs['Object'], noise.inputs['Vector'])
    bump = node(mat, 'ShaderNodeBump', Strength=bump_strength, Distance=0.0003)
    R.link(mat, noise.outputs['Fac'], bump.inputs['Height'])
    R.link(mat, bump.outputs['Normal'], bsdf.inputs['Normal'])
    return mat


def anodised_material(name, color, roughness):
    """Bead-blasted, anodised aluminium: metal whose roughness wanders a little."""
    mat, bsdf = R.principled(name, color, roughness, metallic=1.0)
    noise = node(mat, 'ShaderNodeTexNoise', Scale=60.0, Detail=4.0)
    R.link(mat, node(mat, 'ShaderNodeTexCoord').outputs['Object'], noise.inputs['Vector'])
    spread = node(mat, 'ShaderNodeMapRange', **{'To Min': roughness - 0.06, 'To Max': roughness + 0.06})
    R.link(mat, noise.outputs['Fac'], spread.inputs['Value'])
    R.link(mat, spread.outputs['Result'], bsdf.inputs['Roughness'])
    return mat


def leaf_material():
    """Snake plant: dark green with wavy pale cross-bands and a thin pale edge (UV u across the blade, v along it)."""
    mat, bsdf = R.principled('Snake plant leaf', '2d5236', 0.42)
    uv = node(mat, 'ShaderNodeUVMap').outputs['UV']
    bands = node(mat, 'ShaderNodeTexWave', bands_direction='Y', Scale=4.5, Distortion=14.0, Detail=5.0, **{'Detail Scale': 1.4, 'Detail Roughness': 0.65})
    R.link(mat, uv, bands.inputs['Vector'])
    green = ramp(mat, bands.outputs['Fac'], ((0.35, '1f3a26'), (0.85, '3b5a3d')))
    xyz = node(mat, 'ShaderNodeSeparateXYZ')
    R.link(mat, uv, xyz.inputs['Vector'])
    edge = node(mat, 'ShaderNodeMapRange', interpolation_type='SMOOTHSTEP', **{'From Min': 0.90, 'From Max': 0.97})
    across = math_node(mat, 'SUBTRACT', math_node(mat, 'MULTIPLY', xyz.outputs['X'], 2.0), 1.0)
    R.link(mat, math_node(mat, 'ABSOLUTE', across), edge.inputs['Value'])
    R.link(mat, mix_color(mat, edge.outputs['Result'], green, '8f9a5a'), bsdf.inputs['Base Color'])
    return mat


MOUSE_L, MOUSE_W, MOUSE_H = 0.120, 0.064, 0.038
SPLIT_Y, WHEEL_Y = 0.008, 0.031                      # mouse-local: where the buttons end, the wheel's centre


def mouse_material():
    """Matte black plastic. The split between the buttons, the line behind them and the wheel slot are dark grooves."""
    mat, bsdf = R.principled('Mouse', '242528', 0.48)
    bsdf.inputs['Specular IOR Level'].default_value = 0.4
    xyz = node(mat, 'ShaderNodeSeparateXYZ')
    R.link(mat, node(mat, 'ShaderNodeTexCoord').outputs['Object'], xyz.inputs['Vector'])
    x, y, z = xyz.outputs['X'], xyz.outputs['Y'], xyz.outputs['Z']

    def groove(distance):
        m = node(mat, 'ShaderNodeMapRange', interpolation_type='SMOOTHSTEP',
                 **{'From Min': 0.0003, 'From Max': 0.00062, 'To Min': 1.0, 'To Max': 0.0})
        R.link(mat, math_node(mat, 'ABSOLUTE', distance), m.inputs['Value'])
        return m.outputs['Result']

    split = math_node(mat, 'MULTIPLY', groove(x), math_node(mat, 'GREATER_THAN', y, SPLIT_Y))
    behind = math_node(mat, 'SUBTRACT', math_node(mat, 'SUBTRACT', y, SPLIT_Y), math_node(mat, 'MULTIPLY', math_node(mat, 'MULTIPLY', x, x), -6.0))
    across = math_node(mat, 'MULTIPLY', groove(behind), math_node(mat, 'GREATER_THAN', z, 0.024))
    slot = math_node(mat, 'MULTIPLY', math_node(mat, 'LESS_THAN', math_node(mat, 'ABSOLUTE', x), 0.0047),
                     math_node(mat, 'LESS_THAN', math_node(mat, 'ABSOLUTE', math_node(mat, 'SUBTRACT', y, WHEEL_Y)), 0.0125))
    dark = math_node(mat, 'MAXIMUM', math_node(mat, 'MAXIMUM', split, across), slot)
    R.link(mat, ramp(mat, dark, ((0.0, '242528'), (1.0, '030303'))), bsdf.inputs['Base Color'])
    bump = node(mat, 'ShaderNodeBump', Strength=1.0, Distance=0.0007, invert=True)
    R.link(mat, dark, bump.inputs['Height'])
    R.link(mat, bump.outputs['Normal'], bsdf.inputs['Normal'])
    return mat


def materials():
    p = R.principled
    return {
        'slider': anodised_material('Headphone sliders', '9a9da2', 0.22),
        'headphones': matte_material('Headphones', '18191b', 0.34, 900.0, 0.06),
        'cushion': matte_material('Ear cushions', '262420', 0.45, 4000.0, 0.3, sheen=0.3),
        'wood': wood_material(),
        'wall': matte_material('Wall plaster', '8d8a84', 0.9, 60.0, 0.05),
        'floor': p('Floor', '4a443e', 0.6)[0],
        'felt': matte_material('Desk mat felt', '141517', 0.95, 2500.0, 0.35, sheen=0.15),
        'pot': matte_material('Plant pot', '9a9893', 0.75, 300.0, 0.15),
        'leaf': leaf_material(),
        'soil': matte_material('Soil', '1d1612', 1.0, 3000.0, 0.5),
        'case': anodised_material('Keyboard case aluminium', '74777c', 0.36),
        'plate': p('Keyboard plate', '1a1b1d', 0.5, metallic=0.6)[0],
        'switch': p('Switch housings', '0d0d0e', 0.4)[0],
        'alpha': matte_material('Keycaps PBT', '2a2c30', 0.6, 4000.0, 0.12),
        'mod': matte_material('Keycaps PBT modifiers', '45484e', 0.6, 4000.0, 0.12),
        'accent': matte_material('Keycaps PBT accent', '35d07f', 0.6, 4000.0, 0.12),
        'legend': p('Keycap legends', 'dfe2e6', 0.5)[0],
        'legend_dark': p('Keycap legends on accents', '0f2a1a', 0.55)[0],
        'cord': p('Keyboard cable', '1a1a1b', 0.6)[0],
        'mouse': mouse_material(),
        'wheel': matte_material('Mouse wheel rubber', '141414', 0.75, 3000.0, 0.2),
        'stand': anodised_material('Monitor stand', '2c2d30', 0.35),
        'monitor': p('Monitor plastic', '141517', 0.5)[0],
        'monitor_screen': R.glass_material(Path(R.args.monitor), 'Monitor picture', 0.9, 0.38),
        'ceramic': p('Cup ceramic', 'dcd5c8', 0.18)[0],
        'coffee': p('Coffee', '2a160b', 0.08)[0],
    }


# --- geometry helpers -----------------------------------------------------------------------------------------
def solid(outline, z0, z1, bm=None):
    """A solid in world metres: the outline (x, y) between heights z0 and z1, in bm or a new bmesh."""
    bm = bmesh.new() if bm is None else bm
    face = bm.faces.new([bm.verts.new((x, y, z0)) for x, y in outline])
    top = bmesh.ops.extrude_face_region(bm, geom=[face])['geom']
    bmesh.ops.translate(bm, vec=(0, 0, z1 - z0), verts=[v for v in top if isinstance(v, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def placed(name, bm, material, matrix, smooth_angle=40, bevel_mm=None, segments=3):
    bm.transform(matrix)
    ob = R.mesh_object(name, bm, material, smooth_angle=smooth_angle)
    if bevel_mm:
        R.bevel(ob, bevel_mm, segments)
    return ob


def loft(bm, rings, close_with=None):
    """Quads between equal rings of points (counter-clockwise seen from where the faces point); a fan to close_with."""
    verts = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(rings[0])
    for a, b in zip(verts[:-1], verts[1:], strict=True):
        for k in range(n):
            bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
    if close_with is not None:
        tip, last = bm.verts.new(close_with), verts[-1]
        for k in range(n):
            bm.faces.new((last[k], last[(k + 1) % n], tip))
    return verts


def cable(name, points, radius, material):
    """A cable through the points. On the desk or the mat it lies flat, so it never dips into them. Each handle
    reaches a third of the way to its neighbour, so a short step down over the desk's edge never loops up."""
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions, curve.bevel_depth, curve.bevel_resolution, curve.resolution_u = '3D', radius, 4, 24
    curve.use_fill_caps = True
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    for i, p in enumerate(points):
        before, after = points[max(i - 1, 0)], points[min(i + 1, len(points) - 1)]
        tangent = after - before
        if any(abs(p.z - (level + radius)) < 1e-6 for level in (TOP, TOP + MAT)):
            tangent.z = 0.0
        tangent.normalize()
        bp = spline.bezier_points[i]
        bp.co, bp.handle_left_type, bp.handle_right_type = p, 'FREE', 'FREE'
        bp.handle_left, bp.handle_right = p - tangent * (p - before).length / 3, p + tangent * (after - p).length / 3
    curve.materials.append(material)
    ob = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(ob)
    return ob


# --- the keyboard ---------------------------------------------------------------------------------------------
ROWS = [   # front to back: (width in units, legend), or a gap in units
    [(1.25, 'Ctrl'), (1.25, 'Win'), (1.25, 'Alt'), (6.25, ''), (1.25, 'Alt'), (1.25, 'Fn'), (1.25, 'Menu'),
     (1.25, 'Ctrl'), 0.25, (1, '←'), (1, '↓'), (1, '→')],
    [(2.25, 'Shift'), *[(1, k) for k in 'ZXCVBNM,./'], (2.75, 'Shift'), 1.25, (1, '↑')],
    [(1.75, 'Caps'), *[(1, k) for k in "ASDFGHJKL;'"], (2.25, 'Enter')],
    [(1.5, 'Tab'), *[(1, k) for k in 'QWERTYUIOP[]'], (1.5, '\\'), 0.25, (1, 'Del'), (1, 'End'), (1, 'PgDn')],
    [*[(1, k) for k in '`1234567890-='], (2, 'Back'), 0.25, (1, 'Ins'), (1, 'Home'), (1, 'PgUp')],
    [(1, 'Esc'), 1, *[(1, f'F{i}') for i in range(1, 5)], 0.5, *[(1, f'F{i}') for i in range(5, 9)], 0.5,
     *[(1, f'F{i}') for i in range(9, 13)], 0.25, (1, 'PrtSc'), (1, 'ScrLk'), (1, 'Pause')],
]
ROW_PROFILE = ((0.0080, -6), (0.0080, -6), (0.0074, 0), (0.0079, 4), (0.0090, 8), (0.0090, 8))   # height, top tilt
ARROWS = {'←', '↑', '→', '↓'}
KB_MARGIN, KB_CASE, KB_POCKET, CAP_FLOOR = 0.008, 0.0185, 0.006, 0.0165


def key_ring(cx, cy, hw, hd, r, nx, steps=3):
    """A rounded rectangle, counter-clockwise; the front and back edges are cut in nx pieces so a dish can curve."""
    corners = ((hw - r, -(hd - r), -90), (hw - r, hd - r, 0), (-(hw - r), hd - r, 90), (-(hw - r), -(hd - r), 180))
    points = []
    for i, (ox, oy, start) in enumerate(corners):
        for k in range(steps + 1):
            a = math.radians(start + 90 * k / steps)
            points.append((cx + ox + r * math.cos(a), cy + oy + r * math.sin(a)))
        if i in (1, 3):
            edge_y, sign = (hd, -1) if i == 1 else (-hd, 1)
            points += [(cx + sign * (hw - r) * (2 * k / nx - 1), cy + edge_y) for k in range(1, nx)]
    return points


def keycap(bm, x0, x1, y0, y1, height, tilt, dish):
    """A sculpted keycap with slightly convex sides and rounded corners. Its top tilts towards you and has a
    cylindrical dish. Returns the height of the top at (x, y), for the legend."""
    cx, cy, bw, bd = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    tw, td, slope = bw - 0.0029, bd - 0.0021, math.tan(math.radians(tilt))

    def surface(x, y):
        u = min(abs(x - cx) / tw, 1.0)
        return CAP_FLOOR + height + (y - cy) * slope - dish * (1 - u * u)

    nx = max(2, round((x1 - x0) / U * 3))
    rim = key_ring(cx, cy, tw, td, 0.0018, nx)
    rings = [[(x, y, CAP_FLOOR) for x, y in key_ring(cx, cy, bw, bd, 0.0008, nx)]]
    for s in (0.33, 0.66):
        k = s ** 1.5
        side = key_ring(cx, cy, bw - (bw - tw - 0.00035) * k, bd - (bd - td - 0.00035) * k, 0.0008 + 0.0011 * s, nx)
        rings.append([(x, y, CAP_FLOOR + s * (surface(rx, ry) - 0.0006 - CAP_FLOOR)) for (x, y), (rx, ry) in zip(side, rim, strict=True)])
    shoulder = key_ring(cx, cy, tw + 0.00035, td + 0.00035, 0.0020, nx)
    rings.append([(x, y, surface(rx, ry) - 0.00045) for (x, y), (rx, ry) in zip(shoulder, rim, strict=True)])
    rings.append([(x, y, surface(x, y)) for x, y in rim])
    for q in (0.75, 0.5, 0.25):
        rings.append([(x, y, surface(x, y)) for x, y in key_ring(cx, cy, tw * q, td * q, 0.0018 * q, nx)])
    loft(bm, rings, (cx, cy, surface(cx, cy)))
    return surface


def build_case(mats, place, width, depth):
    """An aluminium tray: rounded outside, a 6 mm deep pocket round the keys with the plate at its floor, two feet
    at the back and a USB-C port."""
    inner = (KB_MARGIN - 0.0012, width - KB_MARGIN + 0.0012, KB_MARGIN - 0.0012, depth - KB_MARGIN + 0.0012)
    outer, hole, floor = R.rounded_rect(0, width, 0, depth, 0.007, 8), R.rounded_rect(*inner, 0.0015, 8), KB_CASE - KB_POCKET
    bm = bmesh.new()
    rings = loft(bm, [[(x, y, z) for x, y in pts] for pts, z in ((outer, 0.0), (outer, KB_CASE), (hole, KB_CASE), (hole, floor))])
    bm.faces.new(rings[0][::-1])
    bm.faces.new(rings[-1])
    placed('Keyboard case', bm, mats['case'], place, 40, 1.0, 3)
    shrink = (inner[0] + 0.0004, inner[1] - 0.0004, inner[2] + 0.0004, inner[3] - 0.0004)
    placed('Keyboard plate', solid(R.rounded_rect(*shrink, 0.001, 4), floor, floor + 0.0015), mats['plate'], place, 30)
    feet = bmesh.new()
    for fx in (0.035, width - 0.035):
        block(feet, (fx, depth - 0.019, -0.00425), (0.020, 0.018, 0.0095))
    placed('Keyboard feet', feet, mats['switch'], place, 30, 0.8, 2)
    port = solid(R.rounded_rect(0.064, 0.073, 0.0055, 0.0088, 0.0016, 6), 0, 1)
    port.transform(Matrix.Translation((0, depth + 0.0003, 0)) @ Matrix.Rotation(math.radians(90), 4, 'X') @ Matrix.Diagonal((1, 1, 0.0008, 1)))
    placed('Keyboard USB-C port', port, mats['switch'], place, None)
    return place @ Vector((0.0685, depth - 0.002, 0.00715))


def block(bm, centre, size):
    """A box added to bm."""
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(centre) @ Matrix.Diagonal((*size, 1)))


def build_legends(labels, mats, place):
    """Every legend is a text curve in Inter (or Blender's own font), turned into a mesh that lies on its cap's top."""
    font_path = Path(bpy.utils.system_resource('DATAFILES', path='fonts')) / 'Inter.woff2'
    font = bpy.data.fonts.load(str(font_path), check_existing=True) if font_path.exists() else None
    texts = []
    for text, *_ in labels:
        curve = bpy.data.curves.new('Legend', 'FONT')
        curve.body, curve.size = text, 0.0056 if len(text) == 1 else 0.0031
        curve.align_x, curve.align_y = 'CENTER', 'CENTER'
        if font:
            curve.font = font
        ob = bpy.data.objects.new('Legend', curve)
        bpy.context.scene.collection.objects.link(ob)
        texts.append(ob)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    out = {'legend': bmesh.new(), 'legend_dark': bmesh.new()}
    for ob, (_, kx, ky, surface, kind) in zip(texts, labels, strict=True):
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph))
        for v in me.vertices:
            x, y = kx + v.co.x, ky + v.co.y
            v.co = (x, y, surface(x, y) + 0.00005)
        out[kind].from_mesh(me)
        bpy.data.meshes.remove(me)
        curve = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.curves.remove(curve)
    if font:
        bpy.data.fonts.remove(font)
    placed('Keycap legends', out['legend'], mats['legend'], place, None)
    placed('Keycap legends on accents', out['legend_dark'], mats['legend_dark'], place, None)


def build_keyboard(mats, x, y, turn):
    """A tenkeyless keyboard in an aluminium tray, front left corner at (x, y) and turned there by turn degrees, on
    feet that tilt it 3 degrees. Returns where its cable leaves the back."""
    width, depth = 18.25 * U + 2 * KB_MARGIN, 6.5 * U + 2 * KB_MARGIN
    place = (Matrix.Translation((x, y, TOP + MAT)) @ Matrix.Rotation(math.radians(turn), 4, 'Z')
             @ Matrix.Rotation(math.radians(3), 4, 'X'))
    port = build_case(mats, place, width, depth)
    caps = {'alpha': bmesh.new(), 'mod': bmesh.new(), 'accent': bmesh.new()}
    switches, labels = bmesh.new(), []
    for r, row in enumerate(ROWS):
        height, tilt = ROW_PROFILE[r]
        y0, cx = KB_MARGIN + (r + (0.5 if r == 5 else 0)) * U, KB_MARGIN
        for key in row:
            if not isinstance(key, tuple):
                cx += key * U
                continue
            w, text = key
            f_key = text[:1] == 'F' and text[1:].isdigit()
            kind = 'accent' if text in ('Esc', 'Enter') else 'mod' if (len(text) > 1 and not f_key) or text in ARROWS else 'alpha'
            gap = 0.00045
            surface = keycap(caps[kind], cx + gap, cx + w * U - gap, y0 + gap, y0 + U - gap, height, tilt, 0.00012 if w > 6 else 0.0005)
            kx, ky = cx + w * U / 2, y0 + U / 2
            low, high = KB_CASE - KB_POCKET + 0.0015, CAP_FLOOR + 0.001
            block(switches, (kx, ky, (low + high) / 2), (0.014, 0.014, high - low))
            if text:
                labels.append((text, kx, ky, surface, 'legend_dark' if kind == 'accent' else 'legend'))
            cx += w * U
    for kind, bm in caps.items():
        placed(f'Keycaps {kind}', bm, mats[kind], place, 80)
    placed('Key switches', switches, mats['switch'], place, 30)
    build_legends(labels, mats, place)
    return port


# --- mouse, monitor, cup, plant -------------------------------------------------------------------------------
def mouse_section(s):
    """Half width, height and y of the mouse's cross-section s: 0 is the front tip, 1 the back."""
    end = max(4 * s * (1 - s), 0.0)
    w = MOUSE_W / 2 * end ** 0.35 * (0.86 + 0.16 * s) * (1 - 0.05 * math.exp(-((s - 0.42) / 0.15) ** 2))
    h = MOUSE_H * (0.45 + 0.55 * math.exp(-((s - 0.62) / 0.32) ** 2)) * end ** 0.22
    return w, h, MOUSE_L / 2 - s * MOUSE_L


def build_mouse(mats, x, y, turn):
    """A symmetric mouse, highest over your palm, with a ribbed rubber wheel. Built in its own frame, which the
    grooves in its material use."""
    sections, upper, lower = 72, 40, 14
    rings = []
    for i in range(1, sections):
        s = 0.5 - 0.5 * math.cos(math.pi * i / sections)
        w, h, py = mouse_section(s)
        zb, ring = min(0.003, h * 0.3), []
        for j in range(upper + 1):
            c, sn = math.cos(math.pi * j / upper), math.sin(math.pi * j / upper)
            ring.append((w * math.copysign(abs(c) ** 0.83, c), py, zb + (h - zb) * abs(sn) ** 0.83))
        for j in range(1, lower):
            c, sn = math.cos(math.pi * (1 + j / lower)), math.sin(math.pi * (1 + j / lower))
            ring.append((w * math.copysign(abs(c) ** 0.25, c), py, zb * (1 - abs(sn) ** 0.25)))
        rings.append(ring)
    bm = bmesh.new()
    verts = loft(bm, rings)
    for ring, tip_y, front in ((verts[0], MOUSE_L / 2, True), (verts[-1], -MOUSE_L / 2, False)):
        tip = bm.verts.new((0, tip_y, sum(v.co.z for v in ring) / len(ring)))
        for k in range(len(ring)):
            a, b = ring[k], ring[(k + 1) % len(ring)]
            bm.faces.new((tip, b, a) if front else (tip, a, b))
    place = Matrix.Translation((x, y, TOP + MAT + 0.0012)) @ Matrix.Rotation(math.radians(turn), 4, 'Z')
    R.mesh_object('Mouse', bm, mats['mouse'], smooth_angle=80).matrix_world = place
    wheel, r, n = bmesh.new(), 0.0105, 72
    ends = [[(side, WHEEL_Y + (r - 0.0003 * (k % 2)) * math.cos(math.tau * k / n), (r - 0.0003 * (k % 2)) * math.sin(math.tau * k / n))
             for k in range(n)] for side in (-0.0035, 0.0035)]
    rim = loft(wheel, ends)
    wheel.faces.new(rim[0][::-1])
    wheel.faces.new(rim[1])
    bmesh.ops.recalc_face_normals(wheel, faces=wheel.faces)
    lift = mouse_section((MOUSE_L / 2 - WHEEL_Y) / MOUSE_L)[1] - r + 0.0022
    wheel_ob = R.mesh_object('Mouse wheel', wheel, mats['wheel'], smooth_angle=30)
    wheel_ob.matrix_world = place @ Matrix.Translation((0, 0, lift))
    R.bevel(wheel_ob, 0.6, 2)


def build_monitor(mats, x, y):
    """A 27-inch 16:9 monitor (597 x 336 mm picture) tilted back 6 degrees on a stand, showing the editor."""
    pw, ph, side, chin, deep = 0.597, 0.336, 0.0085, 0.020, 0.010
    bw, bh = pw + 2 * side, ph + side + chin
    tilt = Matrix.Translation((x, y + 0.075, TOP + 0.30)) @ Matrix.Rotation(math.radians(-6), 4, 'X')
    ground = Matrix.Translation((x, y, TOP))
    placed('Monitor stand base', solid(R.rounded_rect(-0.12, 0.12, -0.05, 0.14, 0.045), 0, 0.006), mats['stand'], ground, 30, 2)
    placed('Monitor stand neck', solid(R.rounded_rect(-0.03, 0.03, 0.088, 0.114, 0.010), 0.004, 0.36), mats['stand'], ground, 30, 1)
    placed('Monitor body', solid(R.rounded_rect(-bw / 2, bw / 2, -bh / 2, bh / 2, 0.004), -deep / 2, deep / 2),
           mats['monitor'], tilt @ Matrix.Rotation(math.radians(90), 4, 'X'), 30, 0.8)
    placed('Monitor back', solid(R.rounded_rect(-0.19, 0.19, -0.13, 0.11, 0.03), deep / 2 - 0.001, deep / 2 + 0.024),
           mats['monitor'], tilt @ Matrix.Rotation(math.radians(-90), 4, 'X') @ Matrix.Rotation(math.radians(180), 4, 'Z'), 30, 4)
    image = bpy.data.images.load(R.args.monitor, check_existing=True)
    aspect, wide = image.size[0] / image.size[1], pw / ph
    su, sv = (wide / aspect, 1.0) if aspect > wide else (1.0, aspect / wide)   # cover the picture, crop the rest
    bm = bmesh.new()
    zc = (chin - side) / 2
    face = bm.faces.new([bm.verts.new((u * pw / 2, -deep / 2 - 0.0004, zc + v * ph / 2)) for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    layer = bm.loops.layers.uv.new('UVMap')
    for loop in face.loops:
        loop[layer].uv = (0.5 + loop.vert.co.x / pw * su, 0.5 + (loop.vert.co.z - zc) / ph * sv)
    placed('Monitor picture', bm, mats['monitor_screen'], tilt, None)


def build_cup(mats, x, y):
    """A mug of coffee."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=0.0395, radius2=0.041, depth=0.092,
                          matrix=Matrix.Translation((0, 0, 0.046)))
    rim = max(bm.faces, key=lambda f: f.calc_center_median().z)
    bmesh.ops.inset_region(bm, faces=[rim], thickness=0.0035)
    down = bmesh.ops.extrude_face_region(bm, geom=[rim])['geom']
    bmesh.ops.delete(bm, geom=[rim], context='FACES_ONLY')         # open the top
    bmesh.ops.translate(bm, vec=(0, 0, -0.082), verts=[v for v in down if isinstance(v, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    placed('Cup', bm, mats['ceramic'], Matrix.Translation((x, y, TOP)), 50, 0.8)
    coffee = R.cylinder(0.0372, 0.002, Matrix.Translation((0, 0, 0.075)), 64)
    placed('Coffee', coffee, mats['coffee'], Matrix.Translation((x, y, TOP)), 50)
    rings, sides = [], 16
    for i in range(41):                                          # a C from the wall and back, its ends inside the wall
        u = math.radians(-100 + 5 * i)
        radial = Vector((math.cos(u), 0, math.sin(u) * 1.15)).normalized()
        centre = Vector((0.0402 + 0.021 * math.cos(u), 0, 0.050 + 0.024 * math.sin(u)))
        rings.append([centre + 0.0048 * (math.cos(v) * radial + math.sin(v) * Vector((0, 1, 0)))
                      for v in (math.tau * k / sides for k in range(sides))])
    handle = bmesh.new()
    loft(handle, rings)
    bmesh.ops.recalc_face_normals(handle, faces=handle.faces)
    placed('Cup handle', handle, mats['ceramic'], Matrix.Translation((x, y, TOP)) @ Matrix.Rotation(math.radians(-35), 4, 'Z'), 60)


BLADES = (   # turn (degrees), height, width, outward bend at the tip, twist (degrees)
    (0, 0.40, 0.050, 0.05, 25), (45, 0.33, 0.044, 0.07, -30), (95, 0.43, 0.052, 0.04, 15), (140, 0.30, 0.042, 0.09, -20),
    (185, 0.38, 0.048, 0.05, 35), (230, 0.32, 0.044, 0.08, -15), (270, 0.41, 0.050, 0.05, 20), (315, 0.28, 0.040, 0.10, -35),
    (20, 0.35, 0.046, 0.02, 10), (160, 0.36, 0.046, 0.03, -10), (250, 0.25, 0.038, 0.11, 30), (70, 0.24, 0.036, 0.12, -25))


def build_plant(mats, x, y):
    """A snake plant in a grey pot: sword-shaped blades with a shallow channel, which bend outwards and twist."""
    pot = bmesh.new()
    bmesh.ops.create_cone(pot, cap_ends=True, segments=64, radius1=0.050, radius2=0.060, depth=0.11,
                          matrix=Matrix.Translation((0, 0, 0.055)))
    placed('Plant pot', pot, mats['pot'], Matrix.Translation((x, y, TOP)), 50, 1.5)
    placed('Soil', R.cylinder(0.056, 0.004, Matrix.Translation((0, 0, 0.098)), 64), mats['soil'], Matrix.Translation((x, y, TOP)), 50)
    bm, uv_rows = bmesh.new(), []
    for i, (turn, height, width, bend, twist) in enumerate(BLADES):
        frame = (Matrix.Translation((x, y, TOP + 0.096)) @ Matrix.Rotation(math.radians(turn), 4, 'Z')
                 @ Matrix.Translation((0, 0.010 + 0.006 * (i % 3), 0)))
        face = math.radians((i * 37) % 60 - 30)
        rows = []
        for j in range(29):
            t = j / 28
            w = width * (1 - t ** 3) ** 0.75 * (0.62 + 0.38 * math.sin(math.pi / 2 * min(t / 0.55, 1.0))) / 2
            angle = face + math.radians(twist) * t
            centre = Vector((0.004 * math.sin(i + 3 * t), bend * t ** 1.8, height * t))
            row = []
            for k in range(7):
                u = k / 3 - 1
                local = Vector((u * w, -0.22 * w * abs(u) ** 1.6, 0))
                row.append(frame @ (centre + Matrix.Rotation(angle, 3, 'Z') @ local))
            rows.append(row)
        verts = [[bm.verts.new(p) for p in row] for row in rows]
        for j in range(28):
            for k in range(6):
                f = bm.faces.new((verts[j][k], verts[j][k + 1], verts[j + 1][k + 1], verts[j + 1][k]))
                uv_rows.append((f, [(k / 6, j / 28), ((k + 1) / 6, j / 28), ((k + 1) / 6, (j + 1) / 28), (k / 6, (j + 1) / 28)]))
    layer = bm.loops.layers.uv.new('UVMap')
    for f, uvs in uv_rows:
        for loop, uv in zip(f.loops, uvs, strict=True):
            loop[layer].uv = uv
    ob = R.mesh_object('Snake plant', bm, mats['leaf'], smooth_angle=80)
    solid_mod = ob.modifiers.new('Thickness', 'SOLIDIFY')
    solid_mod.thickness, solid_mod.offset, solid_mod.use_even_offset = 0.0028, 0.0, True


# --- the scene ------------------------------------------------------------------------------------------------
def cable_tail():
    """The console's USB cable: over the back edge of the desk and down behind it."""
    edge = DESK_Y[1]
    return [Vector((-0.27, edge - 0.015, R.LIE)), Vector((-0.28, edge + 0.004, R.LIE - 0.006)),
            Vector((-0.285, edge + 0.008, TOP - 0.06)), Vector((-0.288, edge + 0.009, TOP - 0.16)), Vector((-0.29, edge + 0.01, -0.40))]


def turned(x, y, z, turn):
    return Matrix.Translation((x, y, z)) @ Matrix.Rotation(math.radians(turn), 4, 'Z')


def build_headphones(mats, x, y, turn):
    """Over-ear headphones lying flat: the cups turned flat onto their cushions, the left one swivelled out of line,
    the band on its edge between them."""
    place, a, b = turned(x, y, TOP, turn) @ Matrix.Scale(1.12, 4), 0.080, 0.100
    for side, name, swivel in ((-1, 'left', 17), (1, 'right', -4)):
        cx, cy = side * a, -0.058
        cup = place @ Matrix.Translation((cx, cy, 0)) @ Matrix.Rotation(math.radians(swivel), 4, 'Z') @ Matrix.Translation((-cx, -cy, 0))
        placed(f'Headphone cushion {name}', solid(R.rounded_rect(cx - 0.037, cx + 0.037, cy - 0.047, cy + 0.047, 0.032), 0.0, 0.019),
                 mats['cushion'], cup, 50, 8.5, 6)
        placed(f'Headphone cup {name}', solid(R.rounded_rect(cx - 0.035, cx + 0.035, cy - 0.045, cy + 0.045, 0.031), 0.0175, 0.043),
                 mats['headphones'], cup, 50, 8.0, 6)
    rings = []
    for i in range(49):   # a padded band in the middle, thinner metal sliders at the ends
        t, thick = -0.12 + (math.pi + 0.24) * i / 48, 1.0 if 7 <= i <= 41 else 0.55
        centre = Vector((a * math.cos(t), b * math.sin(t) - 0.010, 0.0))
        out = Vector((b * math.cos(t), a * math.sin(t), 0.0)).normalized()
        rings.append([centre + out * 0.005 * thick * math.copysign(abs(c) ** 0.5, c)
                      + Vector((0, 0, 0.023 + 0.013 * thick * math.copysign(abs(s) ** 0.5, s)))
                      for c, s in ((math.cos(math.tau * k / 16), math.sin(math.tau * k / 16)) for k in range(16))])
    for name, part, mat in (('Headphone band', rings[6:43], 'headphones'), ('Headphone slider left', rings[:8], 'slider'),
                            ('Headphone slider right', rings[41:], 'slider')):
        bm = bmesh.new()
        loft(bm, part)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        placed(name, bm, mats[mat], place, 60)


def build(mats, skip):
    """The desk, the room, everything on the desk and the lights. skip: objects the lights leave out (the glass)."""
    top = solid(R.rounded_rect(DESK_X[0], DESK_X[1], DESK_Y[0], DESK_Y[1], 0.012), TOP - DESK_T, TOP)
    placed('Desk top', top, mats['wood'], Matrix.Identity(4), 30, 2.5)
    placed('Wall', solid(R.rounded_rect(-1.6, 1.8, WALL_Y, WALL_Y + 0.02, 0.001), -0.78, 1.6), mats['wall'], Matrix.Identity(4), None)
    placed('Floor', solid(R.rounded_rect(-1.6, 1.8, -2.0, WALL_Y, 0.001), -0.79, -0.78), mats['floor'], Matrix.Identity(4), None)
    for lx in (DESK_X[0] + 0.05, DESK_X[1] - 0.09):
        for ly in (DESK_Y[0] + 0.05, DESK_Y[1] - 0.09):
            placed('Desk leg', solid(R.rounded_rect(lx, lx + 0.04, ly, ly + 0.04, 0.004), -0.78, TOP - DESK_T - 0.0005),
                   mats['stand'], Matrix.Identity(4), 30, 1)
    askew = Matrix.Translation((0.48, -0.03, 0)) @ Matrix.Rotation(math.radians(1.2), 4, 'Z') @ Matrix.Translation((-0.48, 0.03, 0))
    placed('Desk mat', solid(R.rounded_rect(0.10, 0.86, -0.20, 0.14, 0.012), TOP, TOP + MAT), mats['felt'], askew, 30, 0.8)
    port = build_keyboard(mats, 0.16, -0.135, 6)
    on_mat, on_desk = TOP + MAT + CORD, TOP + CORD
    cable('Keyboard cable', [port, port + Vector((0, 0.022, -0.002)), Vector((port.x - 0.004, 0.075, on_mat)),
                             Vector((port.x - 0.016, 0.128, on_mat)), Vector((port.x - 0.024, 0.17, on_desk)),
                             Vector((0.19, 0.30, on_desk)), Vector((0.175, 0.47, on_desk)), Vector((0.172, DESK_Y[1] - 0.004, on_desk)),
                             Vector((0.170, DESK_Y[1] + 0.006, TOP - 0.03)), Vector((0.169, DESK_Y[1] + 0.008, -0.40))],
          CORD, mats['cord'])
    build_mouse(mats, 0.69, -0.075, 31)
    build_monitor(mats, 0.34, 0.33)
    build_cup(mats, -0.36, 0.22)
    build_plant(mats, 0.80, 0.40)
    build_headphones(mats, 0.625, 0.30, -24)
    # a tall window far to the left, facing the desk, so its edge never cuts across the wall in view
    R.area_light('Window', (-1.45, 0.05, 0.75), Vector((0.15, 0.10, 0.30)), (2.0, 1.4), 110, (0.93, 0.96, 1.0), skip=skip)
    R.area_light('Room bounce', (0.9, -0.9, 0.6), R.CENTRE, (1.0, 0.8), 5, (1.0, 0.95, 0.88), skip=skip)


def world(scene, strength=0.3):
    """The room around the desk: Blender's bundled interior HDRI, packed into the .blend, dim and turned so its
    bright side is on the window's side. It lights but never shows in reflections: its bright side would glare in the
    panel's glass."""
    scene.world.cycles_visibility.glossy = False
    path = Path(bpy.utils.system_resource('DATAFILES', path='studiolights/world')) / 'interior.exr'
    if not path.exists():
        return
    tree = scene.world.node_tree
    background = next(n for n in tree.nodes if n.type == 'BACKGROUND')
    env = tree.nodes.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(str(path))
    env.image.pack()
    mapping = tree.nodes.new('ShaderNodeMapping')
    mapping.inputs['Rotation'].default_value = (0, 0, math.radians(90))
    tree.links.new(tree.nodes.new('ShaderNodeTexCoord').outputs['Generated'], mapping.inputs['Vector'])
    tree.links.new(mapping.outputs['Vector'], env.inputs['Vector'])
    tree.links.new(env.outputs['Color'], background.inputs['Color'])
    background.inputs['Strength'].default_value = strength
