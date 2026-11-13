'use strict';
// Editor part 3 of 3: the dialogs (firmware, colors, test mode, ambient, images, icons, theme, backups, log, plugins).
/* Brand: the 3x3 mosaic mark and the tile wordmark, identical to the device header. */
function brandColor(t) {
  const stops = [[88, 224, 155], [77, 208, 225], [179, 136, 255]];
  const scaled = Math.min(Math.max(t, 0), 1) * 2, i = Math.min(Math.floor(scaled), 1), f = scaled - i;
  return `rgb(${stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * f)).join(',')})`;
}
function brandTile(parent, x, y, size, radius, color) {
  const tile = document.createElement('i');
  tile.style.cssText = `left:${x}px;top:${y}px;width:${size}px;height:${size}px;border-radius:${radius}px;background:${color}`;
  parent.append(tile);
}
function mountBrand() {
  const glyphs = {
    T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
    E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
    S: ['01111', '10000', '10000', '01110', '00001', '00001', '11110'],
    R: ['11110', '10001', '10001', '11110', '10100', '10010', '10001'],
    A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001']
  };
  document.querySelectorAll('[data-logo]').forEach(el => {
    for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
      if (row === 0 && col === 2) continue;
      brandTile(el, col * 16, 4 + row * 16, 13, 4, brandColor((row + col) / 4));
    }
    brandTile(el, 34, 0, 12, 4, '#ffb74d');
  });
  document.querySelectorAll('[data-wordmark]').forEach(el => {
    [...'TESSERA'].forEach((letter, n) => glyphs[letter].forEach((line, row) => [...line].forEach((bit, col) => {
      if (bit === '1') brandTile(el, n * 22 + col * 4, row * 4, 3, 1, brandColor((n * 5 + col) / 34));
    })));
  });
}
mountBrand();

/* Panel firmware: list verified packages, install with progress. */
let firmwareTimer = null;
async function openFirmware() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  // "Install anyway" is for the one attempt after a panel that did not answer; never carry it over.
  // With no panel connected it is most likely new or blank, so offer the full install and the box straight away.
  const blank = !dashboard?.device?.connected;
  $('#firmware-force').checked = false;
  $('.firmware-force').hidden = !blank;
  $('#firmware-mode').value = blank ? 'full' : 'app';
  $('#firmware-dialog').showModal();
  try { await refreshFirmware(); } catch (error) { showError(error); }
}
async function refreshFirmware() {
  const info = await api('command/firmware-list', {});
  const select = $('#firmware-package'), good = info.packages.filter(p => !p.error);
  select.replaceChildren();
  for (const p of good) select.append(element('option', {value: p.path, text: `Version ${p.version} · ${Math.round(p.bytes / 1024)} KiB`}));
  for (const p of info.packages.filter(item => item.error)) select.append(element('option', {value: '', disabled: 'true', text: `${p.path.split(/[\\/]/).pop()} · ${p.error}`}));
  if (!info.packages.length) select.append(element('option', {value: '', text: 'No package found in dist/ or firmware/'}));
  const device = info.device, newest = good[0];
  // The protocol number only matters to the user when it differs from the newest package's.
  const protocol = newest && device.protocol != null && newest.protocol !== device.protocol ? ` · protocol ${device.protocol}, package needs ${newest.protocol}` : '';
  $('#firmware-device').textContent = device.connected
    ? `Panel connected · firmware ${device.firmware || 'unknown'}${protocol} · Tessera ${info.host || '?'}`
    : `The panel is not connected · Tessera ${info.host || '?'}`;
  $('#firmware-install').disabled = !good.length;
  if (info.job.state === 'running') pollFirmware();
}
async function installFirmware() {
  const path = $('#firmware-package').value;
  if (!path || !await confirmDialog('Write the firmware now?', 'Do not unplug the panel until it has finished.', {ok: 'Write firmware'})) return;
  const force = $('#firmware-force').checked;
  $('#firmware-force').checked = false;
  $('.firmware-force').hidden = true;
  try { await api('command/firmware-install', {package: path, mode: $('#firmware-mode').value, force}); }
  catch (error) { showError(error); return; }
  pollFirmware();
}
async function pollFirmware() {
  clearTimeout(firmwareTimer);
  $('.firmware-progress').hidden = false;
  let job;
  try { job = (await api('command/firmware-progress', {})).job; } catch (error) { showError(error); return; }
  $('#firmware-bar').value = job.percent || 0;
  const label = $('#firmware-state');
  if (job.state === 'running') {
    label.textContent = `${job.stage === 'checking' ? 'Checking the panel' : 'Writing'} … ${job.percent || 0}%`;
    firmwareTimer = setTimeout(pollFirmware, 700);
  } else if (job.state === 'done') {
    label.textContent = `Installed ${job.result.installed}${job.result.previous ? ` (was ${job.result.previous})` : ''}.`
      + (job.restarted ? ' The host has started again.' : job.restart_error ? ` The host did not start again: ${job.restart_error}` : '');
  } else if (job.state === 'failed') {
    label.textContent = job.error || 'The installation failed.';
    const silent = (job.error || '').includes('did not answer');
    $('.firmware-force').hidden = !silent;
    if (silent) $('#firmware-mode').value = 'full';  // a panel that does not answer needs everything written
  }
  $('#firmware-install').disabled = job.state === 'running';
}
$('#firmware-open').onclick = openFirmware;
$('#firmware-close').onclick = () => $('#firmware-dialog').close();
$('#firmware-install').onclick = installFirmware;

/* Key colors: an own background, label color and outline per button (or per state of a toggle button), as a Look row. */
function renderStyle(propRow) {
  const row = (label, key, fallback) => {
    const input = element('input', {type: 'color', value: appearance()[key] || fallback, 'aria-label': label});
    input.addEventListener('input', () => mutate(() => { appearance()[key] = input.value.toUpperCase(); }, false, editKey('style', key)));
    return element('div', {class: 'appearance-row'}, text('span', label, 'hint'), input,
      button('Default', () => mutate(() => { delete appearance()[key]; }), 'text-button'));
  };
  const result = propRow('Key colors', row('Background', 'bg', '#172329'), row('Label text', 'text_color', '#E8F4EF'), row('Outline', 'border', '#31444D'));
  result.classList.add('prop-row-colors');
  return result;
}

