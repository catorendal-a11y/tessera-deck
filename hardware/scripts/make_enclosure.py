"""Desk console for the GUITION JC1060P470C (the _Y variant in its factory housing), as a FreeCAD Part Design model.

    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecadcmd.exe" hardware\\scripts\\make_enclosure.py
    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecad.exe"    hardware\\scripts\\save_view.py      (stores what is shown)

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

With TESSERA_BOARD=crowpanel it builds the same console for the Elecrow CrowPanel Advance 7.0 without its casing
and writes tessera-enclosure-crowpanel.*. Its sizes are from Elecrow's STEP model (github.com/Elecrow-RD, the
CrowPanel Advanced 7inch ESP32-P4 repository, "3D file"): board 176.90 x 104.00 with M3 holes on 171.00 x 98.00, glass
164.90 x 100.00 centred on it, 7.70 from the glass to the back of the board. The front laps 1 mm over the glass, so
the board goes in from below, through the open base, straight up into place; what it passes on the way is cut away
inside the shell. Four M3 screws go in from behind, through the corner holes into the front beside the glass; both
USB-C sockets and the power switch reach out through windows in the left end.
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
    wall=2.8, side=4.0, side_gap=0.0,         # shell and end wall thickness; extra room at each end of the panel
    lip=2.0, lip_h=3.5,                       # the lip that keeps the bottom edge in: thickness, height over the glass
    rim=4.0, rim_low=3.5, rim_t=3.0,          # the rim behind the panel: reach at the sides, top and bottom, thickness
    top_round=10.0, end_round=3.0, frame_chamfer=0.8, base_chamfer=1.2,
    cheek_inset=8.0, cheek_deep=0.6,          # a sunken field on each end
    chin_wall=2.5,                            # what is left under the pocket when the chin is hollowed
    chin_web=1.6,                             # an upright wall under the back edge of that shelf, so it prints from the bed
    post_deep=13.0, post_gap=0.3,             # the corner posts end this far behind the glass; gap to the screw tabs
    tab_t=3.0, tab_reach=7.0, tab_slope=1.75, # screw tabs: thickness, reach past the post, how steeply they grow from the wall
    screw_hole=2.6, access_hole=8.0,          # hole for an M2 or M2.5 screw; hole in the back for the screwdriver
    mark_tile=3.2, mark_gap=1.2, mark_deep=0.6,   # the tile mark in the chin
    vent_tile=7.0, vent_gap=4.0, vent_cols=11, vent_rows=3, vent_low=26.0,
    cable_d=30.0,                             # the cable opening is an arch this wide
    foot=10.4, foot_deep=1.0, foot_pad=17.0, foot_pad_t=2.4,   # 10 mm stick-on rubber feet
    foot_pad_in=2.0,                          # the pads start this far inside the front and the back, so they join the walls
)
BOARD = os.environ.get('TESSERA_BOARD', 'guition')
assert BOARD in ('guition', 'crowpanel'), f'TESSERA_BOARD must be guition or crowpanel, not {BOARD}'
CROW = BOARD == 'crowpanel'
post_x, post_pitch = 83.0, 99.0                                  # GUITION posts on 166.00 x 99.00 (drawing)
if CROW:
    P.update(width=176.90, height=104.00, slab=7.70, deep=15.80,   # board, and glass to the back of the board
             rim_t=6.0,                                            # a thicker front round the board
             foot_pad=13.0,                                        # shorter pads, clear of the board's way in
             side_gap=1.5)                                         # the USB-C sockets stand 1 mm past the board's edge
    post_x, post_pitch = 85.5, 98.0                               # M3 holes on 171.00 x 98.00
    glass_w, glass_h, glass_to_board = 164.90, 100.00, 6.00       # glass centred on the board; its front to the board's
NAME = 'tessera-enclosure' + ('-crowpanel' if CROW else '')
OUT = Path(os.environ.get('TESSERA_OUT') or Path(__file__).resolve().parents[1] / ('crowpanel' if CROW else 'console'))

W, H, T, C = P['width'], P['height'], P['slab'], P['clearance']
tilt, rear = math.radians(P['tilt']), math.radians(P['rear'])
sin_t, cos_t, tan_t, tan_r = math.sin(tilt), math.cos(tilt), math.tan(tilt), math.tan(rear)
half = W / 2 + C + P['side_gap'] + P['side']                   # half the outer width
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

# The shelf under the pocket would start in the air, 175 mm from end wall to end wall. An upright wall under its back
# edge carries it from the bed; the shelf then grows forward from the wall at 45 degrees until it meets the front.
web_y, web_z = at(chin_top, plate)
web_sketch = sketch_on('ChinWebOutline', planes['YZ_Plane'])
polygon(web_sketch, [(web_y - P['chin_web'], below), (web_y, below), (web_y, web_z + 0.2), (web_y - P['chin_web'], web_z + P['chin_web'] + 0.2)])
web = extrude('Pad', 'ChinWeb', web_sketch, 2 * (half - P['side']) + 1.0, symmetric=True)


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
post_low, post_high = panel_low + (H - post_pitch) / 2, panel_low + (H + post_pitch) / 2
recess_sketch = sketch_on('PanelOutline', front)
if CROW:   # the window: the front laps 1 mm over each edge of the glass
    rectangle(recess_sketch, -glass_w / 2 + 1, glass_w / 2 - 1, panel_low + (H - glass_h) / 2 + 1, panel_low + (H + glass_h) / 2 - 1)
else:
    rectangle(recess_sketch, -W / 2 - C, W / 2 + C, panel_low - C, panel_low + H + C)
recess = extrude('Pocket', 'PanelPocket', recess_sketch, pocket_deep, expression='pocketDepth')
doc.recompute()


def frame_edge(edge):
    """The top and the two sides of the pocket's mouth: on the front surface, not the bottom edge (the lip goes there)."""
    ends = [to_front.multVec(vertex.Point) for vertex in edge.Vertexes]
    if len(ends) != 2 or any(abs(point.z) > 1e-6 for point in ends):
        return False
    inside_frame = all(abs(point.x) < W / 2 + C + 1e-3 and panel_low - C - 1e-3 < point.y < panel_low + H + C + 1e-3 for point in ends)
    return inside_frame and (CROW or max(point.y for point in ends) > panel_low + 1)   # the CrowPanel has no lip


