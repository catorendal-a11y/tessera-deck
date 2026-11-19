"""What the host asks KDE Connect, the same on Windows and Linux (host/kdeconnect.py): which devices count, how a device's
player is read, how the volume and the media actions are sent, and that a daemon that is missing or silent is left alone. Also
the shared D-Bus call (host/dbus_client.py): an error reply or a timeout is an error. The D-Bus is a fake."""
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
import kdeconnect  # noqa: E402
from dbus_client import Bus, NotRunning  # noqa: E402

PHONE, LAPTOP, TABLET = 'ce7eff39_phone', 'a1b2c3_laptop', 'ffeedd_tablet'
DEVICE = {PHONE: {'name': ('s', 'OnePlus 12'), 'type': ('s', 'phone')}, LAPTOP: {'name': ('s', 'Work laptop'), 'type': ('s', 'laptop')},
          TABLET: {'name': ('s', 'Tablet'), 'type': ('s', 'tablet')}}
PLAYER = {'volume': ('i', 8), 'isPlaying': ('b', True), 'title': ('s', 'Home'), 'artist': ('s', 'Band'),
          'position': ('i', 166994), 'length': ('i', 278606)}


class FakeBus:
    """Stands in for a Bus: answers like kdeconnectd and records what was called."""

    def __init__(self, devices=(PHONE, LAPTOP, TABLET), no_remote=(TABLET,), player=None):
        self.devices, self.no_remote, self.player = list(devices), set(no_remote), player or dict(PLAYER)
        self.calls, self.fail, self.closed = [], None, 0

    def close(self):
        self.closed += 1

    def call(self, destination, path, interface, member, signature='', body=(), timeout=None):
        self.calls.append((path, interface, member, signature, body))
        if getattr(self, 'error', None):
            raise self.error
        if self.fail:
            raise OSError(self.fail)
        if member == 'devices':
            return (list(self.devices),)
        device = path.split('/')[4] if path.startswith('/modules/kdeconnect/devices/') else ''
        if member == 'loadedPlugins':
            return ([] if device in self.no_remote else ['kdeconnect_battery', 'kdeconnect_mprisremote'],)
        if member == 'GetAll' and body[0] == kdeconnect.DEVICE:
            return (DEVICE[device],)
        if member == 'GetAll' and body[0] == kdeconnect.REMOTE:
            return (self.player,)
        return ()


class Case(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]

    def use(self, **kwargs):
        self.bus = FakeBus(**kwargs)
        self.remote = kdeconnect.KdeConnect(self.bus, clock=lambda: self.now[0])
        return self.bus


class DeviceTests(Case):
    def test_only_a_device_that_offers_media_control_counts(self):
        self.use()
        self.assertEqual(self.remote.list_devices(), [{'id': PHONE, 'name': 'OnePlus 12', 'type': 'phone'},
                                                      {'id': LAPTOP, 'name': 'Work laptop', 'type': 'laptop'}])

    def test_only_reachable_paired_devices_are_asked_for(self):
        bus = self.use()
        self.remote.list_devices()
        self.assertEqual(bus.calls[0][2:], ('devices', 'bb', (True, True)))

    def test_the_list_is_kept_for_a_few_seconds(self):
        bus = self.use()
        self.remote.list_devices()
        count = len(bus.calls)
        self.now[0] += kdeconnect.LIST_SECONDS - 1
        self.remote.list_devices()
        self.assertEqual(len(bus.calls), count)
        self.now[0] += 2
        self.remote.list_devices()
        self.assertGreater(len(bus.calls), count)

    def test_without_kdeconnect_the_list_is_empty_and_the_daemon_is_left_alone_for_a_while(self):
        bus = self.use()
        bus.fail = 'org.freedesktop.DBus.Error.ServiceUnknown: no such service'
        self.assertEqual(self.remote.list_devices(), [])
        self.assertEqual(bus.closed, 0, 'the connection is the bus\'s to close (it does when it broke): a failed question leaves it')
        asked = len(bus.calls)
        self.now[0] += kdeconnect.BACK_OFF - 1
        self.assertEqual(self.remote.list_devices(), [])
        self.assertEqual(len(bus.calls), asked, 'nothing is asked during the back-off')
        bus.fail = None
        self.now[0] += 2
        self.assertEqual(len(self.remote.list_devices()), 2)

    def test_a_daemon_that_is_not_running_is_left_alone_for_longer_than_one_that_failed(self):
        bus = self.use()
        bus.error = NotRunning('KDE Connect is not running')
        self.assertEqual(self.remote.list_devices(), [])
        asked = len(bus.calls)
        self.now[0] += kdeconnect.BACK_OFF + 5  # long enough for a failure, not for an absent daemon
        self.assertEqual(self.remote.list_devices(), [])
        self.assertEqual(len(bus.calls), asked, 'nothing is asked: the daemon is not there (on Windows each look scans the processes)')
        self.now[0] += kdeconnect.ABSENT_BACK_OFF
        bus.error = None
        self.assertEqual(len(self.remote.list_devices()), 2)

    def test_reset_forgets_the_back_off(self):
        bus = self.use()
        bus.fail = 'gone'
        self.remote.list_devices()
        bus.fail = None
        self.remote.reset()
        self.assertEqual(len(self.remote.list_devices()), 2)


