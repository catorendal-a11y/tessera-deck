"""Image cache benchmark: page switches with almost-disjoint icon sets while live keys change.

The real Daemon and PanelSerial drive tests/native/cache_bench, which plays the panel with the firmware's image
cache, model and UI. USB time is virtual: the bytes the host writes over --link-rate, a round trip of --ack-ms for
every answer the host waits for, and the host's own pauses between image lines. cache_bench reports "imgAck":1, so
the host waits for image acknowledgements; --old-firmware makes it answer as firmware without them, and the host
paces image lines instead. Build cache_bench first (docs/DEVELOPMENT.md), then run

    host\\.venv\\Scripts\\python.exe tests\\cache_bench.py --exe build\\native\\cache_bench.exe
"""
import argparse
import base64
import io
import json
import math
from pathlib import Path
import queue
import random
import subprocess
import sys
import tempfile
import threading
import time
import types
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageOps

import host_support  # puts host/ on the path
import panel_serial  # noqa: E402
from deck_assets import Assets  # noqa: E402

NEXT_KEY = 18  # the key that goes to the next page; the live keys sit just before it
UI_TICK = 0.040  # the panel takes up a new layout on its next UI tick: lv_timer_create(update, 40, ...) in esp/main/ui/ui.cpp
WAITED = (b'AD_IMG_DATA ', b'AD_IMG_END ', b'AD_CFG_END ')  # answers the host waits for before it sends more


def icon_png(seed, frames):
    """A 72 px picture with the detail of a program icon: a gradient tile, a ring and a dot. Frames turn them."""
    rng = random.Random(seed)
    low, high = (tuple(rng.randrange(256) for _ in range(3)) for _ in range(2))
    mask = Image.new('L', (72, 72))
    ImageDraw.Draw(mask).rounded_rectangle((2, 2, 69, 69), 16, fill=255)
    pictures = []
    for frame in range(frames):
        angle = 20 + seed * 47 + frame * 30
        ramp = Image.linear_gradient('L').rotate(angle, Image.Resampling.BICUBIC).resize((72, 72))
        picture = Image.new('RGBA', (72, 72))
        picture.paste(ImageOps.colorize(ramp.point(lambda v: v & 0xFC), low, high), mask=mask)
        draw = ImageDraw.Draw(picture)
        draw.ellipse((16, 16, 56, 56), outline=(255, 255, 255, 220), width=6)
        x, y = 36 + 20 * math.cos(math.radians(angle)), 36 + 20 * math.sin(math.radians(angle))
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=high + (255,))
        pictures.append(picture)
    out = io.BytesIO()
    pictures[0].save(out, 'PNG', save_all=frames > 1, append_images=pictures[1:], duration=100, loop=0)
    return out.getvalue()


def write_config(folder, args, frames):
    """Pages of 18 keys: the first --shared icons on every page, new ones for the rest. Returns (pages, image size)."""
    assets = Assets(folder / 'profiles.json')

    def icon(seed):
        return assets.import_image(base64.b64encode(icon_png(seed, frames)).decode())['id']

    shared = [icon(key) for key in range(1, args.shared + 1)]
    live = range(NEXT_KEY - args.live, NEXT_KEY)
    pages = {}
    for page in range(args.pages):
        keys = []
        for key in range(1, 19):
            button = {'id': key, 'label': f'Key {key}', 'icon': shared[key - 1] if key <= args.shared else icon(100 * (page + 1) + key)}
            if key == NEXT_KEY:
                button.update(label='Next', actions=[{'type': 'page', 'page': f'p{(page + 1) % args.pages + 1}'}])
            elif key in live and (key - live.start) % 2:  # the panel draws the gauge in place of an image
                button.pop('icon')
                button['gauge'] = {'key': f'counter:live{key - live.start}', 'max': 100}
            elif key in live:
                button['label'] = f'Live $(var:live{key - live.start})'
            keys.append(button)
        pages[f'p{page + 1}'] = keys
    config = {'default_profile': 'bench', 'auto_profiles': False, 'profiles': {'bench': {'match': [], 'pages': pages}}}
    (folder / 'profiles.json').write_text(json.dumps(config), encoding='utf-8')
    sizes = [path.stat().st_size for path in assets.root.glob('*.adimg')]
    return pages, sum(sizes) / len(sizes)


