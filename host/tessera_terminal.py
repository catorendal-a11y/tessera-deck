#!/usr/bin/env python3
"""Standalone Tessera terminal and profile editor."""
import argparse
import os
import asyncio
import copy
import json
from pathlib import Path
import sys
from deck_control import ROOT, Controller, configure_upstream, save_profiles
from tesserad import Daemon, validate_config
from deck_forms import ActionForm
from textual.app import App
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Grid
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static, TabbedContent, TabPane


ACTION_FIELDS = {'hotkey': ('keys', 'ctrl+shift+b'), 'text': ('text', 'Text to type'),
    'open': ('target', 'Program, file or web address'), 'shell': ('command', 'Command'),
    'http': ('url', 'https://...'), 'delay': ('ms', '250'), 'page': ('page', 'Page name'),
    'profile': ('profile', 'Profile name'), 'press': ('id', 'Button number'),
    'set': ('variable', 'Variable name'), 'folder': ('page', 'Folder'), 'back': (None, 'Back'),
    'state': ('button', 'Button number')}


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
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, action=None):
        super().__init__()
        self.draft = copy.deepcopy(action or {'type': 'hotkey', 'keys': ''})

    def compose(self):
        with Vertical():
            yield Static('ACTION / STEP IN A MULTI-ACTION')
            yield Select([(name, name) for name in ACTION_FIELDS], value=self.draft['type'],
                         allow_blank=False, id='action-type')
            yield Static('', id='parameter-caption')
            yield Input('', id='parameter')
            yield Static('Extra: HTTP body, variable value, or state (next or 1-8)')
            yield Input(str(self.draft.get('body', self.draft.get('task', self.draft.get('value', '')))), id='extra')
            yield Select([(method, method) for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')],
                         value=self.draft.get('method', 'GET'), id='http-method', allow_blank=False)
            yield Static('', id='action-error')
            with Horizontal():
                yield Button('Cancel', id='cancel-action')
                yield Button('Save step', id='save-action', variant='success')

    def on_mount(self):
        self.update_field(self.draft['type'])

    def update_field(self, kind):
        field, example = ACTION_FIELDS[kind]
        self.query_one('#parameter-caption', Static).update((field.upper() + ' / ' + example) if field else example)
        self.query_one('#parameter', Input).value = str(self.draft.get(field, '')) if field else ''
        self.query_one('#parameter').display = field is not None
        self.query_one('#http-method').display = kind == 'http'
        self.query_one('#extra').display = kind in ('http', 'set', 'state')
        if kind == 'state':
            current = self.draft.get('state', 'next') if self.draft['type'] == 'state' else 'next'
            self.query_one('#extra', Input).value = 'next' if current == 'next' else str(current + 1)

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
                raise ValueError('Enter a value')
            if kind in ('delay', 'press', 'state'):
                value = int(value)
                if kind == 'delay' and not 0 <= value <= 60000:
                    raise ValueError('The delay must be 0-60000 milliseconds')
                if kind in ('press', 'state') and not 1 <= value <= 18:
                    raise ValueError('The button number must be 1-18')
            if kind == 'hotkey':
                from tesserad import parse_hotkey
                parse_hotkey(value)
            action = copy.deepcopy(self.draft) if kind == self.draft['type'] else {}
            action = {'type': kind} if ACTION_FIELDS[kind][0] is None else dict(action, type=kind, **{ACTION_FIELDS[kind][0]: value})
            if kind == 'http':
                action.update(body=extra, method=self.query_one('#http-method', Select).value)
            elif kind == 'set':
                action['value'] = extra
            elif kind == 'state':
                number = extra.strip().lower() or 'next'
                if number != 'next' and not (number.isdigit() and 1 <= int(number) <= 8):
                    raise ValueError("The state must be 'next' or a number from 1 to 8")
                action['state'] = 'next' if number == 'next' else int(number) - 1
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
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, button):
        super().__init__()
        self.draft = copy.deepcopy(button)

    def compose(self):
        with Vertical():
            yield Static(f'KNAPP {self.draft["id"]} / NAVN / UTSEENDE / FLERHANDLING')
            yield Input(self.draft.get('label', ''), placeholder='Button name', id='button-label')
            yield Input(self.draft.get('color', '#35D07F'), placeholder='#35D07F', id='button-color')
            icons = 'ok close settings home download refresh play pause stop plus minus loop list folder upload bolt bell wifi trash edit'.split()
            choices = [(name, name) for name in icons]
            selected_icon = self.draft.get('icon', 'ok')
            if selected_icon not in icons:
                choices.append(('Icon chosen in the graphical editor', selected_icon))
            yield Select(choices, value=selected_icon,
                         allow_blank=False, id='button-icon')
            yield Static('ACTIONS / run from top to bottom')
            yield DataTable(id='action-steps', cursor_type='row')
            with Horizontal():
                yield Button('Add step', id='step-add')
                yield Button('Edit step', id='step-edit')
                yield Button('Remove', id='step-remove')
                yield Button('Move up', id='step-up')
                yield Button('Move down', id='step-down')
            yield Static('', id='button-error')
            with Horizontal():
                yield Button('Cancel', id='button-cancel')
                yield Button('Clear slot', id='button-clear', variant='error')
                yield Button('Save button', id='button-save', variant='success')

    def on_mount(self):
        self.query_one(DataTable).add_columns('#', 'Action', 'Value')
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
                self.query_one('#button-error', Static).update('Enter a name for the button')
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
                for caption, identifier in [('New profile', 'profile-add'), ('Profile rules', 'profile-edit'),
                    ('Templates', 'template-add'),
                    ('New page', 'page-add'), ('Rename page', 'page-edit'), ('Delete page', 'page-delete'), ('Export', 'deck-export'),
                    ('Import', 'deck-import')]:
                    yield Button(caption, id=identifier)
            with Horizontal(id='deck-run'):
                yield Button('Show on device', id='deck-activate', variant='success')
                yield Button('Start host', id='deck-host-start')
                yield Button('Stop host', id='deck-host-stop')
                yield Button('Drag and drop ↗', id='deck-graphic-editor')
                yield Button('Delete profile', id='profile-delete')
            yield Static('Choose a slot to edit its name, icon, color and actions.', id='deck-state')
            yield Static('Checking USB status …', id='deck-connection')
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
            status = {'connection': 'USB status unavailable', 'device': {}}
        device = status.get('device') if isinstance(status.get('device'), dict) else {}
        if device.get('connected'):
            message = f'● CONNECTED  {device.get("port")}  ·  {device.get("profile", "")} / {device.get("page", "")}'
        else:
            message = f'○ {str(status.get("connection", "Waiting for the panel")).upper()}'
        self.query_one('#deck-connection', Static).update(message)
        path = ROOT / 'host/deck.local.log'
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 8000))
                lines = stream.read().decode('utf-8', 'replace').splitlines()[-8:]
            self.query_one('#deck-log', Static).update('TESSERA / USB HOST\n' + '\n'.join(lines))

    def refresh_grid(self):
        profile = self.config['profiles'][self.profile]
        buttons = {b['id']: b for b in profile['pages'][self.page]}
        pinned = {b['id']: b for b in profile.get('pinned', [])}
        buttons.update(pinned)
        for i in range(1, 19):
            item = self.query_one(f'#deck-slot-{i}', Button)
            button = buttons.get(i)
            marker = ' ◆' if i in pinned else ''
            item.label = f'{i:02d}{marker}  {button["label"]}\n{len(button.get("actions", []))} actions' if button else f'{i:02d}\n+ Add'
            item.styles.border = ('round', button.get('color', '#35D07F') if button else '#263239')
        self.refresh_log()

    def commit(self, draft):
        try:
            save_profiles(draft, self.path)
            self.config = copy.deepcopy(draft)
            self.refresh_grid()
            self.query_one('#deck-state', Static).update('Saved. The active page updates automatically.')
        except (ValueError, OSError) as exc:
            self.query_one('#deck-state', Static).update('Not saved: ' + str(exc))

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
            self.query_one('#deck-state', Static).update('Sent to the device: ' + self.profile + ' / ' + self.page)
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
                        self.query_one('#deck-state', Static).update('The profile already exists')
                        return
                    draft['profiles'][name] = {'match': [], 'pages': {'main': []}}
                else:
                    if name in draft['profiles'][self.profile]['pages']:
                        self.query_one('#deck-state', Static).update('The page already exists')
                        return
                    draft['profiles'][self.profile]['pages'][name] = []
                self.commit(draft)
                self.query_one('#deck-profile', Select).set_options([(n, n) for n in self.config['profiles']])
                self.query_one('#deck-profile', Select).value = name if kind == 'profile' else self.profile
                if kind == 'page':
                    self.query_one('#deck-page', Select).set_options([(n, n) for n in self.config['profiles'][self.profile]['pages']])
                    self.query_one('#deck-page', Select).value = name
            self.app.push_screen(ActionForm('NEW PROFILE' if kind == 'profile' else 'NEW PAGE', [('name', 'Name', 'text', '', None)]), saved)
        elif identifier == 'template-add':
            try:
                catalog = json.loads((ROOT / 'host/action_packs.json').read_text(encoding='utf-8'))
                templates = {item['name']: item for item in catalog['templates']}
            except (OSError, ValueError, KeyError, TypeError):
                self.query_one('#deck-state', Static).update('Could not read the templates')
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
            self.app.push_screen(ActionForm('PROFILE TEMPLATES', [
                ('template', 'Template', 'select', next(iter(templates)), choices)],
                note='Added as a new profile. Existing profiles are kept.'), saved)
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
            self.app.push_screen(ActionForm('SMART PROFILE / ACTIVE PROGRAM', [
                ('match', 'Program names, separated by commas', 'text', ', '.join(profile.get('match', [])), None),
                ('default', 'Use as the default profile', 'bool', self.config.get('default_profile') == self.profile, None)]), saved)
        elif identifier == 'page-edit':
            original = self.page
            def saved(values):
                if values is None or not values['name'].strip():
                    return
                name = values['name'].strip()
                draft = copy.deepcopy(self.config)
                pages = draft['profiles'][self.profile]['pages']
                if name in pages and name != original:
                    self.query_one('#deck-state', Static).update('The page already exists')
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
            self.app.push_screen(ActionForm('RENAME PAGE', [('name', 'Page name', 'text', original, None)]), saved)
        elif identifier == 'profile-delete':
            if len(self.config['profiles']) <= 1:
                self.query_one('#deck-state', Static).update('Keep at least one profile')
                return
            draft = copy.deepcopy(self.config)
            del draft['profiles'][self.profile]
            if draft.get('default_profile') == self.profile:
                draft['default_profile'] = next(iter(draft['profiles']))
            try:
                validate_config(draft)
            except ValueError:
                self.query_one('#deck-state', Static).update('Remove actions that point to the profile before deleting it')
                return
            self.profile = draft.get('default_profile', next(iter(draft['profiles'])))
            self.page = next(iter(draft['profiles'][self.profile]['pages']))
            self.commit(draft)
            self.query_one('#deck-profile', Select).set_options([(n, n) for n in draft['profiles']])
            self.query_one('#deck-profile', Select).value = self.profile
        elif identifier == 'page-delete':
            if len(self.config['profiles'][self.profile]['pages']) <= 1:
                self.query_one('#deck-state', Static).update('Keep at least one page in every profile')
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
                            raise ValueError('Choose a new file name; existing export files are not overwritten')
                        save_profiles(self.config, path)
                    self.query_one('#deck-state', Static).update('Imported' if importing else 'Exported')
                except (ValueError, OSError) as exc:
                    self.query_one('#deck-state', Static).update(str(exc))
            self.app.push_screen(ActionForm('IMPORT' if importing else 'EXPORT', [
                ('path', 'Path to profile file', 'text', '', None)],
                note='Imported actions become active when you press the buttons. Check the source first.'), saved)