/* Test mode: what pressing a key would do, explained by the host without running anything. */
async function testButton(id = selected) {
  const base = visibleButtons().find(b => b.id === id);
  if (!base) return toast('Choose a key with an action first.');
  const holder = base.states ? base.states[id === selected ? Math.min(editState, base.states.length - 1) : 0] : base;
  const payload = {actions: clone(holder.actions || [])};
  if (base.hold_actions?.length) payload.hold_actions = clone(base.hold_actions);
  if (base.double_actions?.length) payload.double_actions = clone(base.double_actions);
  const result = await api('command/dryrun', payload);
  const box = $('#test-steps');
  box.replaceChildren();
  $('#test-title').textContent = `Test: ${resolveLabel(holder.label || base.label) || `key ${id}`}`;
  const section = (title, report) => {
    box.append(text('h3', title));
    if (!report.steps.length) box.append(text('p', 'No actions.', 'hint'));
    for (const step of report.steps) box.append(element('div', {class: `test-step ${step.ok ? 'ok' : 'bad'}`}, text('span', step.ok ? '✓' : '✕', 'test-mark'), text('span', `${step.index}. ${step.text}`)));
    if (report.wait_seconds) box.append(text('p', `Waits ${report.wait_seconds} s in total.`, 'hint'));
  };
  section('When pressed', result.actions || {steps: [], wait_seconds: 0});
  if (result.hold_actions) section('When held', result.hold_actions);
  if (result.double_actions) section('When double-pressed', result.double_actions);
  $('#test-run').onclick = () => runKey(id, payload.actions).catch(showError);
  $('#test-dialog').showModal();
}
/* Run now: the host presses the key as the panel would, after a confirm for steps that act on this PC. */
async function runKey(id, actions) {
  const risky = {shell: 'runs a command', http: 'sends a web request', text: 'types text'};
  const effects = [...new Set(actions.map(a => risky[a.type]).filter(Boolean))];
  if (effects.length && !await confirmDialog('Run this key now?', `This key ${effects.join(', ')} on this PC.`, {ok: 'Run now'})) return;
  await save();  // the host runs what is saved
  toast((await api('command/run-key', {profile, page, button: id})).message);
}

/* Display: the panel's own settings. Brightness, dimming and quiet hours, then the big clock (and optional weather) when idle. */
function displaySettings() {
  const display = {brightness: 100, dim_after: 300, dim_level: 10, ...(config.display || {})};
  const ambient = {enabled: false, after: 120, ...(config.ambient || {})}, weather = ambient.weather;
  const afterChoices = [30, 60, 120, 300, 600].map(v => [String(v), v < 60 ? `${v} seconds` : `${v / 60} min`]);
  if (!afterChoices.some(([v]) => Number(v) === ambient.after)) afterChoices.push([String(ambient.after), `${ambient.after} seconds`]);
  const where = weather ? `Currently ${weather.name} in ${weather.unit === 'fahrenheit' ? 'Fahrenheit' : 'Celsius'}. ` : '';
  dialog('Display', [
    {name: 'brightness', label: 'Panel brightness', options: displayChoices(brightnessChoices, display.brightness, v => `${v}%`), value: String(display.brightness)},
    {name: 'dimAfter', label: 'Dim the panel after', options: displayChoices(dimAfterChoices, display.dim_after, v => `${Math.round(v / 60)} min`), value: String(display.dim_after), note: 'The first touch on a dimmed panel only wakes it; it does not press a key.'},
    {name: 'dimLevel', label: 'Brightness when dimmed', options: displayChoices(dimLevelChoices, display.dim_level, v => v ? `${v}%` : 'Off'), value: String(display.dim_level)},
    {name: 'nightWindow', label: 'Quiet hours', options: nightChoices(display.night), value: nightWindowValue(display.night), note: 'Between these times the panel uses the lower brightness below instead of the normal one.'},
    {name: 'nightLevel', label: 'Brightness during quiet hours', options: displayChoices(nightLevelChoices, display.night?.brightness || 10, v => `${v}%`), value: String(display.night?.brightness || 10)},
    {name: 'enabled', label: 'Show a big clock when the panel has been idle', type: 'checkbox', value: ambient.enabled, note: 'Touch the panel to get your keys back. Needs the firmware that ships with this version.'},
    {name: 'after', label: 'Show it after', options: afterChoices, value: String(ambient.after)},
    {name: 'city', label: 'Weather for (city, optional)', value: weather?.name || '', note: `${where}Weather comes from open-meteo.com every 15 minutes. Leave the city empty for no weather and no internet use.`},
    {name: 'unit', label: 'Temperature unit', options: [['celsius', 'Celsius'], ['fahrenheit', 'Fahrenheit']], value: weather?.unit || 'celsius'}
  ], values => {
    const city = values.city.trim(), keep = weather && weather.name === city;
    mutate(() => {
      config.display = {brightness: Number(values.brightness), dim_after: Number(values.dimAfter), dim_level: Number(values.dimLevel)};
      const night = nightFromValues(values.nightWindow, values.nightLevel);
      if (night) config.display.night = night;
      config.ambient = {enabled: values.enabled, after: Number(values.after)};
      // A new city keeps the old weather until the lookup succeeds (choose() replaces it); only an empty city drops it.
      if (city && weather) config.ambient.weather = {...weather, unit: values.unit};
    });
    if (city && !keep) lookupCity(city, values.unit).catch(showError);
  }, 'Apply');
}
async function lookupCity(city, unit) {
  const {places} = await api('command/weather-search', {query: city});
  if (!places.length) throw new Error(`No place called “${city}” was found.`);
  const describe = place => [place.name, place.region, place.country].filter(Boolean).join(', ');
  const choose = place => {
    mutate(() => { config.ambient = {...(config.ambient || {enabled: true, after: 120}), weather: {name: place.name, latitude: place.latitude, longitude: place.longitude, unit}}; });
    toast(`Weather for ${describe(place)}.`);
  };
  if (places.length === 1) return choose(places[0]);
  dialog('Which place?', [{name: 'place', label: `Several places match “${city}”`, options: places.map((place, index) => [String(index), describe(place)]), value: '0'}],
    values => choose(places[Number(values.place)]), 'Use this place');
}