chamfer = dress('Chamfer', 'FrameChamfer', recess, edges_of(recess, frame_edge), P['frame_chamfer'])

glass_in = None
if CROW:   # behind the window: room for the glass, then the board's outline open to the back, so it goes in from below
    glass_depth, board_depth = C + P['lip'] - 0.2, C + P['lip'] + glass_to_board   # 0.2 over the glass; the board's face
    glass_sketch = sketch_on('GlassOutline', front_plane('GlassPlane', glass_depth))
    rectangle(glass_sketch, -glass_w / 2 - 0.3, glass_w / 2 + 0.3, panel_low + (H - glass_h) / 2 - 0.3, panel_low + (H + glass_h) / 2 + 0.3)
    glass_in = extrude('Pocket', 'GlassRecess', glass_sketch, board_depth - glass_depth + 0.1)
    board_plane = front_plane('BoardPlane', board_depth)
    opening_sketch = sketch_on('RimOpening', board_plane)
    rectangle(opening_sketch, -W / 2 - C - P['side_gap'], W / 2 + C + P['side_gap'], panel_low - C, panel_low + H + C)
    opening = extrude('Pocket', 'BackOpening', opening_sketch, plate + 1.0 - board_depth)
else:
    opening_sketch = sketch_on('RimOpening', front)
    rectangle(opening_sketch, -W / 2 + P['rim'], W / 2 - P['rim'], panel_low + P['rim_low'], panel_low + H - P['rim_low'])
    opening = extrude('Pocket', 'BackOpening', opening_sketch, plate + 1.0)

lip = None                                                      # the CrowPanel's bottom screws sit where the lip would be
if not CROW:
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
tab_in, tab_wall = post_x - P['tab_reach'], half - P['side'] + 1.0   # the tab starts 1 mm inside the end wall
tabs = reach = None
if not CROW:
    tab_plane = front_plane('TabPlane', tab_depth)
    tab_sketch = sketch_on('TabOutlines', tab_plane)
    for sx in (-1, 1):
        high = post_high + P['tab_reach']
        polygon(tab_sketch, [(sx * tab_wall, post_high - P['tab_reach'] - (tab_wall - tab_in) * P['tab_slope']), (sx * tab_wall, high),
                             (sx * tab_in, high), (sx * tab_in, post_high - P['tab_reach'])])
        polygon(tab_sketch, [(sx * tab_wall, -30.0), (sx * tab_wall, post_low + P['tab_reach']),
                             (sx * tab_in, post_low + P['tab_reach']), (sx * tab_in, -30.0)])       # bottom tab, down to the desk
    tabs = extrude('Pad', 'ScrewTabs', tab_sketch, P['tab_t'], reversed_=True, expression='tabThickness')

