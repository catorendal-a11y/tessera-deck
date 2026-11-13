// Editor smoke test in a real browser: the deck renders, dialogs open and close and give the focus back,
// the tab lists answer the arrow keys, and axe finds no serious problems. CI only (editor-smoke.yml).
import {spawn} from 'node:child_process';
import {copyFileSync, mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import * as axe from '@axe-core/playwright';

const AxeBuilder = axe.AxeBuilder || axe.default?.default || axe.default;  // named or default export, CJS or ESM

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const profiles = join(mkdtempSync(join(tmpdir(), 'tessera-smoke-')), 'profiles.json');
copyFileSync(join(root, 'host/profiles.default.json'), profiles);  // the editor saves backups beside it: not in the repo
const port = process.env.EDITOR_PORT || '8765';
const editor = spawn(process.env.PYTHON || 'python', ['host/tessera_app.py', '--no-browser', '--profiles', profiles, '--port', port], {cwd: root});
editor.stderr.pipe(process.stderr);

const address = await new Promise((done, fail) => {
  let seen = '';
  const timer = setTimeout(() => fail(new Error('The editor did not start within 60 s:\n' + seen)), 60000);
  editor.stdout.on('data', chunk => {
    seen += chunk;
    const found = /^Open (http\S+)/m.exec(seen);
    if (found) { clearTimeout(timer); done(found[1]); }
  });
  editor.on('exit', code => fail(new Error(`The editor stopped (exit ${code}):\n${seen}`)));
});

const problems = [];
const check = (ok, message) => { if (!ok) problems.push(message); console.log(`${ok ? 'ok  ' : 'FAIL'} ${message}`); };
const browser = await chromium.launch();
try {
  const page = await browser.newPage({viewport: {width: 1450, height: 900}});
  page.on('pageerror', error => check(false, `no script error (${error.message})`));
  await page.goto(address);
  await page.waitForFunction(() => document.querySelectorAll('#deck-grid .deck-key').length === 18, null, {timeout: 20000});
  check(true, 'the deck renders 18 keys');
  check(await page.locator('#deck-grid .deck-key:not(.empty)').count() > 0, 'the default profile has keys on the deck');

  const focused = () => page.evaluate(() => document.activeElement?.id || document.activeElement?.textContent?.trim() || '');
  async function dialogRoundTrip(name, open, dialog, close, opener) {
    await open();
    await page.locator(`${dialog}[open]`).waitFor({timeout: 5000});
    await close();
    await page.locator(`${dialog}:not([open])`).waitFor({state: 'attached', timeout: 5000});
    await page.waitForFunction(id => document.activeElement?.id === id, opener, {timeout: 2000}).catch(() => {});
    check(await focused() === opener, `${name}: opens, closes and gives the focus back to #${opener} (focus is on “${await focused()}”)`);
  }
  await dialogRoundTrip('Keyboard shortcuts', () => page.click('#shortcuts-bar'), '#shortcuts-dialog', () => page.keyboard.press('Escape'), 'shortcuts-bar');
  await dialogRoundTrip('Program settings', () => page.click('#app-settings'), '#form-dialog', () => page.click('#form-dialog [value=cancel]'), 'app-settings');
  await dialogRoundTrip('Page settings from the Page menu', async () => { await page.click('#page-menu-toggle'); await page.click('#page-options'); },
    '#form-dialog', () => page.keyboard.press('Escape'), 'page-menu-toggle');

  // The action tabs are one Tab stop; the right arrow opens and focuses the next tab.
  const tabs = page.locator('#library-tabs [role=tab]');
  check(await page.locator('#library-tabs [role=tab][tabindex="0"]').count() === 1, 'one action tab is in the Tab order');
  await page.locator('#library-tabs [role=tab][aria-selected=true]').focus();
  const before = await tabs.evaluateAll(list => list.findIndex(tab => tab.getAttribute('aria-selected') === 'true'));
  await page.keyboard.press('ArrowRight');
  const after = await tabs.evaluateAll(list => list.findIndex(tab => tab.getAttribute('aria-selected') === 'true' && tab === document.activeElement));
  check(after === (before + 1) % await tabs.count(), 'the right arrow moves to the next action tab');

  // Contrast is listed but not enforced: changing the palette is a design decision, not a smoke test.
  const {violations} = await new AxeBuilder({page}).analyze();
  for (const v of violations.filter(item => ['serious', 'critical'].includes(item.impact))) {
    const where = v.nodes.slice(0, 3).map(node => node.target.join(' ')).join(', ');
    if (v.id === 'color-contrast') console.log(`warn ${v.id}: ${v.nodes.length} element(s), e.g. ${where}`);
    else check(false, `axe ${v.impact} ${v.id}: ${v.help} (${where})`);
  }
  check(true, `axe ran (${violations.length} rule(s) with findings in total)`);
} finally {
  await browser.close();
  editor.kill();
}
if (problems.length) { console.error(`\n${problems.length} problem(s)`); process.exit(1); }
console.log('\nThe editor smoke test passed.');