/* Images: crop still pictures to the square the key shows; animations are sent as they are. */
async function chooseImage(file, id = selected) {
  if (!file) return;
  if (file.type === 'image/gif' || file.type === 'image/webp') return uploadImage(file, id);
  const bitmap = await createImageBitmap(file);
  const blob = await openCropper(bitmap);
  bitmap.close?.();
  if (!blob) return;
  await uploadImage(new File([blob], `${file.name.replace(/\.[^.]+$/, '')}.png`, {type: 'image/png'}), id);
}
function openCropper(bitmap) {
  return new Promise(resolve => {
    const view = $('#crop-dialog'), canvas = $('#crop-canvas'), context = canvas.getContext('2d'), zoom = $('#crop-zoom');
    const size = canvas.width, cover = Math.max(size / bitmap.width, size / bitmap.height), stop = new AbortController();
    let scale = 1, x = (size - bitmap.width * cover) / 2, y = (size - bitmap.height * cover) / 2, drag = null, answer = null;
    const clamp = () => {
      const w = bitmap.width * cover * scale, h = bitmap.height * cover * scale;
      x = Math.min(0, Math.max(size - w, x));
      y = Math.min(0, Math.max(size - h, y));
    };
    const draw = () => {
      clamp();
      context.fillStyle = '#091014';
      context.fillRect(0, 0, size, size);
      context.drawImage(bitmap, x, y, bitmap.width * cover * scale, bitmap.height * cover * scale);
    };
    const setZoom = value => {
      const w = bitmap.width * cover * scale, h = bitmap.height * cover * scale, cx = (size / 2 - x) / w, cy = (size / 2 - y) / h;
      scale = Math.min(4, Math.max(1, value));
      x = size / 2 - cx * bitmap.width * cover * scale;
      y = size / 2 - cy * bitmap.height * cover * scale;
      zoom.value = String(Math.round(scale * 100));
      draw();
    };
    const finish = blob => { answer = blob; view.close(); };
    canvas.addEventListener('pointerdown', event => { drag = {px: event.clientX, py: event.clientY, x, y}; canvas.setPointerCapture(event.pointerId); }, {signal: stop.signal});
    canvas.addEventListener('pointermove', event => { if (!drag) return; const k = size / canvas.getBoundingClientRect().width; x = drag.x + (event.clientX - drag.px) * k; y = drag.y + (event.clientY - drag.py) * k; draw(); }, {signal: stop.signal});
    canvas.addEventListener('pointerup', () => { drag = null; }, {signal: stop.signal});
    canvas.addEventListener('wheel', event => { event.preventDefault(); setZoom(scale + (event.deltaY < 0 ? .1 : -.1)); }, {signal: stop.signal, passive: false});
    zoom.addEventListener('input', () => setZoom(Number(zoom.value) / 100), {signal: stop.signal});
    $('#crop-cancel').addEventListener('click', () => finish(null), {signal: stop.signal});
    $('#crop-use').addEventListener('click', () => {
      const out = document.createElement('canvas'), k = 144 / size;
      out.width = out.height = 144;
      out.getContext('2d').drawImage(bitmap, x * k, y * k, bitmap.width * cover * scale * k, bitmap.height * cover * scale * k);
      out.toBlob(blob => finish(blob), 'image/png');
    }, {signal: stop.signal});
    view.addEventListener('close', () => { stop.abort(); resolve(answer); }, {once: true});
    zoom.value = '100';
    draw();
    view.showModal();
  });
}

/* Online icons (Iconify): searched and fetched by the host only when the user asks. */
let iconifyRun = 0;  // a newer search stops the older one's workers from adding icons
async function iconifySearch() {
  const run = ++iconifyRun;
  const query = $('#iconify-query').value.trim(), box = $('#iconify-results');
  $('#iconify-note').hidden = false;
  box.hidden = false;
  box.replaceChildren(text('p', 'Searching …', 'hint'));
  const {icons} = await api('command/iconify-search', {query});
  if (run !== iconifyRun) return;
  box.replaceChildren();
  if (!icons.length) { box.append(text('p', 'Nothing found online.', 'hint')); return; }
  const queue = [...icons];
  const load = async () => {
    while (queue.length && run === iconifyRun) {
      const id = queue.shift(), item = button('', () => useOnlineIcon(id).catch(showError), 'icon-choice online', id);
      box.append(item);
      try {
        const {svg} = await api('command/iconify-svg', {id, color: '#FFFFFF'});
        if (run !== iconifyRun) return;
        item.replaceChildren(element('img', {src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, alt: id, width: '36', height: '36'}));
      } catch { item.textContent = '?'; }
    }
  };
  await Promise.all([load(), load(), load(), load()]);
}
async function useOnlineIcon(id) {
  // A rail shortcut takes only library icons (lc:…): the panel draws them from its font, and the host refuses an image there.
  if (iconPick) return toast('A rail shortcut can only use an icon from the library above.');
  const {svg} = await api('command/iconify-svg', {id, color: (appearance()?.color || '#FFFFFF').toUpperCase()});
  const image = new Image();
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 144;
  canvas.getContext('2d').drawImage(image, 0, 0, 144, 144);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  await uploadImage(new File([blob], `${id.replace(':', '-')}.png`, {type: 'image/png'}));
  $('#icon-dialog').close();
}
/* Theme: the default look of every key (a key's own colors still win). */
const THEMES = {
  midnight: {name: 'Midnight blue', bg: '#10243E', text_color: '#E6F1FF', border: '#3B82F6'},
  graphite: {name: 'Graphite', bg: '#22272B', text_color: '#EDEFF0', border: '#4A5258'},
  forest: {name: 'Forest', bg: '#14281E', text_color: '#E3F5EA', border: '#35A06B'},
  paper: {name: 'Paper', bg: '#E9EEF0', text_color: '#101820', border: '#8FA0A8'},
  ember: {name: 'Ember', bg: '#2A1A14', text_color: '#FFEDE0', border: '#E8793C'}
};
function themeSettings() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  const theme = config.theme || {};
  const current = Object.entries(THEMES).find(([, preset]) => preset.bg === theme.bg && preset.text_color === theme.text_color && preset.border === theme.border)?.[0] || (Object.keys(theme).length ? 'custom' : 'default');
  dialog('Key colors', [
    {name: 'preset', label: 'Theme', options: [['default', 'Default'], ...Object.entries(THEMES).map(([id, preset]) => [id, preset.name]), ['custom', 'Custom colors below']], value: current},
    {name: 'bg', label: 'Key background (custom)', type: 'color', value: theme.bg || '#172329'},
    {name: 'text_color', label: 'Label text (custom)', type: 'color', value: theme.text_color || '#E8F4EF'},
    {name: 'border', label: 'Key outline (custom)', type: 'color', value: theme.border || '#31444D', note: 'Applies to every key that has no colors of its own. Pick Default to go back to the standard look.'}
  ], values => mutate(() => {
    if (values.preset === 'default') delete config.theme;
    else if (values.preset === 'custom') config.theme = {bg: values.bg.toUpperCase(), text_color: values.text_color.toUpperCase(), border: values.border.toUpperCase()};
    else { const {bg, text_color, border} = THEMES[values.preset]; config.theme = {bg, text_color, border}; }
  }), 'Apply');
}
$('#theme-open').onclick = themeSettings;

