"""Small, keyboard-friendly forms used by the standalone Deck terminal."""
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static


class ActionForm(ModalScreen):
    DEFAULT_CSS = '''
    ActionForm {align: center middle; background: #000 65%;}
    ActionForm > Vertical {width: 90%; max-width: 100; height: auto; max-height: 90%;
      border: round #35d07f; background: #10181c; padding: 1 2;}
    ActionForm VerticalScroll {height: 1fr; min-height: 8;}
    ActionForm Static {height: auto; margin-bottom: 1;}
    ActionForm Input, ActionForm Select {margin-bottom: 1;}
    ActionForm Horizontal {height: 3; align: right middle;}
    ActionForm Button {margin-left: 1;}
    '''
    BINDINGS = [('escape', 'cancel', 'Avbryt')]

    def __init__(self, title, fields=(), note='', **_):
        super().__init__(); self.caption=title; self.fields=list(fields); self.note=note

    def compose(self):
        with Vertical():
            yield Static(self.caption, markup=False)
            with VerticalScroll():
                yield Static(self.note, markup=False)
                for key,label,kind,value,choices in self.fields:
                    yield Static(label, markup=False)
                    if kind == 'bool':
                        yield Select([('Ja', True), ('Nei', False)], value=bool(value),
                                     allow_blank=False, id='field-'+key)
                    elif kind == 'select':
                        yield Select(choices, value=value if value not in (None,'') else Select.NULL, id='field-'+key)
                    else:
                        yield Input(str(value or ''), password=kind=='secret', id='field-'+key)
            yield Static('', id='form-error', markup=False)
            with Horizontal():
                yield Button('Avbryt', id='cancel')
                yield Button('Lagre', id='submit', variant='success')

    def action_cancel(self): self.dismiss(None)
    def on_button_pressed(self,event):
        event.stop()
        if event.button.id=='cancel': return self.action_cancel()
        values={}
        for key,_,kind,_,_ in self.fields:
            value=self.query_one('#field-'+key).value
            values[key]=None if value is Select.NULL else bool(value) if kind == 'bool' else value
        self.dismiss(values)