class Link:
    """The serial port PanelSerial opens: writes go to cache_bench, its lines come back, and it keeps the USB clock."""

    def __init__(self, process, rate, ack):
        self.process, self.rate, self.ack = process, rate, ack
        self.clock = 0.0  # seconds of USB time
        self.bytes = self.lines = 0
        self.layouts = []  # USB time at which each AD_CFG_END went out
        self.reports = queue.Queue()
        self.on_panel = set()  # images the panel stored and has not reported dropped
        self.in_waiting = 0

    def open(self):
        pass

    close = flush = reset_input_buffer = open

    def write(self, raw):
        self.process.stdin.write(raw)
        self.process.stdin.flush()
        self.bytes, self.lines, self.clock = self.bytes + len(raw), self.lines + 1, self.clock + len(raw) / self.rate
        if raw == b'AD_CFG_END\n':
            self.layouts.append(self.clock)
        return len(raw)

    def sleep(self, seconds):  # panel_serial's pauses between image lines
        self.clock += seconds

    def command(self, line):  # a line for cache_bench itself, not USB traffic
        self.process.stdin.write(line.encode() + b'\n')
        self.process.stdin.flush()

    def read(self, size=1):
        line = self.process.stdout.readline()
        if line.startswith(b'BENCH '):
            report = json.loads(line[6:])
            self.on_panel.difference_update(report.get('evicted', []))
            self.reports.put(report)
            return b''
        if line.startswith(b'AD_IMG_END OK '):
            self.on_panel.add(line.split()[2].decode())
        if line.startswith(WAITED):  # the host is blocked until it reads this, so the round trip adds to the clock
            self.clock += self.ack
        return line