/* Backups: the host keeps rotating copies of profiles.json; any of them can be put back. */
async function openBackups() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  const {backups} = await api('command/backups', {}), list = $('#backup-list');
  list.replaceChildren();
  if (!backups.length) list.append(text('p', 'No backups yet. The first one is made when you change something.', 'hint'));
  for (const item of backups) {
    list.append(element('div', {class: 'backup-row'},
      element('div', {}, text('strong', item.saved), text('small', `${item.profiles} profiles · ${item.buttons} keys · ${Math.max(1, Math.round(item.bytes / 1024))} KiB`)),
      button('Restore', () => restoreBackup(item).catch(showError), 'outline')));
  }
  $('#backup-dialog').showModal();
}
async function restoreBackup(item) {
  if (!await confirmDialog('Restore this backup?', `The current configuration is replaced by the backup from ${item.saved}. The current one is kept as a backup.`, {ok: 'Restore'})) return;
  const state = await api('command/restore-backup', {name: item.name});
  config = state.config; revision = state.revision;
  dirty = false; conflicted = false; configError = ''; history = []; future = [];
  renderStatusBar();
  $('#reload').hidden = true;
  $('#backup-dialog').close();
  renderAll();
  setSaveState('✓ Backup restored');
}
/* Updates and diagnostics: only when the user asks. */
async function checkUpdates() {
  const label = $('#firmware-latest');
  label.textContent = 'Checking GitHub …';
  const info = await api('command/update-check', {});
  $('#firmware-download').hidden = !(info.firmware && info.sums);  // also for a new panel on the latest version
  label.textContent = info.newer
    ? `Version ${info.latest} is available (you have ${info.current}).${info.firmware ? '' : ' It has no firmware package.'}`
    : `You have the latest version (${info.current}).${info.firmware ? ' Its firmware can still be downloaded for the panel.' : ''}`;
  if (info.newer) label.append(' ', element('a', {href: info.page, target: '_blank', rel: 'noopener', text: 'Release notes and the Windows program'}));
  if (info.newer && info.notes) label.append(element('pre', {class: 'release-notes', text: info.notes}));  // what is new, before you download
}
async function downloadFirmware() {
  const result = await api('command/update-download-firmware', {});
  toast(result.message);
  await refreshFirmware();
}
$('#firmware-check').onclick = () => checkUpdates().catch(error => { $('#firmware-latest').textContent = error.message; });
$('#firmware-download').onclick = () => downloadFirmware().catch(showError);
$('#diagnostics-export').onclick = async () => { document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; }); try { await command('diagnostics'); } catch (error) { showError(error); } };
/* Host log: a live tail of the host's own log, like a serial monitor for the whole product. */
let logTimer = null;
async function refreshLog() {
  const view = $('#log-view'), atEnd = view.scrollHeight - view.scrollTop - view.clientHeight < 40;
  const log = (await api('command/host-log', {lines: 200})).log;
  if (view.textContent !== log) view.textContent = log;
  if (atEnd) view.scrollTop = view.scrollHeight;
}
async function openLog() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  await refreshLog();
  $('#log-view').scrollTop = $('#log-view').scrollHeight;
  $('#log-dialog').showModal();
  clearInterval(logTimer);
  logTimer = setInterval(() => refreshLog().catch(() => {}), 2000);
}
$('#log-open').onclick = () => openLog().catch(showError);
$('#log-close').onclick = () => $('#log-dialog').close();
$('#log-dialog').addEventListener('close', () => clearInterval(logTimer));

/* Plugins: turn integrations on and off and set their options; the host starts and stops them. */
async function openPlugins() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  await renderPlugins();
  $('#plugins-dialog').showModal();
}
async function renderPlugins() {
  const {plugins, problems} = await api('command/plugins', {}), list = $('#plugins-list');
  list.replaceChildren();
  if (!plugins.length) list.append(text('p', 'No plugins installed. Put a plugin folder in the plugins folder next to Tessera.cmd.', 'hint'));
  for (const plugin of plugins) {
    const box = element('div', {class: 'plugin-row'});
    const toggle = element('label', {class: 'check-option'}, element('input', {type: 'checkbox'}), element('span', {},
      text('strong', `${plugin.name} ${plugin.version}`),
      text('small', `${plugin.enabled ? plugin.state : 'off'} · may use: ${plugin.permissions.join(', ') || 'nothing'}`)));
    const check = toggle.querySelector('input');
    check.checked = plugin.enabled;
    check.onchange = async () => {
      if (check.checked && !await pluginConsent(plugin)) { check.checked = false; return; }
      setPlugin(plugin.id, {enabled: check.checked}); save().then(renderPlugins).catch(showError);  // the list shows the host's state, so save first
    };
    box.append(toggle);
    if (plugin.error) box.append(text('p', plugin.error, 'error'));
    for (const [key, spec] of Object.entries(plugin.settings || {})) {
      const value = plugin.values[key] ?? spec.default ?? (spec.type === 'checkbox' ? false : '');
      if (spec.type === 'checkbox') {
        const option = element('label', {class: 'check-option'}, element('input', {type: 'checkbox'}), element('span', {}, text('strong', spec.label || key)));
        const input = option.querySelector('input');
        input.checked = !!value;
        input.onchange = () => setPlugin(plugin.id, {settings: {[key]: input.checked}});
        box.append(option);
      } else {
        // a secret comes back encrypted from the host: hide it, and typing a new one replaces it
        const type = spec.type === 'number' ? 'number' : SECRET_SETTING.test(key) ? 'password' : 'text';
        box.append(field(spec.label || key, String(value), v => setPlugin(plugin.id, {settings: {[key]: spec.type === 'number' ? Number(v) : v}}), {type}));
      }
    }
    list.append(box);
  }
  for (const problem of problems) list.append(text('p', problem, 'error'));
}
const SECRET_SETTING = /token|secret|password|api.?key/i;  // as import_review.py
const PLUGIN_RIGHTS = {vars: 'set values shown on keys (names starting with the plugin id)', press: 'press keys',
  feedback: 'flash keys green or red', state: 'change the state of keys', events: 'read key presses, page changes and its commands',
  read: 'read the panel state and all values'};
/* Ask once per plugin id and manifest version before it first runs: a new version may ask for more. */
async function pluginConsent(plugin) {
  let given = {};
  try { given = JSON.parse(localStorage.getItem('tessera-plugin-consent') || '{}'); } catch {}
  if (given[plugin.id] === plugin.version) return true;
  const rights = plugin.permissions.map(name => `• ${PLUGIN_RIGHTS[name] || name}`).join('\n') || '• nothing in Tessera';
  if (!await confirmDialog(`Turn on ${plugin.name} ${plugin.version}?`, `In Tessera it may:\n${rights}\n\nIt runs this program: ${(plugin.command || []).join(' ')}\n\n`
    + 'The program runs with your own Windows rights: it can use the network and read your files. Only turn it on if you trust where it came from.',
    {ok: 'Turn on'})) return false;
  try { localStorage.setItem('tessera-plugin-consent', JSON.stringify({...given, [plugin.id]: plugin.version})); } catch {}
  return true;
}
function setPlugin(id, change) {
  mutate(() => {
    config.plugins ??= {};
    const entry = config.plugins[id] ??= {enabled: false, settings: {}};
    if ('enabled' in change) entry.enabled = change.enabled;
    if (change.settings) entry.settings = {...entry.settings, ...change.settings};
  }, false);
}
$('#plugins-open').onclick = () => openPlugins().catch(showError);
$('#plugins-close').onclick = () => $('#plugins-dialog').close();
$('#backups-open').onclick = () => openBackups().catch(showError);
$('#backup-close').onclick = () => $('#backup-dialog').close();
$('#display-open').onclick = displaySettings;
$('#test-close').onclick = () => $('#test-dialog').close();
$('#iconify-search').onclick = () => iconifySearch().catch(showError);
$('#iconify-query').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); iconifySearch().catch(showError); } });


/* The agents and readings the panel's agents and status screens can show (chosen on those screens in the rail). */
const PANEL_AGENTS = [['claude', 'Claude Code'], ['codex', 'Codex'], ['zcode', 'ZCode']];
const PANEL_STATS = [['cpu_load', 'CPU load'], ['cpu_temp', 'CPU temperature'], ['ram', 'RAM'], ['disk', 'Disk'], ['gpu_load', 'GPU load'], ['gpu_temp', 'GPU temperature'], ['vram', 'Video memory'], ['net_down', 'Download speed']];

