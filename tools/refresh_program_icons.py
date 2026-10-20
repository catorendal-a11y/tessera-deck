#!/usr/bin/env python3
"""Give every program button its real app icon.

By default the icon is set to "app", which the host resolves from the button's open
action at runtime (portable, no image files stored). With --freeze the icon is
imported now and stored as an im: image instead.

Dry run by default. With --apply the old profiles file is kept as
profiles.backup.local.json next to it, and the running host hot-reloads the result.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from tesserad import validate_config  # noqa: E402
from deck_assets import Assets, resolve_program_target  # noqa: E402

PROGRAM_SUFFIXES = ('.exe', '.lnk')


def program_target(button):
    """The first open-action target that is an installed program, else None."""
    for action in button.get('actions', []):
        if action.get('type') != 'open':
            continue
        try:
            resolved = resolve_program_target(action['target'])
        except ValueError:
            continue
        if resolved.lower().startswith('shell:appsfolder') or resolved.lower().endswith(PROGRAM_SUFFIXES):
            return action['target']
    return None


def iter_buttons(config):
    for profile_name, profile in config['profiles'].items():
        groups = list(profile['pages'].items()) + [('(pinned)', profile.get('pinned', []))]
        for page_name, buttons in groups:
            for button in buttons:
                yield f'{profile_name}/{page_name}', button


def refresh(config, assets, only_images=False, freeze=False):
    """Return (new_config, changes) without modifying the input config."""
    new_config = json.loads(json.dumps(config))
    changes, imported = [], {}
    for where, button in iter_buttons(new_config):
        target = program_target(button)
        old = button.get('icon', 'ok')
        if target is None or (only_images and not old.startswith('im:')):
            continue
        if not freeze:
            imported[target] = 'app'
        if target not in imported:
            try:
                imported[target] = assets.import_program_icon(target)['id']
            except (ValueError, OSError) as exc:
                print(f'  skipping {target}: {exc}')
                imported[target] = None
        new = imported[target]
        if new and new != old:
            button['icon'] = new
            changes.append((where, button['label'], old, new))
    return new_config, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', default=str(ROOT / 'host/profiles.json'))
    parser.add_argument('--apply', action='store_true', help='write the changes to the profiles file')
    parser.add_argument('--freeze', action='store_true',
                        help='import the icons now and store them as im: images')
    parser.add_argument('--only-images', action='store_true',
                        help='only replace buttons that already use an image (im:)')
    args = parser.parse_args()
    path = Path(args.profiles)
    config = json.loads(path.read_text(encoding='utf-8'))
    new_config, changes = refresh(config, Assets(path), args.only_images, args.freeze)
    for where, label, old, new in changes:
        print(f'{where}: {label}: {old} -> {new}')
    if not changes:
        print('No icons to update.')
        return 0
    validate_config(new_config)
    if not args.apply:
        print(f'{len(changes)} buttons would change. Run again with --apply.')
        return 0
    backup = path.with_name('profiles.backup.local.json')
    backup.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(new_config, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    print(f'{len(changes)} buttons updated. Backup: {backup.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