# The rim over the back opening would also start in the air, from one side of the opening to the other. The space
# between it and the back is filled from where a 45 degree slope down from the rim's lower edge meets the back, so
# the rim grows out of the back wall. The screwdriver holes below are cut through it.
brace_y, brace_z = at(panel_low + H + (C if CROW else -P['rim_low']), plate)   # the CrowPanel has no top rim
brace_low = (brace_y + brace_z - back_at(0)) / (1 - tan_r)       # the height where that slope meets the inside of the back
brace_sketch = sketch_on('TopBraceOutline', planes['YZ_Plane'])
polygon(brace_sketch, [(brace_y - 0.3, brace_z + 0.3), (back_at(brace_low) + 0.5, brace_low - 0.5), (back_at(top_z) + 0.5, top_z), (front_at(top_z) - 0.5, top_z)])
brace = None if CROW else extrude('Pad', 'TopBrace', brace_sketch, 2 * (half - P['side']) + 1.0, symmetric=True)   # the CrowPanel prints on its front

hole_sketch = sketch_on('ScrewHoleCentres', board_plane if CROW else tab_plane)
for sx in (-1, 1):
    for y in (post_low, post_high):
        circle(hole_sketch, sx * post_x, y, P['screw_hole'])
if CROW:   # from the board's face towards the front, leaving 1 mm of the front over each hole
    holes = extrude('Pocket', 'ScrewHoles', hole_sketch, board_depth - 1.0, reversed_=True)
else:
    holes = extrude('Pocket', 'ScrewHoles', hole_sketch, P['tab_t'] + 1.0)

# the back has a hole in line with each top screw for the screwdriver; the CrowPanel's bottom ones are reached from below
access_sketch = sketch_on('AccessHoleCentres', front_plane('AccessPlane', board_depth + T - glass_to_board + 3.5 if CROW else tab_depth + P['tab_t'] + 0.5))
for sx in (-1, 1):
    circle(access_sketch, sx * post_x, post_high, 6.5 if CROW else P['access_hole'])
access = extrude('Pocket', 'ScrewAccess', access_sketch, None)
if CROW:
    # both USB-C sockets and the power switch face out of the left end; the windows start behind the front frame
    side_sketch = sketch_on('SideWindowOutlines', front_plane('SidePlane', 7.1))
    middle = panel_low + H / 2
    rectangle(side_sketch, -half - 1.0, -W / 2 - C + 1.0, middle - 17.5, middle + 17.5)   # two plugs, 12.4 x 6.5 each
    rectangle(side_sketch, -half - 1.0, -W / 2 - C + 1.0, middle + 22.0, middle + 33.0)   # the power switch
    reach = extrude('Pocket', 'SideWindows', side_sketch, 8.9)

# --- 5. the base: pads with recesses for stick-on rubber feet, and nothing below the desk ---------------------
pad_sketch = sketch_on('FootPadOutlines', planes['XY_Plane'])
feet = []
for sx in (-1, 1):
    x_out, x_in = sx * (half - 2.5), sx * (half - 2.5 - P['foot_pad'])      # clear of the chamfer round the base
    for y0 in (P['foot_pad_in'], foot_back - P['foot_pad_in'] - P['foot_pad']):   # inside the walls, clear of the base chamfer
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

features = [feature for feature in (shell, round_top, soft_front, round_ends, floating, hollow, lighten, web, recess, chamfer, glass_in, opening, lip, mark,
                                    tabs, brace, holes, access, reach, pads, trim, recesses, *cheeks, notch, vents) if feature is not None]
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


def model_block(x0, x1, y0, y1, z0, z1):
    """A box in Elecrow's CrowPanel model: x across as seen from the front, y towards the viewer with the glass front at
    2.0, z down the panel with the board centred on 0."""
    return block(x0, x1, 2.0 - y1, 2.0 - y0, 52.0 - z1, 52.0 - z0)