/* Connect Claude Code: the hooks that tell the agents screen what Claude is doing and let the panel answer its questions. */
async function claudeSettings() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  const now = await api('command/claude-hooks', {});
  dialog('Connect Claude Code', [
    {name: 'events', label: 'Show what Claude Code is doing (working, waiting for you, idle)', type: 'checkbox', value: now.events, note: 'Adds Tessera’s hooks to your Claude settings file. Your other hooks and settings stay as they are, and a backup of the file is kept next to it.'},
    {name: 'permission', label: 'Answer Claude’s permission questions on the panel', type: 'checkbox', value: now.permission, note: 'Allow and Deny on the agents screen decide. If the panel is not connected or nobody answers within 25 seconds, Claude shows its normal question. Restart Claude Code after changing this.'}
  ], values => {
    api('command/claude-hooks', {events: Boolean(values.events), permission: Boolean(values.permission)})
      .then(() => { toast('Saved. Restart Claude Code for the change to take effect.'); loadHooks(); }).catch(showError);
  }, 'Apply');
}
$('#claude-open').onclick = () => claudeSettings().catch(showError);

/* Getting started: a live checklist on a first run. The host keeps the flags (setup-state), so a starter deck
   still counts as new; the status poll ticks the steps. More → Getting started opens it again. */
const WELCOME_CLOSED = 'tessera-welcome-closed';  // the older browser-only flag, read once to carry it over
let setup = {welcome_done: true}, welcomeOpen = false, welcomeSnapshot = '', welcomeShown = '', pressBaseline = null, pressedLabel = '';
function setupDone(changes) { Object.assign(setup, changes); api('command/setup-done', changes).catch(showError); }
function firmwareOlder(firmware, host) {
  const a = String(firmware || '').split('.').map(Number), b = String(host || '').split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) < (b[i] || 0);
  return false;
}
/* [done, title, what to do or what happened, optional [label, action]] per step, in order. */
function welcomeSteps() {
  const d = dashboard || {}, device = d.device || {}, firmware = () => openFirmware().catch(showError);
  const older = device.connected && device.firmware && firmwareOlder(device.firmware, d.host_version);
  return [
    [!!d.running, 'Host running', d.running ? 'The USB host is running on this PC.' : 'The USB host is not running, so the panel cannot connect.',
      ['Start host', () => $('#host-toggle').click()]],
    [!!device.connected, 'Panel connected', device.connected ? `Connected${device.port ? ' on ' + device.port : ''}.` : 'Plug in the panel. A new panel needs its firmware first.',
      ['Install firmware …', firmware]],
    [!!device.connected && !older, 'Firmware up to date', !device.connected ? 'Checked once the panel is connected.'
      : older ? `The panel has ${device.firmware}; Tessera is ${d.host_version}.` : `The panel runs firmware ${device.firmware || 'that fits this version'}.`,
      device.connected && ['Update firmware …', firmware]],
    [!!setup.key_edited, 'Put an action on a key', setup.key_edited ? 'You changed a key.' : 'Click an action in the list on the right: it makes a new key on the selected empty slot or the first free one. Drop it on a key to add a step.'],
    [!!setup.key_pressed, 'Press it on the panel', setup.key_pressed ? `${pressedLabel || 'Your key'} worked.` : 'Press a key on the panel. This ticks off when the PC gets the press.']];
}
/* The first press that reaches the PC is the moment it all works: say so and light up that key. */
function notePress() {
  const last = dashboard?.device?.last_action;
  if (pressBaseline === null) { pressBaseline = last?.at || 0; return; }
  if (!last || last.at <= pressBaseline) return;
  pressBaseline = last.at;
  if (!last.ok || setup.welcome_done && !welcomeOpen || setup.key_pressed) return;
  pressedLabel = last.label || '';
  setupDone({key_pressed: true});
  toast(`✓ It works: ${pressedLabel || 'the key'} ran on this PC.`);
  if (dashboard.device.profile === profile && dashboard.device.page === page) {
    const tile = $(`#deck-grid [data-slot="${last.id}"]`);
    if (tile) { tile.classList.add('first-press'); setTimeout(() => tile.classList.remove('first-press'), 4000); }
  }
}
function renderWelcome() {
  notePress();
  if (!welcomeOpen) return;
  if (!setup.key_edited && welcomeSnapshot && JSON.stringify(config.profiles) !== welcomeSnapshot) setupDone({key_edited: true});
  const steps = welcomeSteps(), active = steps.findIndex(step => !step[0]), shown = JSON.stringify(steps.map(step => step.slice(0, 3)));
  if (shown === welcomeShown) return;  // unchanged: keep the buttons, and the focus on them
  welcomeShown = shown;
  $('#welcome-intro').textContent = active < 0 ? 'You are all set. Close this card when you like; More → Getting started brings it back.'
    : 'The keys below are a starter set. These steps get your panel working; each one ticks itself off.';
  $('#welcome-steps').replaceChildren(...steps.map(([done, title, detail, action], index) => element('li',
    {class: done ? 'done' : index === active ? 'active' : '', 'aria-current': index === active ? 'step' : null},
    element('span', {class: 'welcome-mark', 'aria-hidden': 'true', text: done ? '✓' : String(index + 1)}),
    element('div', {class: 'welcome-step-text'}, text('b', title), text('small', detail),
      !done && action ? button(action[0], action[1], 'outline') : null))));
}
async function showWelcome(force) {
  if (force !== true) {
    try { setup = await api('command/setup-state', {}); } catch { setup = {welcome_done: true}; }  // an older host: no card
    let closed = false;
    try { closed = localStorage.getItem(WELCOME_CLOSED) === '1'; } catch {}
    if (closed && !setup.welcome_done) setupDone({welcome_done: true});
  }
  welcomeOpen = force === true || !setup.welcome_done;
  $('#welcome').hidden = !welcomeOpen;
  if (!welcomeOpen) return;
  welcomeSnapshot = welcomeSnapshot || JSON.stringify(config.profiles);
  welcomeShown = '';
  renderWelcome();
  if (force === true) { $('#welcome').scrollIntoView({block: 'nearest'}); $('#welcome-close').focus(); }
}
$('#welcome-close').onclick = () => { $('#welcome').hidden = true; welcomeOpen = false; if (!setup.welcome_done) setupDone({welcome_done: true}); };
$('#welcome-open').onclick = () => showWelcome(true);
$('#welcome-template').onclick = () => openGallery();
$('#welcome-test').onclick = () => testButton(selected).catch(showError);

// Everything is defined now: start the editor.
start().then(showWelcome).catch(error=>{setSaveState('The editor could not start',error.message);startError=error.message;renderStatusBar();});

