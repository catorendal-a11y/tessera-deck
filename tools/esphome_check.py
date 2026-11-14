"""Check the panel's ESPHome-compatible API from this PC, the way Home Assistant talks to it.

Connects to the panel's IP on port 6053 with the encryption key, prints the device info, lists the entities,
subscribes to states for 20 seconds and prints them. It presses nothing and changes nothing, unless you pass
--press-test: then it switches the backlight light once (off, or on when it is off) and back.

aioesphomeapi is not a host dependency. Install it into a separate venv, outside host/.venv:

    py -3 -m venv %USERPROFILE%\\esphome-check-venv
    %USERPROFILE%\\esphome-check-venv\\Scripts\\python.exe -m pip install aioesphomeapi
    %USERPROFILE%\\esphome-check-venv\\Scripts\\python.exe tools\\esphome_check.py --host 192.168.1.40

The key comes from Panel -> Wi-Fi and Home Assistant -> Show key in the editor. Pass it with --key, or put it in
the TESSERA_API_KEY environment variable so it stays out of your shell history. Never save it in a file in the repo.
This script never prints the key.
"""
import argparse
import asyncio
import inspect
import os
import sys

PORT = 6053
WATCH_SECONDS = 20


async def maybe_await(value):
    """aioesphomeapi made several calls (subscribe_states, light_command) plain functions in newer releases."""
    return await value if inspect.isawaitable(value) else value


def describe_state(state, names) -> str:
    fields = {name: getattr(state, name) for name in ('state', 'brightness', 'event_type', 'missing_state')
              if hasattr(state, name)}
    return f'{names.get(state.key, state.key)}: {type(state).__name__} {fields}'


async def press_test(client, backlight, states) -> None:
    """Switch the backlight once and back, so you see the light follow (and the panel's brightness return)."""
    before = states.get(backlight.key)
    was_on = bool(getattr(before, 'state', True))
    brightness = getattr(before, 'brightness', None) or 1.0
    print(f'Press test: backlight {"off" if was_on else "on"} for 3 s, then back')
    await maybe_await(client.light_command(backlight.key, state=not was_on))
    await asyncio.sleep(3)
    if was_on:
        await maybe_await(client.light_command(backlight.key, state=True, brightness=brightness))
    else:
        await maybe_await(client.light_command(backlight.key, state=False))
    await asyncio.sleep(2)
    after = states.get(backlight.key)
    print(f'Press test: backlight now state={getattr(after, "state", None)} brightness={getattr(after, "brightness", None)}')


async def run(host, key, seconds, press) -> int:
    try:
        from aioesphomeapi import APIClient, LightInfo
    except ImportError:
        print('aioesphomeapi is missing: install it into a separate venv (see the top of this file).', file=sys.stderr)
        return 2
    client = APIClient(host, PORT, None, noise_psk=key)
    await client.connect(login=True)
    try:
        info = await client.device_info()
        for field in ('name', 'friendly_name', 'mac_address', 'model', 'manufacturer', 'esphome_version',
                      'project_name', 'project_version', 'compilation_time', 'suggested_area', 'api_encryption_supported'):
            print(f'{field}: {getattr(info, field, None)}')
        entities, _services = await client.list_entities_services()
        names = {}
        print(f'{len(entities)} entities:')
        for entity in entities:
            object_id = getattr(entity, 'object_id', '') or ''
            names[entity.key] = object_id or entity.name
            print(f'  {type(entity).__name__:<22} {object_id:<14} key={entity.key:<10} name={entity.name!r}')
        states = {}

        def on_state(state):
            states[state.key] = state
            print(describe_state(state, names))

        await maybe_await(client.subscribe_states(on_state))
        print(f'Watching states for {seconds} s (tap a key on the panel to see its event) ...')
        await asyncio.sleep(seconds)
        if press:
            backlight = next((e for e in entities if isinstance(e, LightInfo)
                              and (getattr(e, 'object_id', '') == 'backlight' or e.name == 'Backlight')), None)
            if backlight is None:
                print('Press test: the panel has no backlight light', file=sys.stderr)
                return 1
            await press_test(client, backlight, states)
    finally:
        await client.disconnect()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--host', required=True, help="the panel's IP address (shown in the editor's Wi-Fi dialog)")
    parser.add_argument('--key', help='the encryption key (default: the TESSERA_API_KEY environment variable)')
    parser.add_argument('--seconds', type=int, default=WATCH_SECONDS, help='how long to watch states')
    parser.add_argument('--press-test', action='store_true', help='switch the backlight once and back')
    args = parser.parse_args(argv)
    key = args.key or os.environ.get('TESSERA_API_KEY', '')
    if not key:
        parser.error('give the key with --key or TESSERA_API_KEY')
    try:
        return asyncio.run(run(args.host, key, max(1, args.seconds), args.press_test))
    except Exception as exc:  # aioesphomeapi's errors name what failed (wrong key, refused, timeout); never the key
        print(f'Failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
