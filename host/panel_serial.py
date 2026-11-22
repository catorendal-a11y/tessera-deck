"""The USB link to the panel: identity handshake, line framing, layout and image transfer."""
from collections import OrderedDict
import hashlib
import json

from platform_support import load
import threading
import time
import zlib

try:
    import serial
except ImportError:
    serial = None

BOARD_IDS = ('tessera-p4', 'tessera-p4-crowpanel7', 'tessera-s3-ws7', 'tessera-s3-8048s070', 'tessera-s3-crowpanel7')
# 1: original, 2: hold events + protocol field, 3: key colors + ambient screen, 4: cockpit screens (agents, mixer, status)
SUPPORTED_PROTOCOLS = (1, 2, 3, 4)
HANDSHAKE_SECONDS = 2.5
# On Linux the kernel raises DTR and RTS when the port opens, before pyserial can lower them. The UART boards wire
# those lines to EN and IO0, so opening the port restarts the panel and it needs about 3 s to answer. Wait longer
# and ask again every second: a request sent while it boots is lost.
RESETS_ON_OPEN = load('labels').RESETS_ON_OPEN
RESET_HANDSHAKE_SECONDS = 10.0
ASK_AGAIN_SECONDS = 1.0
# It answers get_info before its boot screen has finished; a layout sent in that moment can lose bytes on the UART.
SETTLE_AFTER_RESET_SECONDS = 1.5
PANEL_CACHE_BYTES = 8 * 1024 * 1024  # what firmware without "imgCache" in get_info keeps; CacheLimit in main/deck_images.cpp
PANEL_SIZE = (1024, 600)  # what firmware without "w"/"h" in get_info has
OFFLINE_LAYOUT_BYTES = 8192  # what the panel keeps in flash for offline use; LAYOUT_MAX in main/main.cpp
OTA_CHUNK = 512  # image bytes per AD_OTA_DATA line; OTA_CHUNK in main/main.cpp
OTA_WINDOW = 2048  # the panel acknowledges every OTA_WINDOW bytes; OTA_ACK_BYTES in main/main.cpp
IMG_CHUNK = 512  # image bytes per AD_IMG_DATA line to a panel with "imgAck":1; ImgChunk in main/deck_images.cpp
IMG_WINDOW = 2048  # such a panel acknowledges every IMG_WINDOW image bytes; ImgAckBytes in main/deck_images.cpp
# Handshake "reset" reasons that mean the panel crashed or lost power rather than being restarted on purpose.
CRASH_RESETS = {'panic': 'a crash', 'int_wdt': 'a hang (interrupt watchdog)', 'task_wdt': 'a hang (task watchdog)',
                'wdt': 'a hang (watchdog)', 'brownout': 'a power dip (brownout)'}


def restart_report(previous_boot, info):
    """(log line, notice text or None) when the panel booted again since `previous_boot`; None when it did not."""
    boot = info.get('bootId')
    if previous_boot is None or boot is None or boot == previous_boot:
        return None
    reason = info.get('reset') if isinstance(info.get('reset'), str) else 'unknown'
    cause = CRASH_RESETS.get(reason)
    notice = f'The panel restarted after {cause}. It is running again.' if cause else None
    return f'Panel restarted ({reason})', notice


def layout_payload(buttons):
    return json.dumps({'buttons': buttons}, ensure_ascii=True, separators=(',', ':'))


def layout_bytes(buttons):
    return len(layout_payload(buttons).encode())


class DeviceRejected(ValueError):
    """The port answers, but it is not a compatible Tessera panel."""
    kind = 'other'  # 'silent' (no answer), 'board' (another device) or 'protocol' (incompatible firmware)

    def __init__(self, message, kind='other', info=None):
        super().__init__(message)
        self.kind = kind
        self.info = info  # the panel's get_info answer when it was a Tessera panel with another protocol