/* Page templates: a ready-made page (Meetings, Coding, Media, Browser) is shown as it will look, then added. */
let galleryChoice = 0;
function galleryTemplates() {
  return [...(actionCatalog.page_templates || []), {name: 'Empty page', description: 'Start with nothing', page: []}];
}
function showGallery(index) {
  galleryChoice = index;
  const template = galleryTemplates()[index], keys = new Map(template.page.map(key => [key.id, key]));
  $('#gallery-name').textContent = template.name;
  $('#gallery-desc').textContent = template.description;
  $('#gallery-grid').replaceChildren(...Array.from({length: 18}, (_, slot) => {
    const key = keys.get(slot + 1);
    return element('div', {class: 'gallery-key' + (key ? '' : ' empty'), style: key ? `--c:${key.color}` : ''}, key ? text('span', key.label) : '');
  }));
  const used = template.page.length;
  $('#gallery-info').textContent = used ? `${used} keys, ${18 - used} free.` : '18 free keys.';
  [...$('#gallery-list').children].forEach((item, i) => item.setAttribute('aria-selected', String(i === index)));
}
function openGallery() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  $('#gallery-list').replaceChildren(...galleryTemplates().map((template, index) =>
    element('button', {class: 'gallery-item', role: 'option', type: 'button', onclick: () => showGallery(index)}, text('strong', template.name), text('small', template.description))));
  showGallery(0);
  $('#gallery-dialog').showModal();
}
function addGalleryPage() {
  const template = galleryTemplates()[galleryChoice], pages = config.profiles[profile].pages;
  let name = template.name, suffix = 2;
  while (pages[name]) name = `${template.name} ${suffix++}`;
  mutate(() => { pages[name] = clone(template.page); page = name; selected = template.page[0]?.id || 1; });
  $('#gallery-dialog').close();
  renderAll();
  toast(`Page “${name}” was added.`);
}
$('#gallery-open').onclick = openGallery;
$('#gallery-close').onclick = () => $('#gallery-dialog').close();
$('#gallery-add').onclick = addGalleryPage;

/* The rail: the same four screens as the panel. Keys is the editor you know; the other three show what the panel
   shows, live, and let you choose what goes on them. */
