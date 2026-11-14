"""Home Assistant keys (docs/design/esphome.md, stage C): `homeassistant` steps and keys that follow an HA entity.

The panel runs both itself over its ESPHome API, also with the PC off. The host only checks them, puts them in the
layout for panels that report "ha":1, and never runs a `homeassistant` step.
"""
from __future__ import annotations

import json
import math
import re

KIND = 'homeassistant'
TRIGGER_LISTS = (('actions', 'p'), ('hold_actions', 'h'), ('double_actions', 'd'))
ACTION_NAME = re.compile(r'[a-z_][a-z0-9_]*\.[a-z0-9_]+')  # domain.service, and also domain.object_id
DATA_KEY = re.compile(r'[a-z0-9_]{1,32}')
ATTRIBUTE = re.compile(r'[a-z0-9_]{0,32}')
MAX_ACTION = 64
MAX_ENTITIES = 4
MAX_ENTITY_TEXT = 128
MAX_DATA = 4
MAX_VALUE = 64
MAX_PER_TRIGGER = 2
MAX_PER_PAGE = 24
MAX_FOLLOWED = 18
SHOW = {'accent': 'a', 'value': 'v', 'both': 'b'}
MAX_ON = 4
MAX_ON_TEXT = 16
MAX_UNIT = 6
FOLLOW_KEYS = {'entity_id', 'attribute', 'show', 'on', 'unit'}
UNSUPPORTED = 'The panel firmware does not run Home Assistant keys; update the panel firmware'


def data_text(value) -> str:
    """A data value as the panel sends it: text as it is, true/false lowercase, numbers in JSON form."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or (type(value) in (int, float) and math.isfinite(value)):
        return json.dumps(value)
    raise ValueError('data values must be text, numbers or true/false')


def entity_ids(value, many=True) -> str:
    """The entity id(s) as one comma-separated string without spaces; ValueError when one breaks the rules."""
    if not isinstance(value, str):
        raise ValueError('entity_id must be text')
    parts = [part.strip() for part in value.split(',')]
    if not all(ACTION_NAME.fullmatch(part) for part in parts):
        raise ValueError('entity_id must look like light.kitchen' + (' (or a comma-separated list)' if many else ''))
    if len(parts) > (MAX_ENTITIES if many else 1):
        raise ValueError(f'entity_id may name at most {MAX_ENTITIES} entities' if many else 'entity_id must name one entity')
    joined = ','.join(parts)
    if len(joined) > MAX_ENTITY_TEXT:
        raise ValueError(f'entity_id must be at most {MAX_ENTITY_TEXT} characters')
    return joined


def check_action(action) -> None:
    """`{"type":"homeassistant","action":"light.toggle","entity_id":"light.kitchen","data":{…}}`."""
    unknown = set(action) - {'type', 'action', 'entity_id', 'data'}
    if unknown:
        raise ValueError(f'homeassistant: unknown field {sorted(unknown)[0]}')
    name = action['action']
    if len(name) > MAX_ACTION or not ACTION_NAME.fullmatch(name):
        raise ValueError('homeassistant: action must look like light.toggle (domain.service)')
    try:
        if 'entity_id' in action and action['entity_id'] != '':
            entity_ids(action['entity_id'])
        data = action.get('data', {})
        if not isinstance(data, dict) or len(data) > MAX_DATA:
            raise ValueError(f'data must be an object with at most {MAX_DATA} values')
        for key, value in data.items():
            if not isinstance(key, str) or not DATA_KEY.fullmatch(key) or key == 'entity_id':
                raise ValueError('data names must be 1-32 lowercase letters, digits or _ (put the entity in entity_id)')
            if len(data_text(value)) > MAX_VALUE:
                raise ValueError(f'data value {key} must be at most {MAX_VALUE} characters')
    except ValueError as exc:
        raise ValueError(f'homeassistant: {exc}') from exc


def check_follow(follow) -> None:
    """The key option `ha_state`: follow one entity (or one of its attributes) as the key's color or text."""
    if not isinstance(follow, dict) or set(follow) - FOLLOW_KEYS or 'entity_id' not in follow:
        raise ValueError('ha_state needs entity_id and may set attribute, show, on and unit')
    try:
        entity_ids(follow['entity_id'], many=False)
    except ValueError as exc:
        raise ValueError(f'ha_state: {exc}') from exc
    attribute = follow.get('attribute', '')
    if not isinstance(attribute, str) or not ATTRIBUTE.fullmatch(attribute):
        raise ValueError('ha_state.attribute must be up to 32 lowercase letters, digits or _')
    if follow.get('show', 'accent') not in SHOW:
        raise ValueError('ha_state.show must be accent, value or both')
    on = follow.get('on', ['on'])
    if (not isinstance(on, list) or not 1 <= len(on) <= MAX_ON
            or any(not isinstance(item, str) or not 1 <= len(item) <= MAX_ON_TEXT for item in on)):
        raise ValueError(f'ha_state.on must be 1-{MAX_ON} states of at most {MAX_ON_TEXT} characters')
    unit = follow.get('unit', '')
    if not isinstance(unit, str) or len(unit) > MAX_UNIT:
        raise ValueError(f'ha_state.unit must be at most {MAX_UNIT} characters')