class ReadTests(Case):
    def test_the_selected_players_volume_state_and_title_are_read(self):
        self.use()
        self.assertEqual(self.remote.read_device(PHONE), {'volume': 8, 'playing': True, 'title': 'Home', 'artist': 'Band',
                                                           'position': 166.994, 'duration': 278.606})

    def test_a_volume_outside_the_range_is_clamped_and_a_missing_one_is_none(self):
        self.use(player={'volume': ('i', 140)})
        self.assertEqual(self.remote.read_device(PHONE)['volume'], 100)
        self.use(player={'isPlaying': ('b', False)})
        self.assertEqual(self.remote.read_device(PHONE), {'volume': None, 'playing': False, 'title': '', 'artist': '',
                                                           'position': 0.0, 'duration': 0.0})

    def test_the_mixer_and_the_variables_share_one_read_a_second(self):
        bus = self.use()
        self.remote.read_device(PHONE)
        self.remote.read_device(PHONE)
        self.assertEqual([call[2] for call in bus.calls].count('GetAll'), 1)
        self.now[0] += kdeconnect.READ_SECONDS + 0.1
        self.remote.read_device(PHONE)
        self.assertEqual([call[2] for call in bus.calls].count('GetAll'), 2)

    def test_a_device_that_fails_is_left_alone_but_the_others_are_not(self):
        bus = self.use()
        bus.fail = 'timeout'
        with self.assertRaises(OSError):
            self.remote.read_device(PHONE)
        bus.fail = None
        with self.assertRaisesRegex(OSError, 'not answering'):
            self.remote.read_device(PHONE)
        self.assertEqual(self.remote.read_device(LAPTOP)['volume'], 8)

    def test_an_error_reply_about_one_device_does_not_close_the_connection_the_others_use(self):
        bus = self.use()
        bus.fail = 'org.freedesktop.DBus.Error.UnknownObject: No such object'
        with self.assertRaises(OSError):
            self.remote.read_device(PHONE)
        self.assertEqual(bus.closed, 0, 'a bus closes itself when the connection broke; a reply is no reason to')


class WriteTests(Case):
    def test_the_volume_is_written_as_the_property_of_the_remote_object(self):
        bus = self.use()
        self.remote.write_volume(PHONE, 35)
        self.assertEqual(bus.calls[-1], (f'/modules/kdeconnect/devices/{PHONE}/mprisremote', 'org.freedesktop.DBus.Properties', 'Set',
                                         'ssv', (kdeconnect.REMOTE, 'volume', ('i', 35))))

    def test_a_volume_is_kept_between_0_and_100_and_the_next_read_asks_again(self):
        bus = self.use()
        self.remote.read_device(PHONE)
        self.remote.write_volume(PHONE, 250)
        self.assertEqual(bus.calls[-1][4][2], ('i', 100))
        self.remote.read_device(PHONE)
        self.assertEqual([call[2] for call in bus.calls].count('GetAll'), 2)

    def test_only_the_six_media_actions_are_sent(self):
        bus = self.use()
        for action in kdeconnect.ACTIONS:
            self.remote.send_action(PHONE, action)
        self.assertEqual([call[4] for call in bus.calls if call[2] == 'sendAction'], [(name,) for name in kdeconnect.ACTIONS])
        with self.assertRaises(ValueError):
            self.remote.send_action(PHONE, 'Format')


