"""Desk console for the GUITION JC1060P470C (the _Y variant in its factory housing), as a FreeCAD Part Design model.

    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" hardware\\make_enclosure.py
    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecad.exe"    hardware\\save_view.py      (stores what is shown)

Writes tessera-enclosure.FCStd with a normal model tree (constrained sketches, pads, pockets, fillets, a chamfer),
a sheet of sizes and the panel as a reference body, and exports the STL and STEP files from the body.

The design: a console that reclines 45 degrees. A short upright apron at the front, a chin under the screen with
the Tessera tile mark pressed into it, the screen set 2 mm into a chamfered frame, a rounded top, a back with air
openings in the same tile pattern, and four recesses for rubber feet. The panel tilts in behind a low lip and is
held by four screws into its corner posts. There is no floor, and it prints standing up without supports.

Sizes are from the manufacturer's files (github.com/wegi1/ESP32P4-JC1060P470C-I_W_Y): the structure drawing gives
outline 181.80 x 113.72, picture 155.01 x 86.72, slab 8.00, raised box 124.66 x 74.67 (16.38 behind the glass),
20.38 over all and posts on 166.00 x 99.00; the specification shows both USB-C sockets facing straight back; the
side photo gives posts about 4.6 mm across that end 13 mm behind the glass. All sizes in millimetres.
"""
import math
import os
from pathlib import Path

import FreeCAD as App
import MeshPart
import Part
import Sketcher
from FreeCAD import Placement, Rotation, Vector

P = dict(
    width=181.80, height=113.72, slab=8.00,   # the panel's flat part (drawing)
    deep=20.38,                               # glass to the tallest part on the back (drawing)
    clearance=0.6,                            # gap around the panel
    tilt=45.0, rear=10.0,                     # degrees from upright: the front reclines, the back leans forward
    apron=10.0,                               # the short upright front
    chin=18.0, brow=16.0,                     # frame below and above the panel, measured along the front
    wall=2.8, side=4.0,                       # shell and end wall thickness
    lip=2.0, lip_h=3.5,                       # the lip that keeps the bottom edge in: thickness, height over the glass
    rim=4.0, rim_low=3.5, rim_t=3.0,          # the rim behind the panel: reach at the sides, top and bottom, thickness
    top_round=10.0, end_round=3.0, frame_chamfer=0.8, base_chamfer=1.2,
    cheek_inset=8.0, cheek_deep=0.6,          # a sunken field on each end
    chin_wall=2.5,                            # what is left under the pocket when the chin is hollowed
    post_deep=13.0, post_gap=0.3,             # the corner posts end this far behind the glass; gap to the screw tabs
    tab_t=3.0, tab_reach=7.0, tab_slope=1.75, # screw tabs: thickness, reach past the post, how steeply they grow from the wall
    screw_hole=2.6, access_hole=8.0,          # hole for an M2 or M2.5 screw; hole in the back for the screwdriver
    mark_tile=3.2, mark_gap=1.2, mark_deep=0.6,   # the tile mark in the chin
    vent_tile=7.0, vent_gap=4.0, vent_cols=11, vent_rows=3, vent_low=26.0,
    cable_d=30.0,                             # the cable opening is an arch this wide
    foot=10.4, foot_deep=1.0, foot_pad=17.0, foot_pad_t=2.4,   # 10 mm stick-on rubber feet
)
OUT = Path(os.environ.get('TESSERA_OUT') or Path(__file__).resolve().parent)

W, H, T, C = P['width'], P['height'], P['slab'], P['clearance']
tilt, rear = math.radians(P['tilt']), math.radians(P['rear'])
sin_t, cos_t, tan_t, tan_r = math.sin(tilt), math.cos(tilt), math.tan(tilt), math.tan(rear)
half = W / 2 + C + P['side']                                   # half the outer width
face = P['chin'] + H + P['brow']                               # length of the reclining front
apex_y, apex_z = face * sin_t, P['apron'] + face * cos_t
foot_back = apex_y + apex_z * tan_r
pocket_deep = P['lip'] + C + T + C                             # front surface to where the panel's back rests
plate = pocket_deep + P['rim_t']                               # thickness of the front where the pocket is cut