class TesseraApp(App):
    TITLE = 'Tessera'
    CSS = '''
    Screen {background: #0b1114; color: #e9f4ef;}
    #brand {height: 3; padding: 1 2; background: #14211c; color: #92edba;
      text-style: bold;}
    #pages {height: 1fr;}
    TabbedContent ContentSwitcher {background: #0b1114;}
    '''
    BINDINGS = [('q','quit','Quit'), Binding('f8','graphic_editor','Drag and drop')]

    def action_graphic_editor(self):
        import subprocess
        subprocess.Popen([str(ROOT / 'host/.venv/Scripts/pythonw.exe'),
                          str(ROOT / 'host/tessera_app.py'), '--editor'],
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def __init__(self, controller=None, profile_path=None, reader=None):
        self.controller = controller or Controller()
        self.profile_path = profile_path
        super().__init__()

    def compose(self):
        yield Header()
        yield Static('TESSERA  /  18 BUTTONS  /  ONE USB CONNECTION', id='brand')
        with TabbedContent(id='pages'):
            yield DeckPane(self.profile_path)
        yield Footer()

    def dispatch(self, action, values=None):
        async def run():
            output=[]
            try:
                await asyncio.to_thread(getattr(self.controller, action), emit=output.append)
                self.notify(output[-1] if output else 'Done')
            except Exception as exc:
                self.notify(str(exc), severity='error')
        self.run_worker(run(), exclusive=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Synthetic terminal test without USB or actions')
    args = parser.parse_args()
    if args.check:
        from terminal_check import check
        asyncio.run(check())
        return 0
    configure_upstream()
    controller = Controller()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('Open Tessera.cmd in a terminal, or use --check for tests.')
        return 2
    TesseraApp(controller).run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
