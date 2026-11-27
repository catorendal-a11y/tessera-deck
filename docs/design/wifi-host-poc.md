# Wi-Fi Host PoC (draft)

Status: proposal only; no Wi-Fi Host transport is implemented in this commit.

## Scope

This work targets `esphome-beta` only. The first usable PoC must prove exactly one panel key event reaches Tessera Host over the local network and one Host status update reaches the panel. USB remains the default and existing USB behavior stays intact. This does not include WoL, profiles/telemetry parity, internet access, or v3.x firmware changes.

## Existing pieces

- The beta panel already runs an ESPHome-compatible Native API server on the GUITION P4, with Noise encryption, an API key, mDNS, and per-key event entities.
- The key event path already has a separate event cursor for the API server; it does not need to take ownership of the USB console.
- The Host currently owns the USB serial connection and accepts panel events through its existing action queue.

## Security constraints for the PoC

- Keep Wi-Fi Host transport opt-in and disabled by default.
- The panel is the API server; Host connects outward to the panel on the LAN. Do not add a Host listener or unauthenticated command endpoint.
- Require a deliberate approval in the Host UI before pairing. Obtain the panel's API key over the already-connected USB link only as part of that approval; never print or log it.
- Use the panel's Noise-encrypted Native API connection. Do not fall back to plaintext if encryption or authentication fails.
- Keep the pairing secret in the operating system's protected credential store, with an explicit unpair action. Do not put it in profiles, logs, or source control.
- Do not expose discovery or the transport beyond the local network.

## Open implementation detail

Native API key events can cover panel-to-Host input. The reverse direction needs a narrowly defined Host-to-panel request that updates one visible status value. The existing Native API entities are primarily panel-to-client state reports; the PoC must establish whether an existing authenticated command is suitable or whether one small authenticated API message is needed. Do not repurpose an unrelated entity command or claim bidirectional status support until this path is defined and verified.

## Acceptance evidence

The draft is ready for review when it contains a traceable one-key event and one Host-to-panel status update over the encrypted API, has a clear opt-in/pairing path, and demonstrates that a normal start still selects USB. Until then this PR remains a design/WIP draft.
