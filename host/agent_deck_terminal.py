#!/usr/bin/env python3
"""Standalone Agent Deck terminal and profile editor."""
import argparse
import os
import asyncio
import copy
import json
from pathlib import Path
import sys
from deck_control import ROOT, Controller, configure_upstream, save_profiles
from agent_deckd import Daemon, validate_config
from deck_forms import ActionForm
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Grid
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static, TabbedContent, TabPane


ACTION_FIELDS = {'hotkey': ('keys', 'ctrl+shift+b'), 'text': ('text', 'Tekst som skal skrives'),
    'open': ('target', 'Program, fil eller nettadresse'), 'shell': ('command', 'Kommando'),
    'http': ('url', 'https://...'), 'delay': ('ms', '250'), 'page': ('page', 'Sidenavn'),
    'profile': ('profile', 'Profilnavn'), 'press': ('id', 'Knappnummer'),
    'set': ('variable', 'Variabelnavn'), 'folder': ('page', 'Mappe'), 'back': (None, 'Tilbake')}


def profile_buttons(profile):
    """Return every editable button, including pinned and toggle states."""
    return [button for page in profile['pages'].values() for button in page] + list(profile.get('pinned', []))


def rewrite_actions(buttons, transform):
    """Rewrite all normal and toggle-state actions without skipping hidden variants."""
    for button in buttons:
        holders = [button, *button.get('states', [])]
        for holder in holders:
            holder['actions'] = [changed for action in holder.get('actions', [])
                                 if (changed := transform(action)) is not None]


def rewrite_trigger_actions(triggers, transform):
    for trigger in triggers:
        trigger['actions'] = [changed for action in trigger.get('actions', [])
                              if (changed := transform(action)) is not None]


