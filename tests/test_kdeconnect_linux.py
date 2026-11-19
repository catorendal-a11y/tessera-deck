"""The KDE Connect side on Linux (platform_linux/remote.py): which devices count, how a device's player is read, how the volume
and the media actions are sent, and that a daemon that is missing or silent is left alone. The D-Bus is a fake."""
from platform_marks import linux_only_module
linux_only_module(__name__)
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from platform_linux import media, remote  # noqa: E402
from platform_linux.dbus import SessionBus  # noqa: E402

PHONE, LAPTOP, TABLET = 'ce7eff39_phone', 'a1b2c3_laptop', 'ffeedd_tablet'
DEVICE = {PHONE: {'name': ('s', 'OnePlus 12'), 'type': ('s', 'phone')}, LAPTOP: {'name': ('s', 'Work laptop'), 'type': ('s', 'laptop')},
          TABLET: {'name': ('s', 'Tablet'), 'type': ('s', 'tablet')}}
PLAYER = {'volume': ('i', 8), 'isPlaying': ('b', True), 'title': ('s', 'Home'), 'artist': ('s', 'Band'),
          'position': ('i', 166994), 'length': ('i', 278606)}


class FakeBus:
    """Stands in for SessionBus: answers like kdeconnectd and records what was called."""

    def __init__(self, devices=(PHONE, LAPTOP, TABLET), no_remote=(TABLET,), player=None):
        self.devices, self.no_remote, self.player = list(devices), set(no_remote), player or dict(PLAYER)
        self.calls, self.fail = [], None

    def close(self):
        pass

    def call(self, destination, path, interface, member, signature='', body=(), timeout=None):
        self.calls.append((path, interface, member, signature, body))
        if self.fail:
            raise OSError(self.fail)
        if member == 'devices':
            return (list(self.devices),)
        device = path.split('/')[4] if path.startswith('/modules/kdeconnect/devices/') else ''
        if member == 'loadedPlugins':
            return ([] if device in self.no_remote else ['kdeconnect_battery', 'kdeconnect_mprisremote'],)
        if member == 'GetAll' and body[0] == remote.DEVICE:
            return (DEVICE[device],)
        if member == 'GetAll' and body[0] == remote.REMOTE:
            return (self.player,)
        return ()


