"""The KDE Connect side that is Linux's own: kdeconnectd is reached on the session bus, and the players KDE Connect shows for a
paired device are not the PC's media session. What is asked of KDE Connect is tested in test_kdeconnect.py."""
from platform_marks import linux_only_module
linux_only_module(__name__)
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from dbus_client import Bus  # noqa: E402
from platform_linux import media, remote  # noqa: E402
from platform_linux.dbus import SessionBus  # noqa: E402


class PcMediaTests(unittest.TestCase):
    def test_the_players_of_other_devices_are_not_the_pcs_media_session(self):
        names = ['org.freedesktop.DBus', ':1.7', 'org.mpris.MediaPlayer2.spotify', 'org.mpris.MediaPlayer2.kdeconnect.mpris_abc',
                 'org.mpris.MediaPlayer2.firefox.instance_1_2']
        self.assertEqual(media.MediaReader.players(names), ['org.mpris.MediaPlayer2.spotify', 'org.mpris.MediaPlayer2.firefox.instance_1_2'])


class BusTests(unittest.TestCase):
    def test_kdeconnect_is_asked_on_the_session_bus(self):
        self.assertIsInstance(remote.client.bus, SessionBus)
        self.assertIsInstance(remote.client.bus, Bus)

    def test_no_session_bus_is_an_oserror(self):
        from unittest.mock import patch
        with patch('jeepney.io.blocking.open_dbus_connection', side_effect=KeyError('DBUS_SESSION_BUS_ADDRESS')):
            with self.assertRaisesRegex(OSError, 'no D-Bus session bus'):
                SessionBus().connect()


if __name__ == '__main__':
    unittest.main()