class ActionEditor(ModalScreen):
    DEFAULT_CSS = '''
    ActionEditor {align: center middle; background: #000000 70%;}
    ActionEditor > Vertical {width: 80%; max-width: 100; height: auto; max-height: 90%;
        border: round #35d07f; background: #11191d; padding: 1 2;}
    ActionEditor Input, ActionEditor Select {margin-bottom: 1;}
    ActionEditor Static {height: auto;}
    ActionEditor Horizontal {height: 3;}
    '''
    BINDINGS = [('escape', 'cancel', 'Avbryt')]

    def __init__(self, action=None):
        super().__init__()
        self.draft = copy.deepcopy(action or {'type': 'hotkey', 'keys': ''})

    def compose(self):
        with Vertical():
            yield Static('HANDLING / TRINN I MULTIHANDLING')
            yield Select([(name, name) for name in ACTION_FIELDS], value=self.draft['type'],
                         allow_blank=False, id='action-type')
            yield Static('', id='parameter-caption')
            yield Input('', id='parameter')
            yield Static('Ekstra: HTTP-innhold eller variabelverdi')
            yield Input(str(self.draft.get('body', self.draft.get('task', self.draft.get('value', '')))), id='extra')
            yield Select([(method, method) for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')],
                         value=self.draft.get('method', 'GET'), id='http-method', allow_blank=False)
            yield Static('', id='action-error')
            with Horizontal():
                yield Button('Avbryt', id='cancel-action')
                yield Button('Lagre trinn', id='save-action', variant='success')

    def on_mount(self):
        self.update_field(self.draft['type'])

    def update_field(self, kind):
        field, example = ACTION_FIELDS[kind]
        self.query_one('#parameter-caption', Static).update((field.upper() + ' / ' + example) if field else example)
        self.query_one('#parameter', Input).value = str(self.draft.get(field, '')) if field else ''
        self.query_one('#parameter').display = field is not None
        self.query_one('#http-method').display = kind == 'http'
        self.query_one('#extra').display = kind in ('http', 'set')

    def on_select_changed(self, event):
        event.stop()
        if event.select.id == 'action-type' and self.is_mounted:
            self.update_field(str(event.value))

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        event.stop()
        if event.button.id == 'cancel-action':
            self.action_cancel()
            return
        kind = self.query_one('#action-type', Select).value
        value = self.query_one('#parameter', Input).value
        extra = self.query_one('#extra', Input).value
        try:
            if ACTION_FIELDS[kind][0] and not value and kind != 'text':
                raise ValueError('Fyll inn en verdi')
            if kind in ('delay', 'press'):
                value = int(value)
                if kind == 'delay' and not 0 <= value <= 60000:
                    raise ValueError('Forsinkelsen må være 0–60000 millisekunder')
                if kind == 'press' and not 1 <= value <= 18:
                    raise ValueError('Knappnummeret må være 1–18')
            if kind == 'hotkey':
                from agent_deckd import parse_hotkey
                parse_hotkey(value)
            action = copy.deepcopy(self.draft) if kind == self.draft['type'] else {}
            action = {'type': kind} if ACTION_FIELDS[kind][0] is None else dict(action, type=kind, **{ACTION_FIELDS[kind][0]: value})
            if kind == 'http':
                action.update(body=extra, method=self.query_one('#http-method', Select).value)
            elif kind == 'set':
                action['value'] = extra
            self.dismiss(action)
        except (ValueError, TypeError) as exc:
            self.query_one('#action-error', Static).update(str(exc))


class ButtonEditor(ModalScreen):
    DEFAULT_CSS = '''
    ButtonEditor {align: center middle; background: #000000 70%;}
    ButtonEditor > Vertical {width: 94%; max-width: 120; height: 94%; border: round #35d07f;
        background: #11191d; padding: 1 2;}
    ButtonEditor Input, ButtonEditor Select {margin-bottom: 1;}
    ButtonEditor Static {height: auto;}
    ButtonEditor Horizontal {height: 3; margin-top: 1;}
    ButtonEditor DataTable {height: 1fr; min-height: 5;}
    ButtonEditor Button {margin-right: 1; min-width: 10;}
    '''
    BINDINGS = [('escape', 'cancel', 'Avbryt')]

    def __init__(self, button):
        super().__init__()
        self.draft = copy.deepcopy(button)

    def compose(self):
        with Vertical():
            yield Static(f'KNAPP {self.draft["id"]} / NAVN / UTSEENDE / FLERHANDLING')
            yield Input(self.draft.get('label', ''), placeholder='Navn på knappen', id='button-label')
            yield Input(self.draft.get('color', '#35D07F'), placeholder='#35D07F', id='button-color')
            icons = 'ok close settings home download refresh play pause stop plus minus loop list folder upload bolt bell wifi trash edit'.split()
            choices = [(name, name) for name in icons]
            selected_icon = self.draft.get('icon', 'ok')
            if selected_icon not in icons:
                choices.append(('Valgt ikon fra grafisk editor', selected_icon))
            yield Select(choices, value=selected_icon,
                         allow_blank=False, id='button-icon')
            yield Static('HANDLINGER / kjøres ovenfra og ned')
            yield DataTable(id='action-steps', cursor_type='row')
            with Horizontal():
                yield Button('Legg til trinn', id='step-add')
                yield Button('Rediger trinn', id='step-edit')
                yield Button('Fjern', id='step-remove')
                yield Button('Flytt opp', id='step-up')
                yield Button('Flytt ned', id='step-down')
            yield Static('', id='button-error')
            with Horizontal():
                yield Button('Avbryt', id='button-cancel')
                yield Button('Tøm spor', id='button-clear', variant='error')
                yield Button('Lagre knapp', id='button-save', variant='success')

    def on_mount(self):
        self.query_one(DataTable).add_columns('#', 'Handling', 'Verdi')
        self.refresh_steps()

    def refresh_steps(self):
        table = self.query_one(DataTable)
        selected = table.cursor_row
        table.clear()
        for i, action in enumerate(self.draft.get('actions', [])):
            field = ACTION_FIELDS[action['type']][0]
            table.add_row(str(i + 1), action['type'], str(action.get(field, '')), key=str(i))
        if table.row_count:
            table.move_cursor(row=min(selected, table.row_count - 1))

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        event.stop()
        identifier = event.button.id
        actions = self.draft.setdefault('actions', [])
        index = self.query_one(DataTable).cursor_row
        if identifier == 'button-cancel':
            self.action_cancel()
        elif identifier == 'button-clear':
            self.dismiss({'id': self.draft['id'], 'delete': True})
        elif identifier == 'button-save':
            self.draft.update(label=self.query_one('#button-label', Input).value,
                color=self.query_one('#button-color', Input).value,
                icon=self.query_one('#button-icon', Select).value)
            if not self.draft['label'].strip():
                self.query_one('#button-error', Static).update('Skriv inn et navn på knappen')
                return
            self.dismiss(self.draft)
        elif identifier in ('step-add', 'step-edit'):
            if identifier == 'step-edit' and not actions:
                return
            editing = identifier == 'step-edit'
            def saved(action):
                if action is not None:
                    if editing:
                        actions[index] = action
                    else:
                        actions.append(action)
                    self.refresh_steps()
            self.app.push_screen(ActionEditor(actions[index] if editing else None), saved)
        elif actions and identifier == 'step-remove':
            del actions[index]
            self.refresh_steps()
        elif actions and identifier in ('step-up', 'step-down'):
            target = index + (-1 if identifier == 'step-up' else 1)
            if 0 <= target < len(actions):
                actions[index], actions[target] = actions[target], actions[index]
                self.refresh_steps()
                self.query_one(DataTable).move_cursor(row=target)


class DeckPane(TabPane):
    DEFAULT_CSS = '''
    #deck-picker {height: 3; margin-top: 1;}
    #deck-picker Select {width: 1fr; margin-right: 1;}
    #deck-toolbar {height: auto; layout: horizontal; margin: 1 0;}
    #deck-toolbar Button {min-width: 10; margin-right: 1;}
    #deck-run {height: 3; margin-bottom: 1;}
    #deck-run Button {margin-right: 1;}
    #deck-grid {grid-size: 6 3; grid-gutter: 1 2; height: 17;}
    #deck-grid Button {width: 1fr; height: 5; border: round #526572;}
    #deck-state {height: auto; margin-bottom: 1; color: #95ffc2;}
    #deck-connection {height: auto; color: #a3b2bc; margin-bottom: 1;}
    #deck-log {height: auto; min-height: 4; color: #a3b2bc;}
    '''

    def __init__(self, path=None):
        super().__init__('Deck', id='deck-editor')
        self.path = Path(path or ROOT / 'host/profiles.json')
        self.config = Daemon.load_profiles(self.path)
        self.profile = self.config.get('default_profile', next(iter(self.config['profiles'])))
        self.page = next(iter(self.config['profiles'][self.profile]['pages']))
        self.loaded = False

    def compose(self):
        with VerticalScroll():
            with Horizontal(id='deck-picker'):
                yield Select([(name, name) for name in self.config['profiles']], value=self.profile,
                             allow_blank=False, id='deck-profile')
                yield Select([(name, name) for name in self.config['profiles'][self.profile]['pages']],
                             value=self.page, allow_blank=False, id='deck-page')
            with Horizontal(id='deck-toolbar'):
                for caption, identifier in [('Ny profil', 'profile-add'), ('Profilregler', 'profile-edit'),
                    ('Ferdig oppsett', 'template-add'),
                    ('Ny side', 'page-add'), ('Gi siden nytt navn', 'page-edit'), ('Slett side', 'page-delete'), ('Eksporter', 'deck-export'),
                    ('Importer', 'deck-import')]:
                    yield Button(caption, id=identifier)
            with Horizontal(id='deck-run'):
                yield Button('Vis på enheten', id='deck-activate', variant='success')
                yield Button('Start vert', id='deck-host-start')
                yield Button('Stopp vert', id='deck-host-stop')
                yield Button('Dra og slipp ↗', id='deck-graphic-editor')
                yield Button('Slett profil', id='profile-delete')
            yield Static('Velg et spor for å redigere navn, ikon, farge og handlinger.', id='deck-state')
            yield Static('Kontrollerer USB-status …', id='deck-connection')
            with Grid(id='deck-grid'):
                for index in range(1, 19):
                    yield Button('', id=f'deck-slot-{index}')
            yield Static('DECK LOG', id='deck-log', classes='panel', markup=False)

    def on_mount(self):
        self.loaded = True
        self.refresh_grid()
        self.set_interval(2, self.refresh_log)

    def refresh_log(self):
        try:
            status = self.app.controller.status()
        except (AttributeError, OSError, ValueError):
            status = None
        if not isinstance(status, dict):
            status = {'connection': 'USB-status utilgjengelig', 'device': {}}
        device = status.get('device') if isinstance(status.get('device'), dict) else {}
        if device.get('connected'):
            message = f'● TILKOBLET  {device.get("port")}  ·  {device.get("profile", "")} / {device.get("page", "")}'
        else:
            message = f'○ {str(status.get("connection", "Venter på panelet")).upper()}'
        self.query_one('#deck-connection', Static).update(message)
        path = ROOT / 'host/deck.local.log'
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 8000))
                lines = stream.read().decode('utf-8', 'replace').splitlines()[-8:]
            self.query_one('#deck-log', Static).update('AGENT DECK / USB-VERT\n' + '\n'.join(lines))

    def refresh_grid(self):
        profile = self.config['profiles'][self.profile]
        buttons = {b['id']: b for b in profile['pages'][self.page]}
        pinned = {b['id']: b for b in profile.get('pinned', [])}
        buttons.update(pinned)
        for i in range(1, 19):
            item = self.query_one(f'#deck-slot-{i}', Button)
            button = buttons.get(i)
            marker = ' ◆' if i in pinned else ''
            item.label = f'{i:02d}{marker}  {button["label"]}\n{len(button.get("actions", []))} handlinger' if button else f'{i:02d}\n+ Legg til'
            item.styles.border = ('round', button.get('color', '#35D07F') if button else '#263239')
        self.refresh_log()

    def commit(self, draft):
        try:
            save_profiles(draft, self.path)
            self.config = copy.deepcopy(draft)
            self.refresh_grid()
            self.query_one('#deck-state', Static).update('Lagret. Aktiv side oppdateres automatisk.')
        except (ValueError, OSError) as exc:
            self.query_one('#deck-state', Static).update('Ikke lagret: ' + str(exc))

    def on_select_changed(self, event):
        event.stop()
        if not self.loaded or event.value is Select.NULL:
            return
        if event.select.id == 'deck-profile':
            self.profile = str(event.value)
            self.page = next(iter(self.config['profiles'][self.profile]['pages']))
            pages = self.query_one('#deck-page', Select)
            pages.set_options([(name, name) for name in self.config['profiles'][self.profile]['pages']])
            pages.value = self.page
        elif event.select.id == 'deck-page':
            self.page = str(event.value)
        self.refresh_grid()

    def on_button_pressed(self, event):
        event.stop()
        identifier = event.button.id
        if identifier in ('deck-host-start', 'deck-host-stop'):
            self.app.dispatch('start' if identifier == 'deck-host-start' else 'stop', {})
        elif identifier == 'deck-graphic-editor':
            self.app.action_graphic_editor()
        elif identifier == 'deck-activate':
            path = ROOT / 'host/deck-command.local.json'
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'profile': self.profile, 'page': self.page}))
            temporary.replace(path)
            self.query_one('#deck-state', Static).update('Sendt til enheten: ' + self.profile + ' / ' + self.page)
        elif identifier.startswith('deck-slot-'):
            slot = int(identifier.rsplit('-', 1)[-1])
            profile_data = self.config['profiles'][self.profile]
            pinned = profile_data.get('pinned', [])
            current = pinned if any(b['id'] == slot for b in pinned) else profile_data['pages'][self.page]
            button = next((b for b in current if b['id'] == slot), {'id': slot, 'label': '', 'actions': []})
            profile, page, is_pinned = self.profile, self.page, current is pinned
            def saved(result):
                if result is None:
                    return
                draft = copy.deepcopy(self.config)
                target = draft['profiles'][profile].setdefault('pinned', []) if is_pinned else draft['profiles'][profile]['pages'][page]
                target[:] = [b for b in target if b['id'] != slot]
                if not result.get('delete'):
                    target.append(result)
                    target.sort(key=lambda b: b['id'])
                self.commit(draft)
            self.app.push_screen(ButtonEditor(button), saved)
        elif identifier in ('profile-add', 'page-add'):
            kind = 'profile' if identifier == 'profile-add' else 'page'
            def saved(values):
                if values is None:
                    return
                name = values['name'].strip()
                if not name:
                    return
                draft = copy.deepcopy(self.config)
                if kind == 'profile':
                    if name in draft['profiles']:
                        self.query_one('#deck-state', Static).update('Profilen finnes allerede')
                        return
                    draft['profiles'][name] = {'match': [], 'pages': {'hoved': []}}
                else:
                    if name in draft['profiles'][self.profile]['pages']:
                        self.query_one('#deck-state', Static).update('Siden finnes allerede')
                        return
                    draft['profiles'][self.profile]['pages'][name] = []
                self.commit(draft)
                self.query_one('#deck-profile', Select).set_options([(n, n) for n in self.config['profiles']])
                self.query_one('#deck-profile', Select).value = name if kind == 'profile' else self.profile
                if kind == 'page':
                    self.query_one('#deck-page', Select).set_options([(n, n) for n in self.config['profiles'][self.profile]['pages']])
                    self.query_one('#deck-page', Select).value = name
            self.app.push_screen(ActionForm('NY PROFIL' if kind == 'profile' else 'NY SIDE', [('name', 'Navn', 'text', '', None)]), saved)
        elif identifier == 'template-add':
            try:
                catalog = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
                templates = {item['name']: item for item in catalog['templates']}
            except (OSError, ValueError, KeyError, TypeError):
                self.query_one('#deck-state', Static).update('Kunne ikke lese de ferdige oppsettene')
                return
            def saved(values):
                if values is None or values['template'] not in templates:
                    return
                template = templates[values['template']]
                draft = copy.deepcopy(self.config)
                name, suffix = template['name'], 2
                while name in draft['profiles']:
                    name = f'{template["name"]} {suffix}'
                    suffix += 1
                draft['profiles'][name] = copy.deepcopy(template['profile'])
                self.profile = name
                self.page = next(iter(draft['profiles'][name]['pages']))
                self.commit(draft)
                self.query_one('#deck-profile', Select).set_options([(n, n) for n in self.config['profiles']])
                self.query_one('#deck-profile', Select).value = name
            choices = [(name + ' · ' + item['description'], name) for name, item in templates.items()]
            self.app.push_screen(ActionForm('FERDIG PROFILOPPSETT', [
                ('template', 'Oppsett', 'select', next(iter(templates)), choices)],
                note='Legges til som en ny profil. Eksisterende profiler beholdes.'), saved)
        elif identifier == 'profile-edit':
            profile = self.config['profiles'][self.profile]
            def saved(values):
                if values is None:
                    return
                draft = copy.deepcopy(self.config)
                draft['profiles'][self.profile]['match'] = [s.strip() for s in values['match'].split(',') if s.strip()]
                if values['default']:
                    draft['default_profile'] = self.profile
                self.commit(draft)
            self.app.push_screen(ActionForm('SMARTPROFIL / AKTIVT PROGRAM', [
                ('match', 'Programnavn, adskilt med komma', 'text', ', '.join(profile.get('match', [])), None),
                ('default', 'Bruk som standardprofil', 'bool', self.config.get('default_profile') == self.profile, None)]), saved)
        elif identifier == 'page-edit':
            original = self.page
            def saved(values):
                if values is None or not values['name'].strip():
                    return
                name = values['name'].strip()
                draft = copy.deepcopy(self.config)
                pages = draft['profiles'][self.profile]['pages']
                if name in pages and name != original:
                    self.query_one('#deck-state', Static).update('Siden finnes allerede')
                    return
                pages[name] = pages.pop(original)
                def update_page(action):
                    if action.get('type') in ('page', 'folder') and action.get('page') == original:
                        action['page'] = name
                    return action
                rewrite_actions(profile_buttons(draft['profiles'][self.profile]), update_page)
                if draft.get('default_profile') == self.profile:
                    rewrite_trigger_actions(draft.get('triggers', []), update_page)
                self.page = name
                self.commit(draft)
                self.query_one('#deck-page', Select).set_options([(n, n) for n in pages])
                self.query_one('#deck-page', Select).value = name
            self.app.push_screen(ActionForm('GI SIDEN NYTT NAVN', [('name', 'Sidenavn', 'text', original, None)]), saved)
        elif identifier == 'profile-delete':
            if len(self.config['profiles']) <= 1:
                self.query_one('#deck-state', Static).update('Behold minst én profil')
                return
            draft = copy.deepcopy(self.config)
            del draft['profiles'][self.profile]
            if draft.get('default_profile') == self.profile:
                draft['default_profile'] = next(iter(draft['profiles']))
            try:
                validate_config(draft)
            except ValueError:
                self.query_one('#deck-state', Static).update('Fjern handlinger som peker til profilen før den slettes')
                return
            self.profile = draft.get('default_profile', next(iter(draft['profiles'])))
            self.page = next(iter(draft['profiles'][self.profile]['pages']))
            self.commit(draft)
            self.query_one('#deck-profile', Select).set_options([(n, n) for n in draft['profiles']])
            self.query_one('#deck-profile', Select).value = self.profile
        elif identifier == 'page-delete':
            if len(self.config['profiles'][self.profile]['pages']) <= 1:
                self.query_one('#deck-state', Static).update('Behold minst én side i hver profil')
                return
            draft = copy.deepcopy(self.config)
            del draft['profiles'][self.profile]['pages'][self.page]
            previous = self.page
            self.page = next(iter(draft['profiles'][self.profile]['pages']))
            self.commit(draft)
            if previous in self.config['profiles'][self.profile]['pages']:
                self.page = previous
            self.query_one('#deck-page', Select).set_options([(n, n) for n in self.config['profiles'][self.profile]['pages']])
            self.query_one('#deck-page', Select).value = self.page
        elif identifier in ('deck-import', 'deck-export'):
            importing = identifier == 'deck-import'
            def saved(values):
                if values is None:
                    return
                try:
                    path = Path(values['path']).expanduser()
                    if importing:
                        draft = Daemon.load_profiles(path)
                        self.profile = draft.get('default_profile', next(iter(draft['profiles'])))
                        self.page = next(iter(draft['profiles'][self.profile]['pages']))
                        self.commit(draft)
                        self.query_one('#deck-profile', Select).set_options([(n, n) for n in self.config['profiles']])
                        self.query_one('#deck-profile', Select).value = self.profile
                        self.query_one('#deck-page', Select).set_options([(n, n) for n in self.config['profiles'][self.profile]['pages']])
                        self.query_one('#deck-page', Select).value = self.page
                    else:
                        if path.exists():
                            raise ValueError('Velg et nytt filnavn; eksisterende eksportfiler overskrives ikke')
                        save_profiles(self.config, path)
                    self.query_one('#deck-state', Static).update('Importert' if importing else 'Eksportert')
                except (ValueError, OSError) as exc:
                    self.query_one('#deck-state', Static).update(str(exc))
            self.app.push_screen(ActionForm('IMPORTER' if importing else 'EKSPORTER', [
                ('path', 'Sti til profilfil', 'text', '', None)],
                note='Importerte handlinger blir aktive når du trykker på knappene. Kontroller kilden først.'), saved)