class Bench:
    """One scenario. The daemon's own worker and reader loops run; this thread queues jobs and taps and waits."""

    def __init__(self, folder, process, args, pages):
        self.args, self.pages = args, pages
        self.link = Link(process, args.link_rate * 1000, args.ack_ms / 1000)
        self.daemon = host_support.test_daemon(folder / 'profiles.json')
        self.daemon.log = self.log
        self.daemon.publish_runtime = lambda *_, **__: None
        self.queue_job, self.daemon.enqueue = self.daemon.enqueue, self.enqueue  # reader_loop queues through here too
        self.answered = self.taps = self.requests = 0
        self.reports = []  # the layout reports, in order
        self.press_wait = 0.0  # USB time the next press waited behind earlier work
        self.errors = []

    def log(self, message):
        if message.startswith('Action failed'):  # what the worker and a press log when a job fails
            self.errors.append(message)
        if self.args.verbose:
            print(message, file=sys.stderr)

    def enqueue(self, job):
        self.requests += job[0] == 'image-missing'
        if job[0] == 'press':  # its time stamp says how long it waited, so the daemon drops it after 5 s as it would
            job = job[:4] + (job[4] - self.press_wait,)
        return self.queue_job(job)

    def run(self):
        fake_serial = types.SimpleNamespace(Serial=lambda: self.link)
        fake_time = types.SimpleNamespace(sleep=self.link.sleep, monotonic=time.monotonic)
        with patch.object(panel_serial, 'serial', fake_serial), patch.object(panel_serial, 'time', fake_time):
            self.panel = self.daemon.panel = panel_serial.PanelSerial('cache_bench', self.daemon.log)
            threading.Thread(target=self.daemon.reader_loop, args=(self.panel,), daemon=True).start()
            threading.Thread(target=self.daemon.worker_loop, daemon=True).start()
            try:
                return self.schedule()
            finally:
                self.daemon.stop.set()

    def schedule(self):
        self.run_job(('force-push',))  # the first page, as after a connect
        switches = [dict(self.switch(self.link.clock), warmup=True) for _ in range(self.args.pages)]  # fills the cache
        tap, live = self.args.tap_ms / 1000, self.args.live_ms / 1000
        next_tap, next_live = self.link.clock + tap, self.link.clock + live
        updates, left, n = [], (self.args.rounds - 1) * self.args.pages, 0
        while left:
            if self.args.live and live and next_live <= next_tap:  # changes that came during a switch queue behind it
                self.link.clock = max(self.link.clock, next_live)
                updates.append(dict(self.live_update(n), warmup=False))
                n, next_live = n + 1, next_live + live
            else:
                self.link.clock = max(self.link.clock, next_tap)
                switches.append(dict(self.switch(next_tap), warmup=False))
                left, next_tap = left - 1, self.link.clock + tap  # the next tap comes tap_ms after this page went out
        return switches, updates

    def run_job(self, job):
        self.daemon.enqueue(job)
        self.settle()

    def settle(self):
        """Wait until the worker is idle and cache_bench answered everything sent; its lines can queue more jobs."""
        while True:
            self.daemon.jobs.join()
            while self.answered < len(self.link.layouts) + self.taps:
                try:
                    report = self.link.reports.get(timeout=60)
                except queue.Empty:
                    raise RuntimeError('cache_bench stopped answering') from None
                self.answered += 1
                if 'tap' not in report:
                    self.reports.append(report)
            # The reader queues a job from a line before it reads the next one, and the report comes last.
            if not self.daemon.jobs.unfinished_tasks:
                return

    def mark(self):
        return {'bytes': self.link.bytes, 'lines': self.link.lines, 'layouts': len(self.link.layouts),
                'reports': len(self.reports), 'requests': self.requests, 'host': set(self.panel.assets_sent)}

    def measure(self, before):
        reports = self.reports[before['reports']:]
        return {'usb_bytes': self.link.bytes - before['bytes'], 'usb_lines': self.link.lines - before['lines'],
                'layouts': len(reports), 'paint_ms': reports[0]['paint_us'] / 1000 if reports else None,
                'evicted_host': len(before['host'] - set(self.panel.assets_sent)),
                'evicted_panel': sum(len(report['evicted']) for report in reports),
                'requests': self.requests - before['requests'], 'disagree': self.disagreement(),
                'blank_first': len(reports[0]['missing']) if reports else 0,
                'blank_after': len(reports[-1]['missing']) if reports else 0}

    def disagreement(self):
        """What the host's record of the panel's images and the panel's cache disagree on; '' when they agree."""
        host, last = self.panel.assets_sent, self.reports[-1]
        only_host, only_panel = set(host) - self.link.on_panel, self.link.on_panel - set(host)
        if only_host or only_panel or sum(host.values()) != last['bytes'] or len(host) != last['count']:
            return (f'host only {sorted(only_host)}, panel only {sorted(only_panel)}, '
                    f'host {sum(host.values())} B in {len(host)}, panel {last["bytes"]} B in {last["count"]}')
        return ''

    def switch(self, when):
        before, had, page, dropped = self.mark(), set(self.link.on_panel), self.daemon.page, self.daemon.dropped_jobs
        self.press_wait = self.link.clock - when
        self.link.command(f'BENCH_TAP {NEXT_KEY}')
        self.taps += 1
        self.settle()
        result = self.measure(before)
        needed = {button['icon'] for button in self.pages[self.daemon.page] if button.get('icon', '').startswith('im:')}
        result.update(page=self.daemon.page, switched=self.daemon.page != page, needed=len(needed), had=len(needed & had),
                      waited_ms=self.press_wait * 1000, stale=self.daemon.dropped_jobs - dropped)
        if result['switched']:
            drawn = math.ceil(self.link.layouts[before['layouts']] / UI_TICK) * UI_TICK
            result['tap_to_paint_ms'] = (drawn - when) * 1000 + result['paint_ms']
        elif not result['stale']:
            self.errors.append(f'a tap on {page} did not change the page')
        return result

    def live_update(self, n):
        before, index = self.mark(), n % self.args.live
        if index % 2:
            self.run_job(('actions', [{'type': 'counter', 'name': f'live{index}', 'op': 'set', 'value': n % 101}]))
        else:
            self.run_job(('var', f'live{index}', str(n)))
        return self.measure(before)


