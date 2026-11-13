# Security

Tessera runs commands, opens files, calls web addresses and starts plugins on your PC when you press a key. This page says what the host exposes, what you should check, and how to report a problem.

## What the host exposes

The editor and the control API are two small web servers inside the host. Neither is reachable from another computer.

| Surface | Listens on | Protection |
|---|---|---|
| Editor | `127.0.0.1`, a free port | A per-run token. Requests whose `Host` is not `127.0.0.1:<port>` or that come from another web page (`Origin` header) are refused. The session cookie is `HttpOnly` and `SameSite=Strict`. |
| Control API (`/v1/…`) | `127.0.0.1`, a free port | A per-run token in the `X-Deck-Token` header. The same `Host` and `Origin` checks. Each token may make 20 calls a second, in bursts of up to 40, then gets `429`. |

- The tokens live in `host/deck-api.local.json` and in the editor's record file. Only your Windows account can read them. They change every time the host starts.
- Plugins get their own token with only the routes they declared, and only variable names that start with `<plugin id>.`. See [Plugins](docs/PLUGINS.md).
- Every call that changes something through the control API is written to the host log (**More → Host log …**) with the caller's name, the method, the path and the answer code. The log never holds request bodies, and it leaves out successful variable updates.
- The panel itself has no network. It only speaks to the host over USB, see [Protocol](docs/PROTOCOL.md).

## Imported profiles

Treat an imported profile like a program. A profile can hold shell commands, web requests, program launches, plugin commands and rules that run by themselves.

- Import lists every shell command, web request (with the host it goes to), program launch outside web links and documents, plugin command and automatic rule, and asks before keeping them. You can import without them.
- An imported file cannot turn plugins on or change their settings.
- Variable values in shell commands are refused when they contain anything other than letters, digits, spaces and `. , : / - _`. In web addresses they are percent-encoded.
- Read a shared profile before you import it, even when you know the author.

## Secrets

- Keep API keys out of profiles. Write `$(env:NAME)` in an HTTP header or body and set the variable in Windows.
- Exports replace known credential headers (`Authorization`, `Cookie`, `X-Api-Key` and similar) with `$(env:…)` references, and leave out the calendar address and plugin settings that look like secrets. The editor tells you what it left out.
- Plugin settings whose key contains `token`, `secret`, `password` or `api_key` are stored encrypted for your Windows account (DPAPI). `profiles.json` and its backups hold only the encrypted form. Another Windows account, or the same files on another PC, cannot read them.

## Plugins

A plugin runs with your own Windows rights. Tessera does not sandbox it. It can read your files and use the network, whatever its manifest says. The manifest only limits what it may ask Tessera to do.

- Install a plugin only from a source you trust, and read its code first.
- The editor asks before a plugin first runs, and again for a new version, and shows the program it starts.
- A plugin's output goes to `host/plugins/<id>.log`.

## What Tessera contacts

Tessera makes these connections, each only after you ask for it:

| Address | When |
|---|---|
| The project's releases on `api.github.com` | The update check. |
| `api.open-meteo.com`, `geocoding-api.open-meteo.com` | The weather on the ambient screen and its city search. |
| `api.iconify.design` | Online icons. |
| Your own HTTP actions, the calendar address you enter for the *Next meeting* widget | When a key or widget uses them. |
| What the plugins you turn on contact | The bundled plugins only reach your own Home Assistant and OBS. |

Setup installs Python packages from PyPI, pinned by SHA-256 hash in `host/requirements.lock`. `tools\setup_sensors.ps1` downloads Libre Hardware Monitor. Releases carry a build attestation and `SHA256SUMS`; [Install](docs/INSTALL.md) shows how to check a download.

## Claude Code's permission questions

*Connect Claude Code* adds hooks to `~/.claude/settings.json`, after a backup, and keeps your other hooks. A question then appears on the panel's agents screen, and only a touch on **Allow** or **Deny** answers it.

Tessera never allows anything on its own. Claude Code falls back to its own dialog when there is no panel, when nobody answers within 25 seconds, or when the request is longer than 150 characters.

## Reporting a security problem

Do not open a public issue.

1. Open **Security → Report a vulnerability** on the repository page, where GitHub offers it. Otherwise contact [@catorendal-a11y](https://github.com/catorendal-a11y) privately on GitHub.
2. Say which version you run (the `VERSION` file holds it) and how to reproduce the problem.
