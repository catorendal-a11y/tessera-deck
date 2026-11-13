"""Second step after make_enclosure.py: store what is shown, so the model opens ready to look at.

    "C:\\Program Files\\FreeCAD 1.1\\bin\\freecad.exe" hardware\\save_view.py

make_enclosure.py runs without a window, and a file saved that way has no view settings: FreeCAD then opens it
with every object hidden. This opens the file in the real window, shows the enclosure body (its last feature) and
the panel as a see-through reference, saves the file again and writes a picture next to it.
"""
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui

FOLDER = Path(__file__).resolve().parent
doc = App.openDocument(str(FOLDER / 'tessera-enclosure.FCStd'))
gui = Gui.getDocument(doc.Name)
body = doc.getObject('Enclosure')
for ob in doc.Objects:
    view = gui.getObject(ob.Name)
    if view is not None and hasattr(view, 'Visibility'):
        view.Visibility = ob in (body, body.Tip, doc.getObject('PanelReference'))
gui.getObject(body.Name).ShapeColor = (0.16, 0.19, 0.21)
panel = gui.getObject('PanelReference')
panel.ShapeColor = (0.30, 0.82, 0.88)
panel.Transparency = 70
doc.recompute()
view = gui.activeView()
view.viewIsometric()
view.fitAll()
doc.save()
view.saveImage(str(FOLDER / 'tessera-enclosure.png'), 1400, 900, 'White')
shown = [ob.Name for ob in doc.Objects if getattr(gui.getObject(ob.Name), 'Visibility', False)]
(FOLDER / 'save_view.log').write_text('shown: ' + ', '.join(shown) + '\n', encoding='utf-8')
Gui.getMainWindow().close()