def percentile(values, share):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)] if ordered else 0.0


def summary(name, frames, image_size, switches, updates, errors):
    moved = [s for s in switches if s['switched'] and not s['warmup']]
    live = [u for u in updates if not u['warmup']]
    latency, paint = [s['tap_to_paint_ms'] for s in moved], [s['paint_ms'] for s in moved]

    def mean(key, items):
        return sum(item[key] for item in items) / len(items) if items else 0.0

    everything = switches + updates
    return {
        'scenario': name, 'frames': frames, 'image_kb': image_size / 1000, 'switches': len(moved),
        'taps_dropped': sum(s['stale'] for s in switches if not s['warmup']),
        'hit_rate': sum(s['had'] for s in moved) / max(1, sum(s['needed'] for s in moved)),
        'evicted_host': mean('evicted_host', moved), 'evicted_panel': mean('evicted_panel', moved),
        'usb_kb': mean('usb_bytes', moved) / 1000, 'usb_lines': mean('usb_lines', moved),
        'tap_p50_ms': percentile(latency, .5), 'tap_p95_ms': percentile(latency, .95), 'tap_max_ms': max(latency, default=0.0),
        'paint_p50_ms': percentile(paint, .5), 'paint_max_ms': max(paint, default=0.0),
        'live_updates': len(live), 'live_kb': mean('usb_bytes', live) / 1000,
        'live_paint_p50_ms': percentile([u['paint_ms'] for u in live if u['paint_ms'] is not None], .5),
        'blank_first': sum(s['blank_first'] for s in switches), 'blank_after': sum(s['blank_after'] for s in switches),
        'requests': sum(item['requests'] for item in everything),
        'disagreements': sum(bool(item['disagree']) for item in everything), 'errors': errors,
        'raw': {'switches': switches, 'live': updates},
    }


ROWS = (
    ('frames per icon', 'frames', '{}'), ('image size, kB (ADI1)', 'image_kb', '{:.1f}'),
    ('measured switches', 'switches', '{}'), ('taps dropped (waited > 5 s)', 'taps_dropped', '{}'),
    ('hit rate', 'hit_rate', '{:.0%}'), ('evictions/switch, host record', 'evicted_host', '{:.1f}'),
    ('evictions/switch, panel cache', 'evicted_panel', '{:.1f}'), ('USB kB/switch', 'usb_kb', '{:.1f}'),
    ('USB lines/switch', 'usb_lines', '{:.0f}'), ('tap-to-paint p50, ms', 'tap_p50_ms', '{:.0f}'),
    ('tap-to-paint p95, ms', 'tap_p95_ms', '{:.0f}'), ('tap-to-paint max, ms', 'tap_max_ms', '{:.0f}'),
    ('paint p50, ms (PC)', 'paint_p50_ms', '{:.1f}'), ('paint max, ms (PC)', 'paint_max_ms', '{:.1f}'),
    ('live updates', 'live_updates', '{}'), ('USB kB/live update', 'live_kb', '{:.1f}'),
    ('live paint p50, ms (PC)', 'live_paint_p50_ms', '{:.2f}'),
    ('blank keys at first paint*', 'blank_first', '{}'), ('blank keys after a switch*', 'blank_after', '{}'),
    ('image re-requests*', 'requests', '{}'), ('host/panel disagreements*', 'disagreements', '{}'),
)