if CROW:
    # glass, display, board, and the parts on the back of the board, from the bounding boxes in Elecrow's STEP model
    # (the optional camera is left out: it stands 11 mm over the top edge of the board, and there is no room for it)
    parts = [(-82.45, 82.45, -3.5, 2.0, -50.0, 50.0), (-88.45, 88.45, -5.7, -4.0, -52.0, 52.0),
             (-44.45, -30.45, -5.9, 2.0, -42.5, 51.2), (-9.0, 7.0, -5.9, -0.62, -0.3, 50.7),            # display flex cables
             (-25.6, 25.6, -9.2, -4.3, 44.2, 50.8), (71.85, 88.45, -8.11, -5.6, -32.0, -18.8),          # GPIO header, ESP32-C6
             (-74.65, -69.75, -10.7, -5.4, -50.0, -31.72), (-59.15, -54.25, -10.7, -5.4, -50.0, -31.72),  # module headers
             (-10.3, 8.3, -8.8, -5.65, -3.7, 1.7), (-40.75, -34.15, -8.6, -5.69, -45.9, -40.5),
             (-86.45, -80.75, -12.7, -2.7, 25.94, 38.44), (-87.1, -80.25, -10.85, -5.4, -31.94, -22.94),  # UART3, power switch
             (64.45, 76.45, -13.8, -5.4, -50.01, -43.8), (42.45, 54.45, -13.8, -5.4, -50.01, -43.8),      # UART1, I2C1
             (-76.45, -68.44, -11.18, -5.58, 41.41, 49.91), (48.7, 56.71, -11.18, -5.58, 41.41, 49.91),
             (-60.45, -52.44, -11.18, -5.58, 41.41, 49.91),                                               # speakers, battery
             (-89.45, -81.87, -8.86, -4.7, 6.0, 14.94), (-89.45, -81.87, -8.86, -4.7, -14.94, -6.0),      # USB-C
             (81.95, 86.45, -10.2, -5.7, 31.25, 38.25), (81.95, 86.45, -10.2, -5.7, 16.75, 23.75),        # BOOT, RESET
             (82.73, 87.45, -6.96, -5.7, -42.0, -38.24), (-87.45, -82.73, -6.96, -5.7, -42.0, -38.24)]    # microphones
    panel = model_block(*parts[0])
    for part in parts[1:]:
        panel = panel.fuse(model_block(*part))
else:
    BOX_W, BOX_H, BOX_DEEP, POST_D, POST_DEEP = 124.66, 74.67, 16.38, 5.5, P['post_deep']
    panel = block(-W / 2, W / 2, 0, T, 0, H).fuse(block(-BOX_W / 2, BOX_W / 2, T, BOX_DEEP, (H - BOX_H) / 2, (H + BOX_H) / 2))
    panel = panel.fuse(block(8, 26, BOX_DEEP, P['deep'], 52, 68))                    # the Ethernet jack stands 4 mm proud
    for sx in (-1, 1):
        for z in ((H - 99) / 2, (H + 99) / 2):
            post = Part.makeCylinder(POST_D / 2, POST_DEEP - T, Vector(sx * post_x, z, -T), Vector(0, 0, -1))
            post.Placement = frame
            panel = panel.fuse(post)
if CROW:   # room in the front for the display cables and the pin header that reach past the board's face
    for x0, x1, y0, y1, z0, z1 in parts[2:]:
        if 2.0 - y1 < glass_to_board:
            solid = solid.cut(model_block(x0 - 0.3, x1 + 0.3, y0 - 0.3, y1 + 0.3, z0 - 0.3, z1 + 0.3))
    # The board goes in from below, through the open base, straight up into place. Everything it passes on the way
    # is cut away with 0.3 mm to spare: the sockets on its back then clear the shell, and the glass clears the front.
    drop = frame.Rotation.inverted().multVec(Vector(0, 0, -150.0))   # straight down, in the panel's frame

    def hull(points):
        points, lower, upper = sorted(set(points)), [], []
        cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        for chain, ordered in ((lower, points), (upper, points[::-1])):
            for point in ordered:
                while len(chain) > 1 and cross(chain[-2], chain[-1], point) <= 0:
                    chain.pop()
                chain.append(point)
        return lower[:-1] + upper[:-1]

    def swept(x0, x1, y0, y1, z0, z1, m=0.3):
        """What a part in Elecrow's model passes on its way up from under the desk."""
        corners = [(52.0 - z, y - 2.0) for z in (z0 - m, z1 + m) for y in (y0 - m, y1 + m)]   # (up, out) in the frame
        outline = hull(corners + [(u + drop.y, o + drop.z) for u, o in corners])
        part = Part.Face(Part.makePolygon([Vector(x0 - m, u, o) for u, o in outline + outline[:1]])).extrude(Vector(x1 - x0 + 2 * m, 0, 0))
        part.Placement = frame
        return part
    path = swept(*parts[0])
    for part in parts[1:]:
        path = path.fuse(swept(*part))
    solid = solid.cut(path).removeSplitter()
    assert solid.isValid() and len(solid.Solids) == 1, 'the console is not one valid solid after the cable room'
