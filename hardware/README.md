# Desk console for the panel

A printable desk console for the GUITION JC1060P470C in its factory housing (the `_Y` variant), drawn with
FreeCAD. The screen reclines 45° in a chamfered frame; below it is a chin with the Tessera tile mark, in front a
short upright apron. The raised box, the corner posts and the cables are hidden inside. The back has air openings
in the same tile pattern, an arch for the USB cable and two holes for the screwdriver; each end has a sunken field
that follows the outline, and a chamfer round the base lifts the console visually; underneath are four
recesses for 10 mm stick-on rubber feet. `tessera-enclosure.png` shows it with the panel in place.

| File | What it is |
|---|---|
| `tessera-enclosure.stl` | For the slicer |
| `tessera-enclosure.step` | For any CAD program |
| `tessera-enclosure.FCStd` | The FreeCAD model: a Part Design body with sketches, pads, pockets and fillets, a sheet of sizes, and the panel as a reference body |
| `make_enclosure.py` | Builds the model and exports the other two; every size is a parameter at the top |

## Sizes it is built from

From the manufacturer's structure drawing (`3-Structure_Diagram/JC1060P470C_I_W_Y-模型.pdf` in
[wegi1/ESP32P4-JC1060P470C-I_W_Y](https://github.com/wegi1/ESP32P4-JC1060P470C-I_W_Y)):

| | mm |
|---|---|
| Outline | 181.80 × 113.72 |
| Picture (active area) | 155.01 × 86.72 |
| Flat part (slab) thickness | 8.00 |
| Raised box on the back | 124.66 × 74.67, 8.38 deep |
| Depth over all | 20.38 |
| Corner posts | 4 × Ø2.00 holes on 166.00 × 99.00 |

The console: 191.0 × 124.4 × 103.8 mm, 144 cm³ of plastic (about 180 g of PLA if solid; less with infill).

## How the panel goes in and how it is fastened

1. Stand the console on the desk. Put the panel's bottom edge behind the low lip at the foot of the pocket and
   tilt the panel back until it rests on the rim. The USB cable can be plugged in first, through the open bottom.
2. The panel now stays by its own weight. To fasten it, hold it in and lay the enclosure face down on a cloth.
3. Behind each corner post of the panel there is a tab with a 2.6 mm hole. Put a screw through each tab into the
   brass insert of the post: the two bottom screws from the open underside, the two top screws through the two
   8 mm holes in the back. Tighten gently; the screws only pull the panel against the rim.

Screws: 4 pieces, 6 mm long, with a washer. **The thread is not stated in the manufacturer's files.** The hole in
the insert is drawn as 2.00 mm, which points to M2; try an M2 screw first and do not force an M2.5.

The pocket is 183.0 × 114.9 mm and 8.6 mm deep (0.6 mm clearance all round). The lip covers 3.5 mm at the bottom
of the glass; the picture starts 13.5 mm in. Without the screws the panel can be lifted out by its top edge.

## What else was looked up

The drawing does not give everything, so the rest comes from the same repository:

| | Value | From |
|---|---|---|
| USB-C sockets | Both face straight back through the cover, about 13 mm in from one side of the box | Specification, pages 5 and 6 |
| Ethernet jack | Stands 4 mm proud of the box (the drawing's 20.38 over all) | Drawing and side photo |
| Corner posts | About 4.6 mm across, 5 mm tall (they end 13 mm behind the glass); brass inserts | Side photo `PICTURES/11.jpg`, measured in the image |
| Box position | Centred within about 1.5 mm | Side photo |
| Panel corner radius | About 3 mm | Front photo, estimated |

The script draws the panel with these parts, plus a 35 mm long USB plug in each socket position, and stops if
anything touches the shell. Measured values from photos are good to about half a millimetre, not better.

## Still worth a look on your own panel

- The thread in the posts (the hole is 2.00 mm) is not stated anywhere. The enclosure does not use it.
- Posts thicker than about 7 mm would touch the rim; make `rim` smaller if yours are.

## Printing

Print it standing, as it stands on the desk, without supports: the front reclines 45° and the back leans 10°. 0.2 mm
layers and 3 walls; the shell is 2.8 mm thick, so infill hardly matters. Rubber feet under the two long edges keep
it from sliding when you press a key.

## Changing it

Open `tessera-enclosure.FCStd` in FreeCAD. The body **Enclosure** is built in this order:

| Feature | Sketch | What it does |
|---|---|---|
| Shell | Outline | The side outline (apron, reclining front, back), padded to the full width |
| RoundTop, SoftFront, RoundEnds | | Rounds the top (10 mm), the edge above the apron (4 mm) and the two ends (3 mm) |
| BaseChamfer | | A 1.2 mm chamfer round the base |
| Hollow | Inside | Hollows the shell; the front stays thick for the pocket, and there is no floor |
| HollowChin | ChinInside | Thins the chin and the apron to the wall thickness, to save plastic |
| PanelPocket | PanelOutline | The pocket the panel lies in, on the leaning **FrontPlane** |
| FrameChamfer | | A 0.8 mm chamfer round the mouth of the pocket |
| BackOpening | RimOpening | Opens the pocket to the inside, leaving the rim the panel rests on |
| Lip | LipOutline | The low lip that holds the bottom edge |
| TileMark | MarkTiles | The three-by-three tile mark, 0.6 mm deep, in the chin |
| ScrewTabs | TabOutlines | Four tabs behind the corner posts, on **TabPlane** |
| ScrewHoles | ScrewHoleCentres | A 2.6 mm hole in each tab |
| ScrewAccess | AccessHoleCentres | Two 8 mm holes through the back, in line with the top screws |
| FootPads, FootRecesses | FootPadOutlines, FootCentres | Four pads in the corners with a 10.4 mm recess for a rubber foot |
| TrimAtDesk | BelowDesk | Cuts off what reaches below the desk |
| CheekRight, CheekLeft | CheekFieldRight, CheekFieldLeft | A 0.6 mm sunken field on each end |
| CableOpening | CableArch | An arch, 30 mm wide, for the USB cable in the foot of the back |
| AirTiles | VentTiles | Three rows of eleven square openings in the back |

Every sketch is fully constrained with dimensions from the origin: double-click a sketch and change a number. The
sheet **Sizes** drives the lengths of the pads and pockets (outer and inner width, pocket depth, lip, cable notch).
Changing the tilt or the panel size moves several sketches at once, so for that edit the `P = dict(...)` block at
the top of `make_enclosure.py` and build the model again:

```powershell
& "C:\Program Files\FreeCAD 1.1\bin\freecadcmd.exe" hardware\make_enclosure.py
```

The script stops with a message if a feature fails, a sketch is not fully constrained, the body is not one valid
solid, or the panel or a USB plug would touch the shell.

## A simpler dock

`make_dock.py` draws a lighter alternative in Blender: the panel drops in from the top and leans back 30° against
two uprights, and the dock stays open behind it, so the raised box, the ports and the cables are free.
`tessera-dock.stl` is the result for the slicer and `tessera-dock.blend` the model. Every size is an option:

```powershell
blender -b --factory-startup --python-exit-code 1 -P hardware\make_dock.py -- --tilt 30 --slab 10
```

After `make_enclosure.py`, `save_view.py` stores a ready view in the FreeCAD file, so it opens looking at the
console:

```powershell
& "C:\Program Files\FreeCAD 1.1\bin\freecad.exe" hardware\save_view.py
```