doc = App.newDocument('TesseraEnclosure')
sheet = doc.addObject('Spreadsheet::Sheet', 'Sizes')
rows = [('Panel width', 'panelWidth', W), ('Panel height', 'panelHeight', H), ('Slab thickness', 'slab', T),
        ('Clearance', 'clearance', C), ('Recline of the front (deg)', 'tilt', P['tilt']), ('Lean of the back (deg)', 'rear', P['rear']),
        ('Wall', 'wall', P['wall']), ('End wall', 'endWall', P['side']), ('Lip thickness', 'lip', P['lip']),
        ('Outer width', 'outerWidth', 2 * half), ('Inner width', 'innerWidth', 2 * (half - P['side'])),
        ('Pocket depth', 'pocketDepth', pocket_deep), ('Front thickness', 'frontThickness', plate),
        ('Tab thickness', 'tabThickness', P['tab_t']), ('Mark depth', 'markDepth', P['mark_deep']),
        ('Cheek field depth', 'cheekDepth', P['cheek_deep']), ('Foot recess depth', 'footDepth', P['foot_deep'])]
sheet.set('A1', 'Size')
sheet.set('B1', 'mm')
for number, (label, alias, value) in enumerate(rows, start=2):
    sheet.set(f'A{number}', label)
    sheet.set(f'B{number}', f'{value:.3f}')
    sheet.setAlias(f'B{number}', alias)
doc.recompute()

body = doc.addObject('PartDesign::Body', 'Enclosure')
planes = {feature.Role: feature for feature in body.Origin.OriginFeatures}


def attach(feature, plane, offset=None):
    feature.AttachmentSupport = [(plane, '')]
    feature.MapMode = 'FlatFace'
    if offset:
        feature.AttachmentOffset = offset


def pin(sketch, geometry, x, y, point=1):
    """Fix a point (the start of a line, or the centre of a circle with point=3) with two dimensions from the origin."""
    for axis, value, on_axis in (('DistanceX', x, -2), ('DistanceY', y, -1)):
        if abs(value) < 1e-9:
            sketch.addConstraint(Sketcher.Constraint('PointOnObject', geometry, point, on_axis))
        elif value > 0:
            sketch.addConstraint(Sketcher.Constraint(axis, -1, 1, geometry, point, value))
        else:
            sketch.addConstraint(Sketcher.Constraint(axis, geometry, point, -1, 1, -value))


def polygon(sketch, points):
    """A closed outline whose every corner is dimensioned from the origin."""
    first = sketch.GeometryCount
    count = len(points)
    for index, point in enumerate(points):
        following = points[(index + 1) % count]
        sketch.addGeometry(Part.LineSegment(Vector(point[0], point[1], 0), Vector(following[0], following[1], 0)), False)
    for index in range(count):
        sketch.addConstraint(Sketcher.Constraint('Coincident', first + index, 2, first + (index + 1) % count, 1))
    for index, point in enumerate(points):
        pin(sketch, first + index, point[0], point[1])