glass = frame.multVec(Vector(0, H / 2, 0))
assert abs(to_front.multVec(glass).z + C + P['lip']) < 1e-6, 'the reference panel is not where the pocket is'
clash = solid.common(panel).Volume
assert clash < 0.5, f'the panel collides with the shell ({clash:.1f} mm3)'
if CROW:   # a 35 mm USB-C plug (12.4 x 6.5) in either socket, and a finger's room in front of the power switch
    plugs = [model_block(-89.45 - 35, -89.45, -9.98, -3.48, z - 6.2, z + 6.2) for z in (10.47, -10.47)]
    plugs.append(model_block(-89.45 - 10, -87.1, -10.85, -5.4, -31.94, -22.94))
else:      # a 35 mm USB plug in either socket position
    plugs = [block(sx * (BOX_W / 2 - 13) - 6.5, sx * (BOX_W / 2 - 13) + 6.5, BOX_DEEP, BOX_DEEP + 35, z - 4, z + 4)
             for sx in (-1, 1) for z in (75.2, 62.5)]
for plug in plugs:
    hit = solid.common(plug).Volume
    assert hit < 0.5, f'a USB plug would hit the shell ({hit:.0f} mm3)'
if CROW:   # the board comes out straight down through the base without touching
    for depth in range(4, 151, 4):
        moved = panel.copy()
        moved.translate(Vector(0, 0, -depth))
        hit = solid.common(moved)
        assert hit.Volume < 0.5, f'the board cannot go in from below: it hits the shell {depth} mm down, at {hit.BoundBox}'
if CROW:   # each screw hole has solid front round it, from the board's face to 1 mm under the front surface
    def along(radius, start, length, sx, y):
        return solid.common(Part.makeCylinder(radius, length, frame.multVec(Vector(sx * post_x, y - panel_low, -start)),
                                              frame.Rotation.multVec(Vector(0, 0, -1)))).Volume
    for sx in (-1, 1):
        for y in (post_low, post_high):
            ring = along(2.7, 0.5, glass_to_board - 0.5, sx, y) - along(P['screw_hole'] / 2, 0.5, glass_to_board - 0.5, sx, y)
            assert ring > 0.9 * math.pi * (2.7 ** 2 - (P['screw_hole'] / 2) ** 2) * (glass_to_board - 0.5), f'the front round a screw hole is not solid ({ring:.0f} mm3)'
            assert along(1.0, 1.0 - C - P['lip'] + 0.1, glass_to_board + C + P['lip'] - 1.2, sx, y) < 0.5, 'a screw hole is not open'
reference = doc.addObject('Part::Feature', 'PanelReference')
reference.Shape = panel.removeSplitter()
reference.Label = 'Panel (reference, not printed)'
if CROW:   # the body, and the cable room cut after it
    console = doc.addObject('Part::Feature', 'Console')
    console.Shape = solid
    console.Label = 'Console (printed)'
    body.Visibility = False
doc.recompute()

OUT.mkdir(parents=True, exist_ok=True)
doc.saveAs(str(OUT / f'{NAME}.FCStd'))
solid.exportStep(str(OUT / f'{NAME}.step'))
printed = solid
if CROW:   # the STL lies the way it prints, on its front
    printed = solid.copy()
    printed.transformShape(Placement(Vector(), Rotation(outward, Vector(0, 0, -1))).toMatrix())
    printed.translate(Vector(0, 0, -printed.BoundBox.ZMin))
mesh = MeshPart.meshFromShape(Shape=printed, LinearDeflection=0.05, AngularDeflection=0.26, Relative=False)
mesh.write(str(OUT / f'{NAME}.stl'))
if os.environ.get('TESSERA_REVIEW'):
    MeshPart.meshFromShape(Shape=panel, LinearDeflection=0.1, AngularDeflection=0.3, Relative=False).write(os.environ['TESSERA_REVIEW'])
box = solid.BoundBox
print(f'RESULT {BOARD} size {box.XLength:.1f} x {box.YLength:.1f} x {box.ZLength:.1f} mm, volume {solid.Volume / 1000:.1f} cm3, '
      f'facets {mesh.CountFacets}, solid {mesh.isSolid()}, non-manifold {mesh.hasNonManifolds()}, clash {clash:.2f} mm3')
