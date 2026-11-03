# Security notes

Profiles can run commands, open files and call URLs, so **treat imported profiles like code**. Importing lists every
command, web request, program launch and automatic rule and asks before keeping them (you can import without them).
The editor and the control API accept connections from `127.0.0.1` only, require a per-run token and reject
browser requests. Variable values are refused in shell commands when they contain characters like `& | < > ^ " %`
and are percent-encoded in URLs. Keep API keys out of profiles: write `$(env:NAME)` in an HTTP header or body and
set the variable in Windows; exports replace known credential headers with such references.
Plugins run with your own rights and are not sandboxed; the limited tokens only restrict what they can ask
Tessera to do. Only the project's own GitHub releases, `api.open-meteo.com` and `api.iconify.design` are ever
contacted, each only after you ask for it (update check, weather, online icons).
