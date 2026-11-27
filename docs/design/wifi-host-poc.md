# Wi-Fi Host PoC (draft)

Status: minimal implementation in progress; hardware verification is outstanding.

## Scope

This work targets `esphome-beta` only. The first usable PoC must prove exactly one panel key event reaches Tessera Host over the local network and one Host status update reaches the panel. USB remains the default and existing USB behavior stays intact. This does not include WoL, profiles/telemetry parity, internet access, or v3.x firmware changes.

## Existing pieces

- The beta panel already runs an ESPHome-compatible Native API server on the GUITION P4, with Noise encryption, an API key, mDNS, and per-key event entities.
- The key event path already has a separate event cursor for the API server; it does not need to take ownership of the USB console.
- The Host currently owns the USB serial connection and accepts panel events through its existing action queue.

## Security constraints for the PoC

- Keep Wi-Fi Host transport opt-in and disabled by default.
- The panel is the API server; Host connects outward to the panel on the LAN. Do not add a Host listener or unauthenticated command endpoint.
- The PoC's `aioesphomeapi` package is an optional dependency in `host/requirements-wifi-poc.txt`; normal Host startup does not install or use it.
- Require an explicit interactive confirmation before this standalone PoC connects. The operator enters the panel API key through a hidden prompt; it is not saved, printed, or logged. This is a development pairing flow, not a Host UI integration.
- Use the panel's Noise-encrypted Native API connection. Do not fall back to plaintext if encryption or authentication fails.
- This PoC does not persist a pairing secret. A future Host UI integration must use the operating system's protected credential store and provide an explicit unpair action.
- Do not expose discovery or the transport beyond the local network.

## Minimal implementation

Native API key events cover panel-to-Host input. The PoC uses the standard ESPHome TextCommand message ID 99 with a dedicated `host_status` key; the panel accepts it only inside the existing Noise-authenticated API session and displays the text as a short informational banner. It is not exposed as an open Host endpoint and does not execute a panel action. The standalone Host PoC asks for confirmation, prompts for the key without echo, sends one status update, and records one key event without forwarding it into the existing action engine. USB remains the regular Host startup path.

## Acceptance evidence

This draft demonstrates the intended one-key event and one status update in code, with explicit opt-in and Noise authentication. Hardware operation has not been verified; the standalone PoC is not part of normal Host startup and never flashes firmware.
