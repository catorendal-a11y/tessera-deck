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
  $('#more-menu').hidden = true;
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
  const device = info.device;
  $('#firmware-device').textContent = device.connected
    ? `Panel connected · firmware ${device.firmware || 'unknown'} · protocol ${device.protocol ?? '?'} · Tessera ${info.host || '?'}`
    : `The panel is not connected · Tessera ${info.host || '?'}`;
  $('#firmware-install').disabled = !good.length;
  if (info.job.state === 'running') pollFirmware();
}
async function installFirmware() {
  const path = $('#firmware-package').value;
  if (!path || !confirm('Write the firmware now? Do not unplug the panel until it has finished.')) return;
  try { await api('command/firmware-install', {package: path, mode: $('#firmware-mode').value, force: $('#firmware-force').checked}); }
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
    label.textContent = `Installed ${job.result.installed}${job.result.previous ? ` (was ${job.result.previous})` : ''}. The host has started again.`;
  } else if (job.state === 'failed') {
    label.textContent = job.error || 'The installation failed.';
    $('.firmware-force').hidden = !(job.error || '').includes('did not answer');
  }
  $('#firmware-install').disabled = job.state === 'running';
}
$('#firmware-open').onclick = openFirmware;
$('#firmware-close').onclick = () => $('#firmware-dialog').close();
$('#firmware-install').onclick = installFirmware;

/* Key colors: an own background, label color and outline per button (or per state of a toggle button). */
function renderStyle(panel) {
  const row = (label, key, fallback) => {
    const input = element('input', {type: 'color', value: appearance()[key] || fallback, 'aria-label': label});
    input.addEventListener('input', () => mutate(() => { appearance()[key] = input.value.toUpperCase(); }, false, editKey('style', key)));
    return element('div', {class: 'appearance-row'}, text('span', label, 'hint'), input,
      button('Default', () => mutate(() => { delete appearance()[key]; }), 'text-button'));
  };
  panel.append(element('details', {class: 'quick-icons'}, text('summary', 'Key colors'),
    row('Background', 'bg', '#172329'), row('Label text', 'text_color', '#E8F4EF'), row('Outline', 'border', '#31444D')));
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
  $('#test-dialog').showModal();
}

