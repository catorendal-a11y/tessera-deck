"""One-shot, opt-in Wi-Fi Host proof of concept for esphome-beta.

Install the optional dependency with: python -m pip install -r host/requirements-wifi-poc.txt

This reports one panel event for inspection and sends one cosmetic status notice.
It never invokes the Tessera action engine; USB remains the default input path.
"""
from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from aioesphomeapi import APIClient


def fnv1(text: str) -> int:
    value = 2166136261
    for byte in text.encode("utf-8"):
        value = ((value * 16777619) & 0xFFFFFFFF) ^ byte
    return value


KEY_SLOT_HASHES = {fnv1(f"key_{slot}"): slot for slot in range(1, 19)}


async def run(host: str, port: int) -> None:
    if input(f"Connect to Tessera panel at {host}:{port} over encrypted Wi-Fi? [y/N] ").strip().lower() != "y":
        print("Cancelled; USB operation is unchanged.")
        return
    key = getpass("Panel API Noise key (input hidden): ").strip()
    if not key:
        raise SystemExit("No key supplied; no connection was attempted.")

    client = APIClient(host, port, noise_psk=key)
    first_event = asyncio.Event()

    def on_state(state: object) -> None:
        key_slot = KEY_SLOT_HASHES.get(getattr(state, "key", None))
        event_type = getattr(state, "event_type", None)
        if key_slot is not None and event_type and not first_event.is_set():
            print(f"Panel event received: key_{key_slot} / {event_type}")
            first_event.set()

    try:
        await client.connect(login=True)
        client.subscribe_states(on_state)
        await client.text_command(fnv1("host_status"), "Host online (Wi-Fi PoC)")
        print("One status update sent. Press a panel key to record one Wi-Fi event; Ctrl+C exits.")
        await asyncio.wait_for(first_event.wait(), timeout=120)
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicitly run the Tessera beta Wi-Fi Host PoC")
    parser.add_argument("host", help="panel hostname or LAN address")
    parser.add_argument("--port", type=int, default=6053)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.host, args.port))
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
