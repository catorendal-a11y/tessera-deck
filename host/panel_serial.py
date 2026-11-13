"""The USB link to the panel: identity handshake, line framing, layout and image transfer."""
from collections import OrderedDict
import hashlib
import json
import re
import threading
import time
import zlib

try:
    import serial
except ImportError:
    serial = None

BOARD_ID = 'tessera-p4'
# 1: original, 2: hold events + protocol field, 3: key colors + ambient screen, 4: cockpit screens (agents, mixer, status),
# 5: Wi-Fi (AD_WIFI_SET, AD_WIFI_CLEAR, AD_WIFI_STATUS, {"type":"wifi"} and "wifi" in get_info)
SUPPORTED_PROTOCOLS = (1, 2, 3, 4, 5)
WIFI_PROTOCOL = 5
WIFI_STATES = ('off', 'connecting', 'connected', 'failed')
WIFI_REASONS = ('no_coprocessor', 'init', 'no_ap', 'auth', 'no_ip', 'lost', 'crashed', 'storage')
WIFI_SSID_MAX = 32  # bytes of UTF-8; WIFI_SSID_MAX in main/wifi_config.h
WIFI_REPLY_SECONDS = 4
WIFI_UNSUPPORTED = 'The panel firmware does not support Wi-Fi; update it (protocol 5)'
_HEX64 = re.compile(r'[0-9A-Fa-f]{64}')
_IPV4 = re.compile(r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})', re.ASCII)
_MAC = re.compile(r'[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}')
HANDSHAKE_SECONDS = 2.5
PANEL_CACHE_BYTES = 8 * 1024 * 1024  # decoded images the panel keeps; CacheLimit in main/deck_images.cpp
OFFLINE_LAYOUT_BYTES = 8192  # what the panel keeps in flash for offline use; LAYOUT_MAX in main/main.cpp
OTA_CHUNK = 512  # image bytes per AD_OTA_DATA line; OTA_CHUNK in main/main.cpp
OTA_WINDOW = 2048  # the panel acknowledges every OTA_WINDOW bytes; OTA_ACK_BYTES in main/main.cpp
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


def check_wifi_ssid(ssid) -> None:
    """1-32 bytes of UTF-8 without control characters, as main/wifi_config.c checks it."""
    try:
        size = len(ssid.encode('utf-8'))  # a lone surrogate cannot be encoded and is refused here
    except (AttributeError, UnicodeEncodeError):
        size = 0
    if not 0 < size <= WIFI_SSID_MAX or any(ord(c) < 0x20 or ord(c) == 0x7F for c in ssid):
        raise ValueError('ssid: the network name must be 1-32 bytes of text without control characters')


def check_wifi_credentials(ssid, password) -> None:
    """The firmware's rules: ValueError('ssid: ...') or ValueError('password: ...'). No message holds the password."""
    check_wifi_ssid(ssid)
    if not isinstance(password, str):
        raise ValueError('password: the password must be text')
    if password == '' or _HEX64.fullmatch(password):
        return
    if not 8 <= len(password) <= 63 or any(not 0x20 <= ord(c) <= 0x7E for c in password):
        raise ValueError('password: use 8-63 printable ASCII characters, 64 hex digits, or none for an open network')


def wifi_line(ssid, password) -> str:
    """'AD_WIFI_SET {"ssid":...,"password":...}' in pure ASCII. Raises ValueError on the firmware's rules."""
    check_wifi_credentials(ssid, password)
    return 'AD_WIFI_SET ' + json.dumps({'ssid': ssid, 'password': password}, ensure_ascii=True, separators=(',', ':'))


def parse_wifi_status(message):
    """A {"type":"wifi"} line reduced to {state, reason?, ssid?, ip?, rssi?, mac?, cp?}; None when malformed."""
    if not isinstance(message, dict) or message.get('type') != 'wifi' or message.get('state') not in WIFI_STATES:
        return None
    result = {'state': message['state']}
    if message.get('reason') in WIFI_REASONS:
        result['reason'] = message['reason']
    try:
        check_wifi_ssid(message.get('ssid'))
        result['ssid'] = message['ssid']
    except ValueError:
        pass
    connected = result['state'] == 'connected'
    ip = message.get('ip')
    match = _IPV4.fullmatch(ip) if connected and isinstance(ip, str) else None
    if match and all(int(part) <= 255 for part in match.groups()):
        result['ip'] = ip
    rssi = message.get('rssi')
    if connected and type(rssi) is int and -127 <= rssi <= 0:
        result['rssi'] = rssi
    if isinstance(message.get('mac'), str) and _MAC.fullmatch(message['mac']):
        result['mac'] = message['mac'].upper()
    cp = message.get('cp')
    if isinstance(cp, str) and 0 < len(cp) <= 15 and cp.isascii() and cp.isprintable():
        result['cp'] = cp
    return result


def layout_payload(buttons):
    return json.dumps({'buttons': buttons}, ensure_ascii=True, separators=(',', ':'))


def layout_bytes(buttons):
    return len(layout_payload(buttons).encode())