/* Ambient screen: a big clock (and optional weather) when the panel is idle. */
function ambientSettings() {
  $('#more-menu').hidden = true;
  const ambient = {enabled: false, after: 120, ...(config.ambient || {})}, weather = ambient.weather;
  const afterChoices = [30, 60, 120, 300, 600].map(v => [String(v), v < 60 ? `${v} seconds` : `${v / 60} min`]);
  if (!afterChoices.some(([v]) => Number(v) === ambient.after)) afterChoices.push([String(ambient.after), `${ambient.after} seconds`]);
  const where = weather ? `Currently ${weather.name} in ${weather.unit === 'fahrenheit' ? 'Fahrenheit' : 'Celsius'}. ` : '';
  dialog('Ambient screen', [
    {name: 'enabled', label: 'Show a big clock when the panel has been idle', type: 'checkbox', value: ambient.enabled, note: 'Touch the panel to get your keys back. Needs the firmware that ships with this version.'},
    {name: 'after', label: 'Show it after', options: afterChoices, value: String(ambient.after)},
    {name: 'city', label: 'Weather for (city, optional)', value: weather?.name || '', note: `${where}Weather comes from open-meteo.com every 15 minutes. Leave the city empty for no weather and no internet use.`},
    {name: 'unit', label: 'Temperature unit', options: [['celsius', 'Celsius'], ['fahrenheit', 'Fahrenheit']], value: weather?.unit || 'celsius'}
  ], values => {
    const city = values.city.trim(), keep = weather && weather.name === city;
    mutate(() => {
      config.ambient = {enabled: values.enabled, after: Number(values.after)};
      if (keep) config.ambient.weather = {...weather, unit: values.unit};
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
async function iconifySearch() {
  const query = $('#iconify-query').value.trim(), box = $('#iconify-results');
  $('#iconify-note').hidden = false;
  box.hidden = false;
  box.replaceChildren(text('p', 'Searching …', 'hint'));
  const {icons} = await api('command/iconify-search', {query});
  box.replaceChildren();
  if (!icons.length) { box.append(text('p', 'Nothing found online.', 'hint')); return; }
  const queue = [...icons];
  const load = async () => {
    while (queue.length) {
      const id = queue.shift(), item = button('', () => useOnlineIcon(id).catch(showError), 'icon-choice online', id);
      box.append(item);
      try {
        const {svg} = await api('command/iconify-svg', {id, color: '#FFFFFF'});
        item.replaceChildren(element('img', {src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, alt: id, width: '36', height: '36'}));
      } catch { item.textContent = '?'; }
    }
  };
  await Promise.all([load(), load(), load(), load()]);
}
async function useOnlineIcon(id) {
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
  $('#more-menu').hidden = true;
  const theme = config.theme || {};
  const current = Object.entries(THEMES).find(([, preset]) => preset.bg === theme.bg && preset.text_color === theme.text_color && preset.border === theme.border)?.[0] || (Object.keys(theme).length ? 'custom' : 'default');
  dialog('Key theme', [
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
  $('#more-menu').hidden = true;
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
  if (!confirm(`Replace the current configuration with the backup from ${item.saved}? The current one is kept as a backup.`)) return;
  const state = await api('command/restore-backup', {name: item.name});
  config = state.config; revision = state.revision;
  dirty = false; conflicted = false; history = []; future = [];
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
}
async function downloadFirmware() {
  const result = await api('command/update-download-firmware', {});
  toast(result.message);
  await refreshFirmware();
}
$('#firmware-check').onclick = () => checkUpdates().catch(error => { $('#firmware-latest').textContent = error.message; });
$('#firmware-download').onclick = () => downloadFirmware().catch(showError);
$('#diagnostics-export').onclick = async () => { $('#more-menu').hidden = true; try { await command('diagnostics'); } catch (error) { showError(error); } };
/* Host log: a live tail of the host's own log, like a serial monitor for the whole product. */
let logTimer = null;
async function refreshLog() {
  const view = $('#log-view'), atEnd = view.scrollHeight - view.scrollTop - view.clientHeight < 40;
  view.textContent = (await api('command/host-log', {lines: 200})).log;
  if (atEnd) view.scrollTop = view.scrollHeight;
}
async function openLog() {
  $('#more-menu').hidden = true;
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
  $('#more-menu').hidden = true;
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
    check.onchange = () => { setPlugin(plugin.id, {enabled: check.checked}); renderPlugins(); };
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
        box.append(field(spec.label || key, String(value), v => setPlugin(plugin.id, {settings: {[key]: spec.type === 'number' ? Number(v) : v}}), {type: spec.type === 'number' ? 'number' : 'text'}));
      }
    }
    list.append(box);
  }
  for (const problem of problems) list.append(text('p', problem, 'error'));
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
$('#ambient-open').onclick = ambientSettings;
$('#test-close').onclick = () => $('#test-dialog').close();
$('#iconify-search').onclick = () => iconifySearch().catch(showError);
$('#iconify-query').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); iconifySearch().catch(showError); } });

/* Panel screens: which agents, programs and readings the panel's agents, mixer and status screens show. */
const PANEL_AGENTS = [['claude', 'Claude Code'], ['codex', 'Codex'], ['zcode', 'ZCode']];
const PANEL_STATS = [['cpu_load', 'CPU load'], ['cpu_temp', 'CPU temperature'], ['ram', 'RAM'], ['disk', 'Disk'], ['gpu_load', 'GPU load'], ['gpu_temp', 'GPU temperature'], ['vram', 'Video memory'], ['net_down', 'Download speed']];
function panelSettings() {
  $('#more-menu').hidden = true;
  const panel = {agents: PANEL_AGENTS.map(a => a[0]), apps: [], mic: true, stats: PANEL_STATS.map(s => s[0]), ...(config.panel || {})};
  const fields = [
    ...PANEL_AGENTS.map(([id, name]) => ({name: 'agent_' + id, label: `Agents: ${name}`, type: 'checkbox', value: panel.agents.includes(id), note: id === 'claude' ? 'Allow and Deny on the panel answer Claude Code’s permission questions once the hook is installed (deckctl hooks claude-permission).' : ''})),
    {name: 'apps', label: 'Mixer: programs (up to 3, e.g. spotify.exe, chrome.exe)', value: panel.apps.join(', '), note: 'Leave empty to show the programs that are playing sound right now.'},
    {name: 'mic', label: 'Mixer: show the microphone', type: 'checkbox', value: panel.mic},
    ...PANEL_STATS.map(([id, name]) => ({name: 'stat_' + id, label: `Status: ${name}`, type: 'checkbox', value: panel.stats.includes(id)}))
  ];
  dialog('Panel screens', fields, values => {
    const apps = values.apps.split(',').map(item => item.trim()).filter(Boolean);
    if (apps.length > 3) throw new Error('Choose at most three programs for the mixer.');
    if (apps.some(item => !/^[A-Za-z0-9_.-]{1,35}\.exe$/.test(item))) throw new Error('Program names must end in .exe, like spotify.exe.');
    mutate(() => {
      config.panel = {
        agents: PANEL_AGENTS.map(a => a[0]).filter(id => values['agent_' + id]),
        apps, mic: Boolean(values.mic),
        stats: PANEL_STATS.map(s => s[0]).filter(id => values['stat_' + id])
      };
    });
  }, 'Apply');
}
$('#panel-open').onclick = panelSettings;

// Everything is defined now: start the editor.
start().catch(error=>{setSaveState('The editor could not start',error.message);toast(error.message);});

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
  $('#more-menu').hidden = true;
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