def steps_of(actions) -> list[dict]:
    return [action for action in actions or [] if isinstance(action, dict) and action.get('type') == KIND]


def check_button(button) -> None:
    """Per key: at most two HA steps per trigger, and the follow option when it is set."""
    for key, _ in TRIGGER_LISTS:
        if len(steps_of(button.get(key))) > MAX_PER_TRIGGER:
            raise ValueError(f'use at most {MAX_PER_TRIGGER} Home Assistant steps per trigger')
    if 'ha_state' in button:
        check_follow(button['ha_state'])


def check_page(buttons) -> None:
    """The panel keeps at most 24 HA steps and 18 followed entities for one page (it shows one page at a time)."""
    steps = sum(len(steps_of(button.get(key))) for button in buttons for key, _ in TRIGGER_LISTS)
    if steps > MAX_PER_PAGE:
        raise ValueError(f'a page may hold at most {MAX_PER_PAGE} Home Assistant steps')
    if sum('ha_state' in button for button in buttons) > MAX_FOLLOWED:
        raise ValueError(f'a page may follow at most {MAX_FOLLOWED} Home Assistant entities')


def only_panel_steps(actions) -> bool:
    """A trigger whose steps all run on the panel: the panel gives the feedback, the host sends none."""
    return bool(actions) and len(steps_of(actions)) == len(actions)


def step_entry(action) -> dict:
    entry = {'a': action['action']}
    if action.get('entity_id'):
        entry['e'] = entity_ids(action['entity_id'])
    if action.get('data'):
        entry['d'] = {key: data_text(value) for key, value in action['data'].items()}
    return entry


def layout_fields(button) -> dict:
    """The `ha` and `hs` fields of a layout entry (design C.3); empty when the key has neither."""
    fields = {}
    steps = {short: [step_entry(action) for action in steps_of(button.get(key))] for key, short in TRIGGER_LISTS}
    steps = {short: items for short, items in steps.items() if items}
    if steps:
        fields['ha'] = steps
    follow = button.get('ha_state')
    if isinstance(follow, dict):
        fields['hs'] = {'e': follow['entity_id'].strip(), 'a': follow.get('attribute', ''),
                        'm': SHOW[follow.get('show', 'accent')], 'on': list(follow.get('on', ['on'])),
                        'u': follow.get('unit', '')}
    return fields


def uses_homeassistant(button) -> bool:
    return 'ha_state' in button or any(steps_of(button.get(key)) for key, _ in TRIGGER_LISTS)


def describe(action) -> str:
    """`Home Assistant: light.toggle on light.kitchen` for the dry run."""
    text = f'Home Assistant: {action["action"]}'
    if action.get('entity_id'):
        text += f' on {entity_ids(action["entity_id"]).replace(",", ", ")}'
    if action.get('data'):
        text += ' with ' + ', '.join(f'{key}={data_text(value)}' for key, value in action['data'].items())
    return text + ' (the panel sends it)'