class AgentDeckApp(App):
    TITLE = 'Agent Deck'
    CSS = '''
    Screen {background: #0b1114; color: #e9f4ef;}
    #brand {height: 3; padding: 1 2; background: #14211c; color: #92edba;
      text-style: bold;}
    #pages {height: 1fr;}
    TabbedContent ContentSwitcher {background: #0b1114;}
    '''
    BINDINGS = [('q','quit','Avslutt'), Binding('f8','graphic_editor','Dra og slipp')]

    def action_graphic_editor(self):
        import subprocess
        subprocess.Popen([str(ROOT / 'host/.venv/Scripts/pythonw.exe'),
                          str(ROOT / 'host/agent_deck_app.py'), '--editor'],
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def __init__(self, controller=None, profile_path=None, reader=None):
        self.controller = controller or Controller()
        self.profile_path = profile_path
        super().__init__()

    def compose(self):
        yield Header()
        yield Static('AGENT DECK  /  18 KNAPPER  /  ÉN USB-TILKOBLING', id='brand')
        with TabbedContent(id='pages'):
            yield DeckPane(self.profile_path)
        yield Footer()

    def dispatch(self, action, values=None):
        async def run():
            output=[]
            try:
                await asyncio.to_thread(getattr(self.controller, action), emit=output.append)
                self.notify(output[-1] if output else 'Ferdig')
            except Exception as exc:
                self.notify(str(exc), severity='error')
        self.run_worker(run(), exclusive=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Syntetisk terminaltest uten USB eller handlinger')
    args = parser.parse_args()
    if args.check:
        from terminal_check import check
        asyncio.run(check())
        return 0
    configure_upstream()
    controller = Controller()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('Open Agent-Deck.cmd in a terminal, or use --check for tests.')
        return 2
    AgentDeckApp(controller).run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