const RAIL = [
  ['keys', 'Keys', '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>'],
  ['agents', 'Agents', '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2M20 14h2M15 13v2M9 13v2"/>'],
  ['mixer', 'Mixer', '<line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="2" x2="6" y1="14" y2="14"/><line x1="10" x2="14" y1="8" y2="8"/><line x1="18" x2="22" y1="16" y2="16"/>'],
  ['status', 'Status', '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>']
];
let editorView = 'keys', hooksState = null;
function panelChoice() {
  return {agents: PANEL_AGENTS.map(a => a[0]), apps: [], mic: true, stats: PANEL_STATS.map(s => s[0]), ...(config?.panel || {})};
}
function savePanel(change) {
  mutate(() => { config.panel = {...panelChoice(), ...change}; });
  renderScreen();
}
let railShown = '';
function renderRail() {
  const waiting = Object.values(dashboard.agent_states || {}).includes('waiting');
  const choice = panelChoice();
  const shortcuts = (choice.shortcuts || []).filter(s => s.type === 'actions' || config?.profiles?.[s.profile]?.pages?.[s.page]);
  const shown = JSON.stringify([waiting, editorView, choice.screens, shortcuts, packIcons.size]);  // the status poll calls this every 1.5 s
  if (shown === railShown) return;
  railShown = shown;
  $('#rail').replaceChildren(
    element('span', {class: 'rail-logo', 'aria-hidden': 'true'}),
    ...((ids => (ids.includes('keys') ? ids : ['keys', ...ids]).map(id => RAIL.find(r => r[0] === id)).filter(Boolean))(choice.screens || RAIL.map(r => r[0]))).map(([id, name, path]) => {
      const item = element('button', {class: 'rail-item' + (editorView === id ? ' on' : ''), type: 'button', title: name, 'aria-label': name, 'aria-pressed': String(editorView === id), onclick: () => setEditorView(id)});
      item.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
      if (id === 'agents' && waiting && editorView !== 'agents') item.append(element('u', {class: 'rail-dot'}));
      return item;
    }),
    ...(shortcuts.length ? [element('span', {class: 'rail-sep'})] : []),
    ...shortcuts.map(shortcut => {
      const runs = shortcut.type === 'actions';
      const label = runs ? `${shortcut.label || 'Steps'}: runs on the panel` : `${shortcut.profile} › ${shortcut.page}`;
      const item = element('button', {class: 'rail-item', type: 'button', title: label, 'aria-label': label, onclick: () => {
        if (runs) return railSettings();  // steps run from the panel; here the shortcut opens its settings
        profile = shortcut.profile; page = shortcut.page; selected = 1; editState = 0; setEditorView('keys'); renderAll();
      }}, shortcutIcon(shortcut.icon));
      return item;
    }),
    (() => {
      const add = element('button', {class: 'rail-item rail-add', type: 'button', title: 'Customize the rail: screens and page shortcuts', 'aria-label': 'Customize the rail', onclick: () => railSettings()});
      add.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="M12 5v14"/></svg>';
      return add;
    })());
}
function setEditorView(id) {
  editorView = id;
  $('#deck-view').hidden = id !== 'keys';
  $('#screens-view').hidden = id === 'keys';
  renderRail();
  if (id === 'agents') loadHooks();
  renderScreen();
}
async function loadHooks() {
  try { hooksState = await api('command/claude-hooks', {}); } catch (error) { hooksState = {error: true}; }
  if (editorView === 'agents') renderScreen();
}
const AGENT_STATE_TEXT = {working: 'Working', waiting: 'Waiting for you', idle: 'Idle'};
function renderScreen() {
  const area = $('#screens-view');
  if (editorView === 'keys') return;
  const choice = panelChoice(), vars = dashboard.variables || {}, running = dashboard.agents || {};
  const head = (title, note) => [text('h2', title), text('p', note, 'hint')];
  let body;
  if (editorView === 'agents') {
    const lanes = PANEL_AGENTS.map(([id, name]) => {
      const state = (dashboard.agent_states || {})[id] || (running[id] ? 'idle' : '');
      const used = choice.agents.includes(id);
      const box = element('input', {type: 'checkbox', 'aria-label': `Show ${name} on the panel`, onchange: event => savePanel({agents: PANEL_AGENTS.map(a => a[0]).filter(key => key === id ? event.target.checked : choice.agents.includes(key))})});
      box.checked = used;
      return element('div', {class: 'screen-card lane-' + (state || 'off')},
        element('div', {}, text('strong', name), text('small', state ? AGENT_STATE_TEXT[state] + (vars[id + '.project'] ? ' · ' + vars[id + '.project'] : '') : 'Not running')),
        element('label', {class: 'screen-check'}, box, text('span', 'Show on panel')));
    });
    const connected = hooksState && hooksState.events;
    const claude = element('div', {class: 'screen-card'},
      element('div', {}, text('strong', 'Claude Code connection'), text('small', hooksState === null ? 'Checking …' : hooksState.error ? 'Could not check' : connected ? 'Connected: the panel shows “waiting for you”' + (hooksState.permission ? ' and Allow / Deny answer permission questions.' : '.') : 'Not connected: the panel only sees working and idle.')),
      button(connected ? 'Change …' : 'Connect …', () => claudeSettings().catch(showError), 'outline'));
    body = [...head('Agents', 'What the panel’s agents screen shows. Working and idle come from the tools’ own session files.'), ...lanes, claude];
  } else if (editorView === 'mixer') {
    const faders = (dashboard.mixer || []).map(f => element('div', {class: 'screen-fader' + (f.muted ? ' muted' : '')},
      text('b', f.muted ? 'Muted' : f.level + ' %'), element('span', {class: 'fader-track'}, element('i', {style: `height:${f.level}%;background:${f.muted ? '#3a4950' : f.color}`})), text('small', f.name)));
    const apps = element('input', {type: 'text', value: choice.apps.join(', '), placeholder: 'e.g. spotify.exe, chrome.exe', 'aria-label': 'Programs in the mixer', onchange: event => {
      const list = event.target.value.split(',').map(item => item.trim()).filter(Boolean);
      if (list.length > 3 || list.some(item => !/^[A-Za-z0-9_.-]{1,35}\.exe$/.test(item))) { toast('Use up to three program names ending in .exe, like spotify.exe.'); event.target.value = choice.apps.join(', '); return; }
      savePanel({apps: list});
    }});
    const mic = element('input', {type: 'checkbox', onchange: event => savePanel({mic: event.target.checked})});
    mic.checked = choice.mic;
    body = [...head('Mixer', 'The faders on the panel’s mixer screen, as the PC has them right now.'),
      element('div', {class: 'screen-faders'}, ...(faders.length ? faders : [text('p', 'The host has not read the sound yet.', 'hint')])),
      element('div', {class: 'screen-card'}, element('div', {}, text('strong', 'Programs'), text('small', 'Up to three. Leave empty to use the ones that are playing sound.')), apps),
      element('div', {class: 'screen-card'}, element('div', {}, text('strong', 'Microphone'), text('small', 'Include a microphone fader.')), element('label', {class: 'screen-check'}, mic, text('span', 'Show'))) ];
  } else {
    const stats = dashboard.stats || {};
    const cards = PANEL_STATS.map(([id, name]) => {
      const box = element('input', {type: 'checkbox', 'aria-label': `Show ${name}`, onchange: event => savePanel({stats: PANEL_STATS.map(s => s[0]).filter(key => key === id ? event.target.checked : choice.stats.includes(key))})});
      box.checked = choice.stats.includes(id);
      return element('label', {class: 'screen-stat' + (box.checked ? '' : ' off')}, text('small', name), text('strong', stats[id] === undefined ? '--' : String(stats[id])), element('span', {class: 'screen-check'}, box, text('span', 'Show')));
    });
    body = [...head('Status', 'The readings on the panel’s status screen. Untick what you do not need.'), element('div', {class: 'screen-stats'}, ...cards)];
  }
  area.replaceChildren(element('div', {class: 'screens-inner'}, ...body));
}
/* Rail: which screens get a button, and up to three shortcuts to a page of any profile. */
const SHORTCUT_ICONS = [
  {name: 'Globe', code: 'lc:e0e8', path: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'},
  {name: 'Code', code: 'lc:e093', path: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'},
  {name: 'Video', code: 'lc:e1a5', path: '<path d="m16 13 5.2 3.5a.5.5 0 0 0 .8-.4V7.9a.5.5 0 0 0-.8-.4L16 11"/><rect x="2" y="6" width="14" height="12" rx="2"/>'},
  {name: 'Music', code: 'lc:e122', path: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'},
  {name: 'Star', code: 'lc:e176', path: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>'},
  {name: 'Bolt', code: 'lc:e1b4', path: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'},
  {name: 'Bookmark', code: 'lc:e060', path: '<path d="m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>'},
  {name: 'Folder', code: 'lc:e0d7', path: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'},
  {name: 'Home', code: 'lc:e0f5', path: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>'},
  {name: 'Grid', code: 'lc:e0ff', path: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>'}
];
$('#rail-open').onclick = railSettings;
renderRail();

/* The rail dialog: a live preview of the rail beside the screens (on/off, order) and the shortcuts (page and icon). */
const SCREEN_INFO = {keys: ['Keys', 'Your pages and keys'], agents: ['Agents', 'Claude Code, Codex and ZCode'], mixer: ['Mixer', 'Sound per program and the microphone'], status: ['Status', 'CPU, GPU, RAM, disk and network']};
let railDraft = null;
const railIcon = path => { const node = element('span', {class: 'rail-ic', 'aria-hidden': 'true'}); node.innerHTML = `<svg viewBox="0 0 24 24">${path}</svg>`; return node; };
/* A shortcut's icon: one of the quick icons, or any icon from the library. */
function shortcutIcon(code) { const quick = SHORTCUT_ICONS.find(icon => icon.code === code); return quick ? railIcon(quick.path) : iconVisual(code, 'currentColor', 'rail-ic'); }
function railTotal() { return railDraft.order.filter(id => railDraft.on.has(id)).length + railDraft.shortcuts.length; }
function railSettings() {
  document.querySelectorAll('.more-menu').forEach(menu => { menu.hidden = true; });
  const choice = panelChoice(), screens = choice.screens || RAIL.map(r => r[0]);
  railDraft = {
    order: [...new Set([...screens.filter(id => SCREEN_INFO[id]), ...RAIL.map(r => r[0])])],
    on: new Set(['keys', ...screens]),
    shortcuts: (choice.shortcuts || []).filter(s => s.type === 'actions' || config.profiles[s.profile]?.pages[s.page]).map(s => clone(s))
  };
  drawRail();
  $('#rail-dialog').showModal();
}
function drawRail() {
  const d = railDraft, total = railTotal(), over = total > 7;
  // preview: the rail as the panel draws it
  const slot = (icon, name, cls = '') => element('span', {class: 'rail-slot ' + cls}, element('span', {class: 'rail-chip' + (cls.includes('home') ? ' on' : '')}, icon), text('small', name));
  $('#rail-preview').replaceChildren(
    element('span', {class: 'rail-logo'}),
    ...d.order.filter(id => d.on.has(id)).map(id => slot(railIcon(RAIL.find(r => r[0] === id)[2]), SCREEN_INFO[id][0], id === 'keys' ? 'home' : '')),
    ...(d.shortcuts.length ? [element('span', {class: 'rail-sep'})] : []),
    ...d.shortcuts.map(s => slot(shortcutIcon(s.icon), s.type === 'actions' ? (s.label || 'Steps') : s.page, 'shortcut')),
    ...Array.from({length: Math.max(0, 7 - total)}, () => slot(element('span'), 'Free', 'free')));
  // screens
  $('#rail-screens').replaceChildren(...d.order.map((id, index) => {
    const on = d.on.has(id), [name, note] = SCREEN_INFO[id];
    const move = (delta, label) => element('button', {class: 'rail-move', type: 'button', title: label, 'aria-label': `${label}: ${name}`, disabled: index + delta < 0 || index + delta >= d.order.length, onclick: () => { [d.order[index], d.order[index + delta]] = [d.order[index + delta], d.order[index]]; drawRail(); }}, delta < 0 ? '▲' : '▼');
    const toggle = element('button', {class: 'rail-switch' + (on ? ' on' : ''), type: 'button', role: 'switch', 'aria-checked': String(on), 'aria-label': `Show ${name} on the rail`, disabled: id === 'keys', onclick: () => { on ? d.on.delete(id) : d.on.add(id); drawRail(); }});
    return element('div', {class: 'rail-row' + (on ? '' : ' off')}, railIcon(RAIL.find(r => r[0] === id)[2]), element('div', {class: 'rail-text'}, text('strong', name), text('small', id === 'keys' ? note + ' · always on' : note)), move(-1, 'Move up'), move(1, 'Move down'), toggle);
  }));
  // shortcuts: open a page, or run steps like a key; any icon from the library
  const targets = Object.entries(config.profiles).map(([profileName, item]) => element('optgroup', {label: profileName}, ...Object.keys(item.pages).map(pageName => element('option', {value: profileName + '\u0001' + pageName}, `${profileName} › ${pageName}`))));
  const sources = Object.entries(config.profiles).flatMap(([profileName, item]) => Object.entries(item.pages).flatMap(([pageName, keys]) =>
    keys.filter(key => key.actions?.length).map(key => [`${profileName}\u0001${pageName}\u0001${key.id}`, `${profileName} › ${pageName} › ${key.label || 'Key ' + key.id}`, key])));
  $('#rail-shortcuts').replaceChildren(...d.shortcuts.map((s, index) => {
    const runs = s.type === 'actions';
    const kind = element('select', {'aria-label': `Shortcut ${index + 1}: what it does`, class: 'rail-kind', onchange: event => {
      if (event.target.value === 'actions') { const [, , key] = sources[0] || []; Object.assign(s, {type: 'actions', actions: clone(key?.actions || []), label: key?.label || 'Actions'}); delete s.profile; delete s.page; }
      else { const [firstProfile] = Object.keys(config.profiles); Object.assign(s, {profile: firstProfile, page: Object.keys(config.profiles[firstProfile].pages)[0]}); delete s.type; delete s.actions; delete s.label; }
      drawRail(); }}, element('option', {value: 'page'}, 'Opens a page'), element('option', {value: 'actions'}, 'Runs steps'));
    kind.value = runs ? 'actions' : 'page';
    let what;
    if (runs) {
      const copy = element('select', {'aria-label': `Shortcut ${index + 1}: copy the steps of a key`, onchange: event => {
        const found = sources.find(([value]) => value === event.target.value);
        if (found) { s.actions = clone(found[2].actions); s.label = found[2].label || s.label; }
        drawRail(); }}, element('option', {value: ''}, 'Copy the steps of a key …'), ...sources.map(([value, name]) => element('option', {value}, name)));
      const name = element('input', {type: 'text', maxlength: '40', value: s.label || '', placeholder: 'A name for this shortcut', 'aria-label': `Shortcut ${index + 1}: name`, oninput: event => { s.label = event.target.value; $('#rail-preview').querySelectorAll('.rail-slot.shortcut small')[index].textContent = s.label || 'Steps'; }});
      what = element('div', {class: 'rail-steps'}, name, copy, text('small', s.actions?.length ? stepSummary(s.actions) : 'No steps yet: copy them from a key', 'hint'));
    } else {
      what = element('select', {'aria-label': `Shortcut ${index + 1}: page`, onchange: event => { const [p, g] = event.target.value.split('\u0001'); s.profile = p; s.page = g; drawRail(); }}, ...targets.map(group => group.cloneNode(true)));
      what.value = s.profile + '\u0001' + s.page;
    }
    const quick = SHORTCUT_ICONS.some(icon => icon.code === s.icon) ? [] : [element('button', {class: 'rail-icon-pick on', type: 'button', role: 'radio', 'aria-checked': 'true', title: 'Chosen from the library'}, iconVisual(s.icon, '#58E09B', 'rail-ic'))];
    const icons = element('div', {class: 'rail-icons', role: 'radiogroup', 'aria-label': 'Icon'}, text('span', 'Icon', 'rail-icons-label'), ...quick, ...SHORTCUT_ICONS.map(icon =>
      element('button', {class: 'rail-icon-pick' + (icon.code === s.icon ? ' on' : ''), type: 'button', role: 'radio', 'aria-checked': String(icon.code === s.icon), title: icon.name, onclick: () => { s.icon = icon.code; drawRail(); }}, railIcon(icon.path))),
      element('button', {class: 'rail-more-icons', type: 'button', onclick: () => { iconPick = id => { s.icon = id; drawRail(); }; openIcons(); }}, 'All icons …'));
    const shift = (delta, label) => element('button', {class: 'rail-move', type: 'button', title: label, 'aria-label': `${label}: shortcut ${index + 1}`, disabled: index + delta < 0 || index + delta >= d.shortcuts.length,
      onclick: () => { [d.shortcuts[index], d.shortcuts[index + delta]] = [d.shortcuts[index + delta], d.shortcuts[index]]; drawRail(); }}, delta < 0 ? '▲' : '▼');
    return element('div', {class: 'rail-short'}, element('div', {class: 'rail-short-top'}, element('span', {class: 'rail-short-number'}, String(index + 1)), kind, shift(-1, 'Move up'), shift(1, 'Move down'),
      element('button', {class: 'rail-remove', type: 'button', title: 'Remove', 'aria-label': 'Remove shortcut', onclick: () => { d.shortcuts.splice(index, 1); drawRail(); }}, '✕')), what, icons);
  }), ...(d.shortcuts.length < 3 ? [element('button', {class: 'rail-add-short', type: 'button', onclick: () => {
    const [firstProfile] = Object.keys(config.profiles), firstPage = Object.keys(config.profiles[firstProfile].pages)[0];
    d.shortcuts.push({profile: firstProfile, page: firstPage, icon: SHORTCUT_ICONS[d.shortcuts.length % SHORTCUT_ICONS.length].code}); drawRail();
  }}, '+ Add a shortcut')] : []));
  $('#rail-count').textContent = over ? `${total} buttons: the panel fits 7. Turn something off.` : `${total} of 7 places used`;
  $('#rail-count').classList.toggle('over', over);
  $('#rail-apply').disabled = over;
}
$('#rail-close').onclick = $('#rail-cancel').onclick = () => $('#rail-dialog').close();
$('#rail-apply').onclick = () => {
  const d = railDraft;
  if (d.shortcuts.some(s => s.type === 'actions' && !s.actions?.length)) { toast('A shortcut that runs steps needs steps: copy them from a key.'); return; }
  savePanel({screens: d.order.filter(id => d.on.has(id)), shortcuts: d.shortcuts.map(s => s.type === 'actions'
    ? {type: 'actions', actions: s.actions, label: (s.label || '').slice(0, 40), icon: s.icon}
    : {profile: s.profile, page: s.page, icon: s.icon})});
  renderRail();
  $('#rail-dialog').close();
  toast('The rail was updated.');
};
