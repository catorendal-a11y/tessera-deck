# Security notes

Profiles can run commands, open files and call URLs, so **treat imported profiles like code**. Importing lists every
command, web request, program launch and automatic rule and asks before keeping them (you can import without them).
The editor and the control API accept connections from `127.0.0.1` only, require a per-run token and reject
browser requests. Variable values are refused in shell commands when they contain characters like `& | < > ^ " %`
and are percent-encoded in URLs. Keep API keys out of profiles: write `$(env:NAME)` in an HTTP header or body and
set the variable in Windows; exports replace known credential headers with such references.
Plugins run with your own rights and are not sandboxed; the limited tokens only restrict what they can ask
Tessera to do. While running, Tessera itself only contacts the project's own GitHub releases, `api.open-meteo.com` and
`api.iconify.design`, each only after you ask for it (update check, weather, online icons), plus the addresses in your
own HTTP actions. Setup installs Python packages from PyPI, and `tools\setup_sensors.ps1` downloads Libre Hardware Monitor.

**Claude Code's permission questions.** *Connect Claude Code* adds hooks to `~/.claude/settings.json` (after a backup, keeping your other hooks). A question is then shown on the panel's agents screen and only a touch on **Allow** or **Deny** answers it. Tessera never allows anything on its own: with no panel, no answer within 25 seconds or a request too long to show in full, Claude Code falls back to its own dialog.

## Reporting a security problem

Please do not open a public issue. Contact [@catorendal-a11y](https://github.com/catorendal-a11y) privately through GitHub, or use **Security → Report a vulnerability** on the repository page where it is offered. Say which version you run and how to reproduce the problem.