class Case(unittest.TestCase):
    def setUp(self):
        remote.reset()
        self.now = [100.0]
        self.addCleanup(remote.reset)
        patcher = patch.object(remote, '_clock', side_effect=lambda: self.now[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def use(self, **kwargs):
        bus = FakeBus(**kwargs)
        patcher = patch.object(remote, '_bus', bus)
        patcher.start()
        self.addCleanup(patcher.stop)
        return bus


class DeviceTests(Case):
    def test_only_a_device_that_offers_media_control_counts(self):
        self.use()
        self.assertEqual(remote.list_devices(), [{'id': PHONE, 'name': 'OnePlus 12', 'type': 'phone'},
                                                 {'id': LAPTOP, 'name': 'Work laptop', 'type': 'laptop'}])

    def test_only_reachable_paired_devices_are_asked_for(self):
        bus = self.use()
        remote.list_devices()
        self.assertEqual(bus.calls[0][2:], ('devices', 'bb', (True, True)))

    def test_the_list_is_kept_for_a_few_seconds(self):
        bus = self.use()
        remote.list_devices()
        count = len(bus.calls)
        self.now[0] += remote.LIST_SECONDS - 1
        remote.list_devices()
        self.assertEqual(len(bus.calls), count)
        self.now[0] += 2
        remote.list_devices()
        self.assertGreater(len(bus.calls), count)

    def test_without_kdeconnect_the_list_is_empty_and_the_daemon_is_left_alone_for_a_while(self):
        bus = self.use()
        bus.fail = 'org.freedesktop.DBus.Error.ServiceUnknown: no such service'
        self.assertEqual(remote.list_devices(), [])
        asked = len(bus.calls)
        self.now[0] += remote.BACK_OFF - 1
        self.assertEqual(remote.list_devices(), [])
        self.assertEqual(len(bus.calls), asked, 'nothing is asked during the back-off')
        bus.fail = None
        self.now[0] += 2
        self.assertEqual(len(remote.list_devices()), 2)


class ReadTests(Case):
    def test_the_selected_players_volume_state_and_title_are_read(self):
        self.use()
        self.assertEqual(remote.read_device(PHONE), {'volume': 8, 'playing': True, 'title': 'Home', 'artist': 'Band',
                                                      'position': 166.994, 'duration': 278.606})

    def test_a_volume_outside_the_range_is_clamped_and_a_missing_one_is_none(self):
        self.use(player={'volume': ('i', 140)})
        self.assertEqual(remote.read_device(PHONE)['volume'], 100)
        remote.reset()
        self.use(player={'isPlaying': ('b', False)})
        self.assertEqual(remote.read_device(PHONE), {'volume': None, 'playing': False, 'title': '', 'artist': '', 'position': 0.0,
                                                      'duration': 0.0})

    def test_the_mixer_and_the_variables_share_one_read_a_second(self):
        bus = self.use()
        remote.read_device(PHONE)
        remote.read_device(PHONE)
        self.assertEqual([call[2] for call in bus.calls].count('GetAll'), 1)
        self.now[0] += remote.READ_SECONDS + 0.1
        remote.read_device(PHONE)
        self.assertEqual([call[2] for call in bus.calls].count('GetAll'), 2)

    def test_a_device_that_fails_is_left_alone_but_the_others_are_not(self):
        bus = self.use()
        bus.fail = 'timeout'
        with self.assertRaises(OSError):
            remote.read_device(PHONE)
        bus.fail = None
        with self.assertRaisesRegex(OSError, 'not answering'):
            remote.read_device(PHONE)
        self.assertEqual(remote.read_device(LAPTOP)['volume'], 8)


class WriteTests(Case):
    def test_the_volume_is_written_as_the_property_of_the_remote_object(self):
        bus = self.use()
        remote.write_volume(PHONE, 35)
        self.assertEqual(bus.calls[-1], (f'/modules/kdeconnect/devices/{PHONE}/mprisremote', 'org.freedesktop.DBus.Properties', 'Set',
                                         'ssv', (remote.REMOTE, 'volume', ('i', 35))))

    def test_a_volume_is_kept_between_0_and_100_and_the_next_read_asks_again(self):
        bus = self.use()
        remote.read_device(PHONE)
        remote.write_volume(PHONE, 250)
        self.assertEqual(bus.calls[-1][4][2], ('i', 100))
        remote.read_device(PHONE)
        self.assertEqual([call[2] for call in bus.calls].count('GetAll'), 2)

    def test_only_the_six_media_actions_are_sent(self):
        bus = self.use()
        for action in remote.ACTIONS:
            remote.send_action(PHONE, action)
        self.assertEqual([call[4] for call in bus.calls if call[2] == 'sendAction'], [(name,) for name in remote.ACTIONS])
        with self.assertRaises(ValueError):
            remote.send_action(PHONE, 'Format')


class PcMediaTests(unittest.TestCase):
    def test_the_players_of_other_devices_are_not_the_pcs_media_session(self):
        names = ['org.freedesktop.DBus', ':1.7', 'org.mpris.MediaPlayer2.spotify', 'org.mpris.MediaPlayer2.kdeconnect.mpris_abc',
                 'org.mpris.MediaPlayer2.firefox.instance_1_2']
        self.assertEqual(media.MediaReader.players(names), ['org.mpris.MediaPlayer2.spotify', 'org.mpris.MediaPlayer2.firefox.instance_1_2'])


class BusTests(unittest.TestCase):
    def test_an_error_reply_is_an_error_and_not_a_result(self):
        from jeepney import MessageType
        from jeepney.low_level import Endianness, Header, HeaderFields, Message, MessageFlag

        class Connection:
            def send_and_get_reply(self, message, timeout=None):
                header = Header(Endianness.little, MessageType.error, MessageFlag(0), 1, 0, 1,
                                {HeaderFields.error_name: 'org.freedesktop.DBus.Error.UnknownObject', HeaderFields.reply_serial: 1})
                return Message(header, ('No such object',))
        bus = SessionBus()
        bus._connection = Connection()
        with self.assertRaisesRegex(OSError, 'UnknownObject.*No such object'):
            bus.call('org.kde.kdeconnect', '/x', 'org.freedesktop.DBus.Properties', 'GetAll', 's', ('y',))

    def test_a_timeout_is_an_oserror_and_the_connection_is_opened_again_next_time(self):
        class Connection:
            closed = False

            def send_and_get_reply(self, message, timeout=None):
                raise TimeoutError

            def close(self):
                self.closed = True
        connection = Connection()
        bus = SessionBus()
        bus._connection = connection
        with self.assertRaisesRegex(OSError, 'did not answer'):
            bus.call('org.kde.kdeconnect', '/x', 'org.kde.kdeconnect.device', 'loadedPlugins')
        self.assertTrue(connection.closed)
        self.assertIsNone(bus._connection)


if __name__ == '__main__':
    unittest.main()