class PanelSerial:
    """Serialized writes and byte-based framing retain split UTF-8 and newlines."""
    def __init__(self, port, log, baud=None):
        if serial is None:
            raise RuntimeError('Install host/requirements.txt first')
        self.log = log
        self.write_lock = threading.RLock()
        self.rx = bytearray()
        self.cfg_done = threading.Event()
        self.cfg_reply = ''
        self.asset_done = threading.Event()
        self.asset_reply = ''
        self.assets_sent = OrderedDict()  # name -> decoded bytes on the panel, oldest first
        self.ser = serial.Serial()
        if baud is None:
            from host_runtime import port_baud
            baud = port_baud(port)
        self.ser.port, self.ser.baudrate = port, baud
        self.ser.timeout, self.ser.write_timeout = 0.1, 2
        self.ser.dtr = self.ser.rts = False  # on the UART boards these lines drive EN and IO0
        self.ser.open()
        self.info = {}
        try:
            self.verify()
        except BaseException:
            self.ser.close()
            raise

    def verify(self):
        """Ask the device who it is and check board and protocol before anything is configured.

        Key events that arrive before the answer belong to an earlier session and are discarded.
        """
        self.ser.reset_input_buffer()
        self.send_line('{"cmd":"get_info"}')
        started = time.monotonic()
        deadline = started + (max(HANDSHAKE_SECONDS, RESET_HANDSHAKE_SECONDS) if self.resets_on_open() else HANDSHAKE_SECONDS)
        asked = started
        while time.monotonic() < deadline:
            if self.resets_on_open() and time.monotonic() - asked >= ASK_AGAIN_SECONDS:
                asked = time.monotonic()
                self.send_line('{"cmd":"get_info"}')
            for line in self.read_lines():
                try:
                    message = json.loads(line) if line.startswith('{') else None
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get('type') == 'info':
                    self.accept(message)
                    if self.resets_on_open():
                        time.sleep(SETTLE_AFTER_RESET_SECONDS)
                        self.ser.reset_input_buffer()  # the boot log and the answers to the repeated questions
                    return
        raise DeviceRejected(f'{self.ser.port} did not identify itself as a Tessera panel', 'silent')

    def resets_on_open(self):
        return RESETS_ON_OPEN and str(getattr(getattr(self, 'ser', None), 'port', '')).startswith('/dev/')

    def accept(self, info):
        if info.get('boardId') not in BOARD_IDS:
            raise DeviceRejected(f'{self.ser.port} is a different device (board {info.get("boardId")!r})', 'board')
        protocol = info.get('protocol', 1)
        if type(protocol) is not int or protocol not in SUPPORTED_PROTOCOLS:
            raise DeviceRejected(f'Firmware protocol {protocol!r} is not supported (this host speaks '
                                 f'{SUPPORTED_PROTOCOLS[0]}-{SUPPORTED_PROTOCOLS[-1]}); update the firmware or the host', 'protocol', info)
        self.info = dict(info, protocol=protocol)

    @property
    def cache_bytes(self):
        value = self.info.get('imgCache')
        return value if type(value) is int and value > 0 else PANEL_CACHE_BYTES

    @property
    def screen_size(self):
        w, h = self.info.get('w'), self.info.get('h')
        return (w, h) if type(w) is int and type(h) is int and w > 0 and h > 0 else PANEL_SIZE

    def close(self):
        self.ser.close()

    def send_line(self, text):
        raw = (text + '\n').encode('utf-8')
        with self.write_lock:
            if self.ser.write(raw) != len(raw):
                raise OSError('Incomplete USB write')

    def read_lines(self):
        self.rx.extend(self.ser.read(max(1, min(self.ser.in_waiting, 4096))))
        if len(self.rx) > 32768:
            self.rx.clear()
            raise OSError('USB message too long')
        result = []
        while (end := self.rx.find(b'\n')) >= 0:
            result.append(bytes(self.rx[:end]).decode('utf-8', 'replace').strip())
            del self.rx[:end + 1]
        return result

    def expect(self, command, wanted, seconds):
        """Read until the panel answers `command`; anything but `command wanted` raises OSError with its answer.

        Only for a port no reader thread owns (the firmware installer opens its own connection).
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for line in self.read_lines():
                if line == f'{command} {wanted}':
                    return
                if line.startswith(command + ' '):
                    raise OSError(line)
        raise TimeoutError(f'The panel did not answer {command}')

    def ota_upload(self, data, progress=lambda percent: None):
        """Stream an application image into the panel's idle slot; the panel verifies it and restarts into it."""
        with self.write_lock:
            self.send_line(f'AD_OTA_BEGIN {len(data)} {hashlib.sha256(data).hexdigest()}')
            self.expect('AD_OTA_BEGIN', 'OK', 30)
            for offset in range(0, len(data), OTA_CHUNK):
                self.send_line(f'AD_OTA_DATA {offset} ' + data[offset:offset + OTA_CHUNK].hex())
                done = min(len(data), offset + OTA_CHUNK)
                if done % OTA_WINDOW == 0 or done == len(data):  # wait while the panel erases and writes flash
                    self.expect('AD_OTA_DATA', f'OK {done}', 15)
                    progress(done * 100 / len(data))
            self.send_line('AD_OTA_END')
            self.expect('AD_OTA_END', 'OK', 60)  # the panel checks the whole image before it answers

    ack_seconds = 4

    def push_buttons(self, buttons):
        payload = layout_payload(buttons)
        if len(payload.encode()) > OFFLINE_LAYOUT_BYTES:
            raise ValueError('The button layout is too large')
        try:
            self.push_payload(payload)
        except (TimeoutError, ValueError) as exc:  # lost on the way (timeout) or damaged (INVALID): same port, once more
            # An INVALID answer is a refusal and is not retried, except on the Linux UART link, where it is almost
            # always a damaged line, and failing here would close and reopen the port, which restarts the panel.
            if isinstance(exc, ValueError) and not (self.resets_on_open() and str(exc).startswith('AD_CFG_END INVALID')):
                raise
            self.log('The panel did not accept the button layout; sending it once more')
            self.push_payload(payload)  # the layout replaces the old one, so sending it twice is harmless

    def push_payload(self, payload):
        with self.write_lock:
            self.cfg_done.clear()
            self.cfg_reply = ''
            self.send_line('AD_CFG_BEGIN')
            for i in range(0, len(payload), 380):
                self.send_line('AD_CFG_DATA ' + payload[i:i+380])
            self.send_line('AD_CFG_END')
            if not self.cfg_done.wait(self.ack_seconds):
                raise TimeoutError('The panel did not acknowledge the button layout')
            if not self.cfg_reply.startswith('AD_CFG_END OK'):
                raise ValueError(self.cfg_reply)

    def feedback(self, button_id, ok, wake=True):
        # A touch proves the panel is alive. Wake the backlight as part of the
        # response so a dark display can recover without a cable reconnect.
        # wake=False while the host has the panel dimmed: lighting it then would
        # leave it lit for good, since the host only dims a panel it thinks is awake.
        if wake:
            self.send_line('AD_DISPLAY_WAKE')
        self.send_line(f'AD_FEEDBACK {"ok" if ok else "alert"} {button_id}')

    image_seconds = 15

    def supports_image_ack(self) -> bool:
        """The panel acknowledges image data as it does firmware data ("imgAck":1 in get_info)."""
        ack = self.info.get('imgAck')
        return type(ack) is int and ack >= 1

    def _image_answer(self, wanted, what) -> None:
        """Wait for the AD_IMG_* line the reader loop hands over; anything but `wanted` raises with the panel's answer."""
        if not self.asset_done.wait(self.image_seconds):
            raise TimeoutError(f'The panel did not acknowledge {what}')
        if self.asset_reply != wanted:
            raise ValueError(self.asset_reply)
        self.asset_done.clear()  # the panel says nothing more until the next window is sent
        self.asset_reply = ''

    def push_assets(self, buttons, assets):
        shown = sorted({b.get('icon', '') for b in buttons if b.get('icon', '').startswith('im:')})
        for name in shown:
            if name in self.assets_sent:
                self.assets_sent.move_to_end(name)
                continue
            raw = assets.read(name)
            with self.write_lock:
                self.asset_done.clear()
                self.asset_reply = ''
                if self.supports_image_ack():
                    # As for firmware updates, the panel answers every IMG_WINDOW bytes and the host waits for it,
                    # so the 8 KB receive buffer cannot overrun and no pauses are needed.
                    self.send_line(f'AD_IMG_BEGIN {name} {len(raw)} {zlib.crc32(raw)} ack')
                    for offset in range(0, len(raw), IMG_CHUNK):
                        self.send_line(f'AD_IMG_DATA {offset} ' + raw[offset:offset + IMG_CHUNK].hex())
                        done = min(len(raw), offset + IMG_CHUNK)
                        if done % IMG_WINDOW == 0 or done == len(raw):
                            self._image_answer(f'AD_IMG_DATA OK {done}', 'the image data')
                else:
                    self.send_line(f'AD_IMG_BEGIN {name} {len(raw)} {zlib.crc32(raw)}')
                    # USB Serial/JTAG accepts large writes, but the firmware task
                    # consumes line frames in smaller bursts. Pace image chunks so
                    # Windows cannot overrun that receive loop on detailed icons. A pause every 4 chunks (about
                    # 1.3 KB of the panel's 8 KB buffer) is 4 times faster than one per chunk; the lock is held meanwhile.
                    for number, offset in enumerate(range(0, len(raw), 160)):
                        self.send_line(f'AD_IMG_DATA {offset} ' + raw[offset:offset+160].hex())
                        if number % 4 == 3:
                            self.ser.flush()
                            time.sleep(.01)
                self.send_line('AD_IMG_END')
                self._image_answer('AD_IMG_END OK ' + name, 'the image')
                self.assets_sent[name] = raw[4] * raw[5] * 4 * raw[6]  # width x height x RGBA x frames
            # The panel keeps cache_bytes of decoded images and drops the oldest ones no key shows; forget
            # those here too, so they are sent again when a page needs them.
            while sum(self.assets_sent.values()) > self.cache_bytes:
                oldest = next((key for key in self.assets_sent if key not in shown), None)
                if oldest is None:
                    break
                del self.assets_sent[oldest]
