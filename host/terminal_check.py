"""Headless end-to-end terminal editor regression with isolated profile files."""
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock
from textual.widgets import Input, Select, TabbedContent
from tessera_terminal import TesseraApp, ButtonEditor, ActionEditor
from deck_control import ROOT


async def check():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'profiles.json'
        config = json.loads((ROOT / 'host/profiles.default.json').read_text(encoding='utf-8'))
        config['profiles']['main']['pages']['main'][0]['icon'] = 'lc:e064'
        config['profiles']['main']['pinned'] = [
            {'id': 17, 'label': 'Pinned button', 'icon': 'home', 'color': '#35D07F', 'actions': []}]
        path.write_text(json.dumps(config), encoding='utf-8')
        app = TesseraApp(controller=Mock(), profile_path=path)
        async with app.run_test(size=(140, 48)) as pilot:
            await pilot.pause(.3)
            assert app.query_one('#pages', TabbedContent).active == 'deck-editor'
            assert '◆' in str(app.query_one('#deck-slot-17').label)
            await pilot.click('#deck-slot-17')
            await pilot.pause(.1)
            app.screen.query_one('#button-label', Input).value = 'Pinned changed'
            await pilot.click('#button-save')
            await pilot.pause(.1)
            pinned = json.loads(path.read_text(encoding='utf-8'))['profiles']['main']['pinned']
            assert pinned[0]['label'] == 'Pinned changed'
            await pilot.click('#deck-slot-1')
            await pilot.pause(.1)
            assert isinstance(app.screen, ButtonEditor)
            app.screen.query_one('#button-label', Input).value = 'Test button'
            await pilot.click('#step-add')
            await pilot.pause(.1)
            assert isinstance(app.screen, ActionEditor)
            app.screen.query_one('#parameter', Input).value = 'ctrl+shift+b'
            await pilot.click('#save-action')
            await pilot.pause(.1)
            assert isinstance(app.screen, ButtonEditor)
            await pilot.click('#button-save')
            await pilot.pause(.2)
            saved = json.loads(path.read_text(encoding='utf-8'))
            button = saved['profiles']['main']['pages']['main'][0]
            assert button['label'] == 'Test button'
            assert button['icon'] == 'lc:e064'
            assert button['actions'][-1] == {'type': 'hotkey', 'keys': 'ctrl+shift+b'}
            # Cancel leaves the committed file byte-for-byte intact.
            accepted = path.read_bytes()
            await pilot.click('#deck-slot-1')
            app.screen.query_one('#button-label', Input).value = 'Not saved'
            await pilot.press('escape')
            await pilot.pause(.1)
            assert path.read_bytes() == accepted
            await pilot.click('#deck-slot-18')
            await pilot.pause(.1)
            app.screen.query_one('#button-label', Input).value = 'Last slot'
            await pilot.click('#button-save')
            await pilot.pause(.1)
            assert json.loads(path.read_text(encoding='utf-8'))['profiles']['main']['pages']['main'][-1]['id'] == 18
            await pilot.click('#page-add')
            await pilot.pause(.1)
            app.screen.query_one('#field-name', Input).value = 'Test page'
            await pilot.click('#submit')
            await pilot.pause(.2)
            assert app.query_one('#deck-page', Select).value == 'Test page'
            assert json.loads(path.read_text(encoding='utf-8'))['profiles']['main']['pages']['Test page'] == []
            await pilot.click('#page-edit')
            await pilot.pause(.1)
            app.screen.query_one('#field-name', Input).value = 'Renamed'
            await pilot.click('#submit')
            await pilot.pause(.2)
            assert app.query_one('#deck-page', Select).value == 'Renamed'
            await pilot.click('#page-delete')
            await pilot.pause(.2)
            assert 'Renamed' not in json.loads(path.read_text(encoding='utf-8'))['profiles']['main']['pages']
            await pilot.click('#template-add')
            await pilot.pause(.1)
            app.screen.query_one('#field-template', Select).value = 'Windows control'
            await pilot.click('#submit')
            await pilot.pause(.2)
            templated = json.loads(path.read_text(encoding='utf-8'))
            self_name = next(name for name in templated['profiles'] if name.startswith('Windows control'))
            assert len(templated['profiles'][self_name]['pages']['main']) == 16
            app.query_one('#deck-profile', Select).value = 'coding'
            await pilot.pause(.1)
            await pilot.click('#profile-edit')
            await pilot.pause(.1)
            assert app.screen.query_one('#field-default', Select).value is False
            await pilot.click('#submit')
            await pilot.pause(.1)
            assert json.loads(path.read_text(encoding='utf-8'))['default_profile'] == 'main'
            output = ROOT / 'build/previews'
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot('terminal-deck.svg', path=str(output))
            await pilot.press('q')
        # Exercise the responsive pane in a smaller terminal too.
        app = TesseraApp(controller=Mock(), profile_path=path)
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause(.2)
            assert app.query_one('#deck-slot-18')
            await pilot.press('q')
    print('Terminal check passed: navigation, edit, multi actions, cancel, slot 18, empty pages, rename, delete and narrow layout. No USB or actions executed.')