class DeviceRejected(ValueError):
    """The port answers, but it is not a compatible Tessera panel."""
    kind = 'other'  # 'silent' (no answer), 'board' (another device) or 'protocol' (incompatible firmware)

    def __init__(self, message, kind='other'):
        super().__init__(message)
        self.kind = kind


class PanelSerial:
    """Serialized writes and byte-based framing retain split UTF-8 and newlines."""
    def __init__(self, port, log):
        if serial is None:
            raise RuntimeError('Install host/requirements.txt first')
        self.log = log
        self.write_lock = threading.RLock()
        self.rx = bytearray()
        self.cfg_done = threading.Event()
        self.cfg_reply = ''
        self.asset_done = threading.Event()
        self.asset_reply = ''
        self.wifi_done = threading.Event()  # set by the reader loop on an AD_WIFI_SET / AD_WIFI_CLEAR answer
        self.wifi_reply = ''
        self.assets_sent = OrderedDict()  # name -> decoded bytes on the panel, oldest first
        self.ser = serial.Serial()
        self.ser.port, self.ser.baudrate = port, 115200
        self.ser.timeout, self.ser.write_timeout = 0.1, 2
        self.ser.dtr = self.ser.rts = False
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
        deadline = time.monotonic() + HANDSHAKE_SECONDS
        while time.monotonic() < deadline:
            for line in self.read_lines():
                try:
                    message = json.loads(line) if line.startswith('{') else None
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get('type') == 'info':
                    self.accept(message)
                    return
        raise DeviceRejected(f'{self.ser.port} did not identify itself as a Tessera panel', 'silent')

    def accept(self, info):
        if info.get('boardId') != BOARD_ID:
            raise DeviceRejected(f'{self.ser.port} is a different device (board {info.get("boardId")!r})', 'board')
        protocol = info.get('protocol', 1)
        if type(protocol) is not int or protocol not in SUPPORTED_PROTOCOLS:
            raise DeviceRejected(f'Firmware protocol {protocol!r} is not supported (this host speaks '
                                 f'{SUPPORTED_PROTOCOLS[0]}-{SUPPORTED_PROTOCOLS[-1]}); update the firmware or the host', 'protocol')
        self.info = dict(info, protocol=protocol)

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

    def supports_wifi(self) -> bool:
        protocol = self.info.get('protocol', 1)
        return type(protocol) is int and protocol >= WIFI_PROTOCOL

    def _wifi_command(self, command, line) -> None:
        """Send `line`, wait for `command OK`; OSError with the panel's answer otherwise. The line is never logged."""
        with self.write_lock:
            self.wifi_done.clear()
            self.wifi_reply = ''
            self.send_line(line)
            if not self.wifi_done.wait(WIFI_REPLY_SECONDS):
                raise TimeoutError(f'The panel did not answer {command}')
            if self.wifi_reply != f'{command} OK':
                raise OSError(self.wifi_reply)

    def wifi_set(self, ssid, password) -> None:
        """Store the network on the panel and start a connect; the result arrives as {"type":"wifi"} lines."""
        if not self.supports_wifi():  # nothing reaches an older panel, which would not answer
            raise RuntimeError(WIFI_UNSUPPORTED)
        self._wifi_command('AD_WIFI_SET', wifi_line(ssid, password))

    def wifi_clear(self) -> None:
        """Erase the stored network on the panel and turn its Wi-Fi off."""
        if not self.supports_wifi():
            raise RuntimeError(WIFI_UNSUPPORTED)
        self._wifi_command('AD_WIFI_CLEAR', 'AD_WIFI_CLEAR')

    def wifi_status(self) -> None:
        """Ask for a {"type":"wifi"} line; the reader loop stores it."""
        if not self.supports_wifi():
            raise RuntimeError(WIFI_UNSUPPORTED)
        self.send_line('AD_WIFI_STATUS')

    def push_buttons(self, buttons):
        payload = layout_payload(buttons)
        if len(payload.encode()) > OFFLINE_LAYOUT_BYTES:
            raise ValueError('The button layout is too large')
        try:
            self.push_payload(payload)
        except TimeoutError:
            self.log('The panel did not acknowledge the button layout; sending it once more')
            self.push_payload(payload)  # the layout replaces the old one, so sending it twice is harmless

    def push_payload(self, payload):
        with self.write_lock:
            self.cfg_done.clear()
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
                if not self.asset_done.wait(15):
                    raise TimeoutError('The panel did not acknowledge the image')
                if self.asset_reply != 'AD_IMG_END OK ' + name:
                    raise ValueError(self.asset_reply)
                self.assets_sent[name] = raw[4] * raw[5] * 4 * raw[6]  # width x height x RGBA x frames
            # The panel keeps PANEL_CACHE_BYTES of decoded images and drops the oldest ones no key shows; forget
            # those here too, so they are sent again when a page needs them.
            while sum(self.assets_sent.values()) > PANEL_CACHE_BYTES:
                oldest = next((key for key in self.assets_sent if key not in shown), None)
                if oldest is None:
                    break
                del self.assets_sent[oldest]