class OpenBus(Bus):
    """A Bus whose connection is given, as a platform's _open would make it."""

    def __init__(self, connection):
        super().__init__()
        self.made = connection

    def _open(self):
        return self.made


class BusTests(unittest.TestCase):
    def test_an_error_reply_is_an_error_and_not_a_result(self):
        from jeepney import MessageType
        from jeepney.low_level import Endianness, Header, HeaderFields, Message, MessageFlag

        class Connection:
            def send_and_get_reply(self, message, timeout=None):
                header = Header(Endianness.little, MessageType.error, MessageFlag(0), 1, 0, 1,
                                {HeaderFields.error_name: 'org.freedesktop.DBus.Error.UnknownObject', HeaderFields.reply_serial: 1})
                return Message(header, ('No such object',))
        with self.assertRaisesRegex(OSError, 'UnknownObject.*No such object'):
            OpenBus(Connection()).call('org.kde.kdeconnect', '/x', 'org.freedesktop.DBus.Properties', 'GetAll', 's', ('y',))

    def test_nobody_having_the_name_is_not_running_and_any_other_error_reply_is_an_oserror(self):
        from jeepney import MessageType
        from jeepney.low_level import Endianness, Header, HeaderFields, Message, MessageFlag

        def reply(name):
            class Connection:
                def send_and_get_reply(self, message, timeout=None):
                    header = Header(Endianness.little, MessageType.error, MessageFlag(0), 1, 0, 1,
                                    {HeaderFields.error_name: name, HeaderFields.reply_serial: 1})
                    return Message(header, ('nobody',))
            return OpenBus(Connection())
        for name in ('org.freedesktop.DBus.Error.ServiceUnknown', 'org.freedesktop.DBus.Error.NameHasNoOwner'):
            with self.assertRaises(NotRunning):
                reply(name).call('org.kde.kdeconnect', '/x', 'org.kde.kdeconnect.daemon', 'devices')
        with self.assertRaises(OSError) as raised:
            reply('org.freedesktop.DBus.Error.UnknownObject').call('org.kde.kdeconnect', '/x', 'org.kde.kdeconnect.device', 'm')
        self.assertNotIsInstance(raised.exception, NotRunning)

    def test_two_threads_never_use_the_connection_at_the_same_moment(self):
        class Connection:
            inside, most, closed = 0, 0, 0

            def send_and_get_reply(self, message, timeout=None):
                self.inside += 1
                self.most = max(self.most, self.inside)
                time.sleep(0.002)
                self.inside -= 1
                return type('Reply', (), {'body': ('ok',), 'header': None})()

            def close(self):
                assert self.inside == 0, 'closed while a call was running'
                self.closed += 1
        connection = Connection()
        bus = OpenBus(connection)
        errors = []

        def ask():
            try:
                for turn in range(10):
                    bus.call('org.kde.kdeconnect', '/x', 'org.kde.kdeconnect.device', 'loadedPlugins')
                    if turn == 5:
                        bus.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        threads = [threading.Thread(target=ask) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((errors, connection.most), ([], 1))

    def test_a_timeout_or_a_broken_connection_is_an_oserror_and_the_next_call_connects_again(self):
        for error, message in ((TimeoutError, 'did not answer'), (ConnectionResetError, '')):
            class Connection:
                closed = False
                fails_with = error

                def send_and_get_reply(self, message, timeout=None):
                    raise self.fails_with

                def close(self):
                    self.closed = True
            connection = Connection()
            bus = OpenBus(connection)
            with self.assertRaisesRegex(OSError, message):
                bus.call('org.kde.kdeconnect', '/x', 'org.kde.kdeconnect.device', 'loadedPlugins')
            self.assertTrue(connection.closed)
            self.assertIsNone(bus._connection)


if __name__ == '__main__':
    unittest.main()