def rectangle(sketch, x0, x1, y0, y1):
    polygon(sketch, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def circle(sketch, x, y, diameter):
    index = sketch.addGeometry(Part.Circle(Vector(x, y, 0), Vector(0, 0, 1), diameter / 2), False)
    sketch.addConstraint(Sketcher.Constraint('Diameter', index, diameter))
    pin(sketch, index, x, y, point=3)


def sketch_on(name, plane, offset=None):
    sketch = body.newObject('Sketcher::SketchObject', name)
    attach(sketch, plane, offset)
    return sketch


def extrude(kind, name, sketch, length, symmetric=False, reversed_=False, expression=None):
    feature = body.newObject('PartDesign::' + kind, name)
    feature.Profile = sketch
    if length is None:
        feature.Type = 'ThroughAll'
    else:
        feature.Type = 'Length'
        feature.Length = length
    if symmetric:
        if hasattr(feature, 'SideType'):
            feature.SideType = 'Symmetric'
        else:
            feature.Midplane = True
    feature.Reversed = reversed_
    if expression:
        feature.setExpression('Length', 'Sizes.' + expression)
    sketch.Visibility = False
    return feature


def dress(kind, name, base, edges, size):
    feature = body.newObject('PartDesign::' + kind, name)
    feature.Base = (base, edges)
    setattr(feature, 'Radius' if kind == 'Fillet' else 'Size', size)
    doc.recompute()
    assert feature.isValid() and not feature.Shape.isNull(), f'{name} failed: {feature.getStatusString()}'
    return feature


def edges_of(feature, test):
    return [f'Edge{index + 1}' for index, edge in enumerate(feature.Shape.Edges) if test(edge)]


# --- 1. the side outline: apron, reclining front, top, back; pushed out to the full width -------------------
outline = sketch_on('Outline', planes['YZ_Plane'])              # sketch x is depth, sketch y is height
polygon(outline, [(0, 0), (0, P['apron']), (apex_y, apex_z), (foot_back, 0)])
shell = extrude('Pad', 'Shell', outline, 2 * half, symmetric=True, expression='outerWidth')
doc.recompute()
round_top = dress('Fillet', 'RoundTop', shell, edges_of(shell, lambda e: e.BoundBox.ZMin > apex_z - 1e-6 and e.Length > half), P['top_round'])
soft_front = dress('Fillet', 'SoftFront', round_top, edges_of(round_top, lambda e: e.Length > half and abs(e.BoundBox.ZMin - P['apron']) < 1e-6
                                                              and abs(e.BoundBox.ZMax - P['apron']) < 1e-6), 4.0)
round_ends = dress('Fillet', 'RoundEnds', soft_front, edges_of(soft_front, lambda e: e.BoundBox.XLength < 1e-6 and e.BoundBox.ZMax > 1e-3
                                                               and abs(abs(e.BoundBox.XMin) - half) < 1e-6), P['end_round'])
base_edges = edges_of(round_ends, lambda e: e.BoundBox.ZMax < 1e-6 and e.Length > 5)
floating = dress('Chamfer', 'BaseChamfer', round_ends, base_edges, P['base_chamfer'])
outer_solid = floating.Shape.copy()

# --- 2. hollow it: a thick front for the pocket, thin back, no floor ----------------------------------------
below = -1.0                                                    # the sketch reaches under the desk, so no floor is left
front_at = lambda z: (z - P['apron']) * tan_t + plate / cos_t   # inside of the front, as depth at a height
back_at = lambda z: foot_back - z * tan_r - P['wall'] / math.cos(rear)
top_z = (foot_back - P['wall'] / math.cos(rear) - plate / cos_t + P['apron'] * tan_t) / (tan_t + tan_r)
inside = sketch_on('Inside', planes['YZ_Plane'])
assert front_at(below) >= P['wall'], 'the apron is too low for this front thickness'
polygon(inside, [(front_at(below), below), (front_at(top_z), top_z), (back_at(below), below)])
hollow = extrude('Pocket', 'Hollow', inside, 2 * (half - P['side']), symmetric=True, expression='innerWidth')
doc.recompute()
roof = min(face.distToShape(Part.Vertex(Vector(0, front_at(top_z), top_z)))[0] for face in outer_solid.Faces)
assert roof >= 2.4, f'the top is only {roof:.1f} mm thick over the hollow'

# the chin and the apron do not need the thick front: hollow them to the wall thickness
at = lambda up_front, depth: (up_front * sin_t + depth * cos_t, P['apron'] + up_front * cos_t - depth * sin_t)   # depth and height
chin_top = P['chin'] - C - P['chin_wall']
start = P['wall'] * (1 - cos_t) / sin_t                          # where the inside of the apron meets the inside of the front
light_sketch = sketch_on('ChinInside', planes['YZ_Plane'])
polygon(light_sketch, [(P['wall'], below), at(start, P['wall']), at(chin_top, P['wall']), at(chin_top, plate + 0.5), (front_at(below) + 0.5, below)])
lighten = extrude('Pocket', 'HollowChin', light_sketch, 2 * (half - P['side']), symmetric=True, expression='innerWidth')


# --- 3. planes on and behind the reclining front: x across, y up the front from the top of the apron ----------
def front_plane(name, depth):
    feature = body.newObject('PartDesign::Plane', name)
    attach(feature, planes['XZ_Plane'], Placement(Vector(0, P['apron'] - depth * sin_t, -depth * cos_t), Rotation(Vector(1, 0, 0), -P['tilt'])))
    feature.Visibility = False
    return feature


front = front_plane('FrontPlane', 0.0)
doc.recompute()
up = front.Placement.Rotation.multVec(Vector(0, 1, 0))
outward = front.Placement.Rotation.multVec(Vector(0, 0, 1))
assert abs(up.y - sin_t) < 1e-6 and abs(up.z - cos_t) < 1e-6 and outward.y < 0, f'the front plane leans the wrong way: {up} {outward}'
to_front = front.Placement.inverse()                            # world point -> (across, up the front, out of the front)

panel_low = P['chin']                                           # the panel's bottom edge, measured up the front
recess_sketch = sketch_on('PanelOutline', front)
rectangle(recess_sketch, -W / 2 - C, W / 2 + C, panel_low - C, panel_low + H + C)
recess = extrude('Pocket', 'PanelPocket', recess_sketch, pocket_deep, expression='pocketDepth')
doc.recompute()


def frame_edge(edge):
    """The top and the two sides of the pocket's mouth: on the front surface, not the bottom edge (the lip goes there)."""
    ends = [to_front.multVec(vertex.Point) for vertex in edge.Vertexes]
    if len(ends) != 2 or any(abs(point.z) > 1e-6 for point in ends):
        return False
    inside_frame = all(abs(point.x) < W / 2 + C + 1e-3 and panel_low - C - 1e-3 < point.y < panel_low + H + C + 1e-3 for point in ends)
    return inside_frame and max(point.y for point in ends) > panel_low + 1


chamfer = dress('Chamfer', 'FrameChamfer', recess, edges_of(recess, frame_edge), P['frame_chamfer'])

opening_sketch = sketch_on('RimOpening', front)
rectangle(opening_sketch, -W / 2 + P['rim'], W / 2 - P['rim'], panel_low + P['rim_low'], panel_low + H - P['rim_low'])
opening = extrude('Pocket', 'BackOpening', opening_sketch, plate + 1.0)

lip_sketch = sketch_on('LipOutline', front)
rectangle(lip_sketch, -W / 2 - C - P['frame_chamfer'], W / 2 + C + P['frame_chamfer'], panel_low - C, panel_low + P['lip_h'])
lip = extrude('Pad', 'Lip', lip_sketch, P['lip'], reversed_=True, expression='lip')

# the Tessera mark, pressed into the chin: three by three tiles, the top right one lifted like in the logo
mark_sketch = sketch_on('MarkTiles', front)
pitch = P['mark_tile'] + P['mark_gap']
mark_low = (panel_low - C - (3 * P['mark_tile'] + 2 * P['mark_gap'])) / 2
for row in range(3):
    for column in range(3):
        lift = 0.9 if (row, column) == (2, 2) else 0.0
        x0, y0 = (column - 1.5) * pitch + P['mark_gap'] / 2 + lift, mark_low + row * pitch + lift
        rectangle(mark_sketch, x0, x0 + P['mark_tile'], y0, y0 + P['mark_tile'])
mark = extrude('Pocket', 'TileMark', mark_sketch, P['mark_deep'], expression='markDepth')

# --- 4. screw tabs behind the four corner posts ------------------------------------------------------------------
# The posts have brass inserts that open to the back. A tab sits just behind each post; a screw goes through the tab
# into the post and pulls the panel against the rim. The tabs grow out of the end walls steeply enough to print
# without supports, and the back has a hole in line with each top screw for the screwdriver.
tab_depth = P['lip'] + C + P['post_deep'] + P['post_gap']        # front surface to the face of the tabs
post_x = 83.0                                                     # posts sit on 166.00 x 99.00 (drawing)
post_low, post_high = panel_low + (H - 99.0) / 2, panel_low + (H + 99.0) / 2
tab_in, tab_wall = post_x - P['tab_reach'], half - P['side'] + 1.0   # the tab starts 1 mm inside the end wall
tab_plane = front_plane('TabPlane', tab_depth)
tab_sketch = sketch_on('TabOutlines', tab_plane)
for sx in (-1, 1):
    high = post_high + P['tab_reach']
    polygon(tab_sketch, [(sx * tab_wall, post_high - P['tab_reach'] - (tab_wall - tab_in) * P['tab_slope']), (sx * tab_wall, high),
                         (sx * tab_in, high), (sx * tab_in, post_high - P['tab_reach'])])
    polygon(tab_sketch, [(sx * tab_wall, -30.0), (sx * tab_wall, post_low + P['tab_reach']),
                         (sx * tab_in, post_low + P['tab_reach']), (sx * tab_in, -30.0)])       # bottom tab, down to the desk
tabs = extrude('Pad', 'ScrewTabs', tab_sketch, P['tab_t'], reversed_=True, expression='tabThickness')

hole_sketch = sketch_on('ScrewHoleCentres', tab_plane)
for sx in (-1, 1):
    for y in (post_low, post_high):
        circle(hole_sketch, sx * post_x, y, P['screw_hole'])
holes = extrude('Pocket', 'ScrewHoles', hole_sketch, P['tab_t'] + 1.0)

access_sketch = sketch_on('AccessHoleCentres', front_plane('AccessPlane', tab_depth + P['tab_t'] + 0.5))
for sx in (-1, 1):
    circle(access_sketch, sx * post_x, post_high, P['access_hole'])
access = extrude('Pocket', 'ScrewAccess', access_sketch, None)

# --- 5. the base: pads with recesses for stick-on rubber feet, and nothing below the desk ---------------------
pad_sketch = sketch_on('FootPadOutlines', planes['XY_Plane'])
feet = []
for sx in (-1, 1):
    x_out, x_in = sx * (half - 2.5), sx * (half - 2.5 - P['foot_pad'])      # clear of the chamfer round the base
    for y0 in (2.5, foot_back - 3.5 - P['foot_pad']):
        rectangle(pad_sketch, min(x_out, x_in), max(x_out, x_in), y0, y0 + P['foot_pad'])
        feet.append(((x_out + x_in) / 2, y0 + P['foot_pad'] / 2))
pads = extrude('Pad', 'FootPads', pad_sketch, P['foot_pad_t'])

desk_sketch = sketch_on('BelowDesk', planes['XY_Plane'])
rectangle(desk_sketch, -half - 5, half + 5, -10, foot_back + 10)
trim = extrude('Pocket', 'TrimAtDesk', desk_sketch, 80.0)

foot_sketch = sketch_on('FootCentres', planes['XY_Plane'])
for x, y in feet:
    circle(foot_sketch, x, y, P['foot'])
recesses = extrude('Pocket', 'FootRecesses', foot_sketch, P['foot_deep'], reversed_=True, expression='footDepth')

# --- 6. a sunken field on each end, following the outline ------------------------------------------------------
field = Part.Face(Part.makePolygon([Vector(0, 0, 0), Vector(0, P['apron'], 0), Vector(apex_y, apex_z, 0), Vector(foot_back, 0, 0), Vector(0, 0, 0)]))
field_points = [(v.X, v.Y) for v in field.makeOffset2D(-P['cheek_inset'], join=2).OuterWire.OrderedVertexes]
cheeks = []
for name, x, flip in (('Right', half, False), ('Left', -half, True)):
    cheek_sketch = sketch_on(f'CheekField{name}', planes['YZ_Plane'], Placement(Vector(0, 0, x), Rotation()))
    polygon(cheek_sketch, field_points)
    cheeks.append(extrude('Pocket', f'Cheek{name}', cheek_sketch, P['cheek_deep'], reversed_=flip, expression='cheekDepth'))

# --- 7. the back: an arch for the cable and air openings in the tile pattern ----------------------------------
back_plane = lambda name: sketch_on(name, planes['XZ_Plane'], Placement(Vector(0, 0, -apex_y), Rotation()))   # upright, through the top, facing the back
notch_sketch = back_plane('CableArch')
circle(notch_sketch, 0, 0, P['cable_d'])
notch = extrude('Pocket', 'CableOpening', notch_sketch, foot_back - apex_y + 5)

vent_sketch = back_plane('VentTiles')
vent_pitch = P['vent_tile'] + P['vent_gap']
for row in range(P['vent_rows']):
    for column in range(P['vent_cols']):
        x0 = (column - P['vent_cols'] / 2) * vent_pitch + P['vent_gap'] / 2
        z0 = P['vent_low'] + row * vent_pitch
        rectangle(vent_sketch, x0, x0 + P['vent_tile'], z0, z0 + P['vent_tile'])
vents = extrude('Pocket', 'AirTiles', vent_sketch, foot_back - apex_y + 5)
doc.recompute()

features = (shell, round_top, soft_front, round_ends, floating, hollow, lighten, recess, chamfer, opening, lip, mark, tabs, holes, access, pads, trim,
            recesses, *cheeks, notch, vents)
for feature in features:
    assert feature.isValid() and not feature.Shape.isNull(), f'{feature.Name} did not build: {feature.getStatusString()}'
    print('STEP', feature.Name, f'{feature.Shape.Volume / 1000:.1f} cm3')
for sketch in [ob for ob in body.Group if ob.TypeId == 'Sketcher::SketchObject']:
    assert sketch.solve() == 0, f'{sketch.Name} is not fully constrained ({sketch.solve()} degrees of freedom)'
solid = body.Shape
assert solid.isValid() and len(solid.Solids) == 1, 'the body is not one valid solid'
outside = solid.cut(outer_solid).Volume
assert outside < 1.0, f'something sticks out of the shell ({outside:.1f} mm3)'

# --- the panel as the manufacturer's files give it: it must fit without touching -----------------------------
frame = Placement(front.Placement.multVec(Vector(0, panel_low, -(C + P['lip']))), front.Placement.Rotation)   # y = 0 is the glass, behind the lip


def block(x0, x1, y0, y1, z0, z1):
    """A box in the panel's frame: x across, y into the shell from the glass, z up the panel."""
    part = Part.makeBox(x1 - x0, z1 - z0, y1 - y0, Vector(x0, z0, -y1))
    part.Placement = frame
    return part


BOX_W, BOX_H, BOX_DEEP, POST_D, POST_DEEP = 124.66, 74.67, 16.38, 5.5, P['post_deep']
panel = block(-W / 2, W / 2, 0, T, 0, H).fuse(block(-BOX_W / 2, BOX_W / 2, T, BOX_DEEP, (H - BOX_H) / 2, (H + BOX_H) / 2))
panel = panel.fuse(block(8, 26, BOX_DEEP, P['deep'], 52, 68))                    # the Ethernet jack stands 4 mm proud
for sx in (-1, 1):
    for z in ((H - 99) / 2, (H + 99) / 2):
        post = Part.makeCylinder(POST_D / 2, POST_DEEP - T, Vector(sx * post_x, z, -T), Vector(0, 0, -1))
        post.Placement = frame
        panel = panel.fuse(post)
glass = frame.multVec(Vector(0, H / 2, 0))
assert abs(to_front.multVec(glass).z + C + P['lip']) < 1e-6, 'the reference panel is not where the pocket is'
clash = solid.common(panel).Volume
assert clash < 0.5, f'the panel collides with the shell ({clash:.1f} mm3)'
for sx in (-1, 1):                                              # a 35 mm USB plug in either socket position
    for z in (75.2, 62.5):
        plug = block(sx * (BOX_W / 2 - 13) - 6.5, sx * (BOX_W / 2 - 13) + 6.5, BOX_DEEP, BOX_DEEP + 35, z - 4, z + 4)
        hit = solid.common(plug).Volume
        assert hit < 0.5, f'a USB plug would hit the shell ({hit:.0f} mm3)'
reference = doc.addObject('Part::Feature', 'PanelReference')
reference.Shape = panel.removeSplitter()
reference.Label = 'Panel (reference, not printed)'
doc.recompute()

OUT.mkdir(parents=True, exist_ok=True)
doc.saveAs(str(OUT / 'tessera-enclosure.FCStd'))
solid.exportStep(str(OUT / 'tessera-enclosure.step'))
mesh = MeshPart.meshFromShape(Shape=solid, LinearDeflection=0.05, AngularDeflection=0.26, Relative=False)
mesh.write(str(OUT / 'tessera-enclosure.stl'))
if os.environ.get('TESSERA_REVIEW'):
    MeshPart.meshFromShape(Shape=panel, LinearDeflection=0.1, AngularDeflection=0.3, Relative=False).write(os.environ['TESSERA_REVIEW'])
box = solid.BoundBox
print(f'RESULT size {box.XLength:.1f} x {box.YLength:.1f} x {box.ZLength:.1f} mm, volume {solid.Volume / 1000:.1f} cm3, '
      f'facets {mesh.CountFacets}, solid {mesh.isSolid()}, non-manifold {mesh.hasNonManifolds()}, clash {clash:.2f} mm3')