def print_table(results, args):
    print(f'{args.pages} pages, {args.shared} shared icons, {args.live} live keys, a tap {args.tap_ms} ms after each switch, '
          f'a live change every {args.live_ms} ms, link {args.link_rate:g} kB/s, {args.ack_ms:g} ms per answer the host '
          f'waits for; a first, untimed lap fills the cache.')
    print('Old firmware: the host pauses 10 ms after every 4 image lines of 160 bytes.' if args.old_firmware else
          'The panel acknowledges image data every 2 KB ("imgAck":1) and the host sends lines of 512 bytes.')
    print(f'{"":32}' + ''.join(f'{result["scenario"]:>12}' for result in results))
    for label, key, form in ROWS:
        print(f'{label:32}' + ''.join(f'{form.format(result[key]):>12}' for result in results))
    print('* counted over the first lap too. Tap-to-paint is USB time, the wait for the panel\'s next 40 ms UI tick and '
          'the paint time on this PC; the 0-20 ms the panel takes to send a press is not in it.')
    for result in results:
        for error in result['errors']:
            print(f'{result["scenario"]}: {error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--exe', required=True, type=Path, help='cache_bench.exe from the native build')
    parser.add_argument('--pages', type=int, default=4)
    parser.add_argument('--shared', type=int, default=2, help='icons every page shows (default 2)')
    parser.add_argument('--live', type=int, default=3, help='keys whose label or gauge follows a variable (default 3)')
    parser.add_argument('--frames', type=int, nargs='+', default=[1, 12], help='frames per icon, one scenario each')
    parser.add_argument('--rounds', type=int, default=4, help='laps through the pages; the first fills the cache and is not timed')
    parser.add_argument('--tap-ms', type=int, default=1500, help='time from one switch to the next tap (default 1500)')
    parser.add_argument('--live-ms', type=int, default=500)
    # Full-speed USB carries about 1 MB/s at best; 500 kB/s is a guess for the panel's USB Serial/JTAG link until it
    # is measured. With --old-firmware the host's 10 ms pause after every 4 image lines limits images to 64 kB/s anyway.
    parser.add_argument('--link-rate', type=float, default=500, help='USB link rate in kB/s (default 500)')
    # Also a guess: one 1 ms full-speed USB frame for the last line to reach the panel and one for its answer.
    parser.add_argument('--ack-ms', type=float, default=2, help='round trip for each answer the host waits for (default 2)')
    parser.add_argument('--old-firmware', action='store_true', help='cache_bench answers without "imgAck":1, as older firmware does')
    parser.add_argument('--json', action='store_true', help='print the raw numbers as JSON')
    parser.add_argument('--check', action='store_true', help='exit 1 when a key stays blank, host and panel disagree, the host reports an error or every tap was dropped')
    parser.add_argument('--verbose', action='store_true', help="print the host's log")
    args = parser.parse_args()
    if args.pages < 2 or args.rounds < 2 or not 0 <= args.shared <= 17 - args.live or args.live < 0:
        parser.error('use at least 2 pages and 2 rounds, and at most 17 shared and live keys together')
    if any(not 1 <= frames <= 12 for frames in args.frames):
        parser.error('icons have 1-12 frames')
    results = []
    for frames in args.frames:
        with tempfile.TemporaryDirectory(prefix='tessera-bench-') as folder:
            pages, image_size = write_config(Path(folder), args, frames)
            process = subprocess.Popen([str(args.exe)] + ['--old-firmware'] * args.old_firmware,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                bench = Bench(Path(folder), process, args, pages)
                switches, updates = bench.run()
            finally:
                process.stdin.close()
                process.wait(10)
            name = 'static' if frames == 1 else f'{frames} frames'
            results.append(summary(name, frames, image_size, switches, updates, bench.errors))
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        print_table(results, args)
    failed = any(r['errors'] or r['blank_after'] or r['disagreements'] or not r['switches'] for r in results)
    return 1 if args.check and failed else 0


if __name__ == '__main__':
    sys.exit(main())
