"""How the host reaches KDE Connect on Windows (platform_windows/dbus.py): the D-Bus daemon that came with KDE Connect, the
address it publishes in shared memory (or the port it listens on), and the EXTERNAL sign-in with the user's SID. What is asked of
KDE Connect is tested in test_kdeconnect.py. No KDE Connect is needed: processes, memory and sockets are fakes."""
from platform_marks import windows_only_module
windows_only_module(__name__)
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from dbus_client import Bus, NotRunning  # noqa: E402
from platform_windows import dbus, remote  # noqa: E402

STORE = 'C:\\Program Files\\WindowsApps\\KDEe.V.KDEConnect_26.802.6845.0_x64__7vt06qxq7ptv8'
ADDRESS = 'tcp:host=localhost,port=54782,family=ipv4,guid=851ef421972c8afc381d114c6aff1a9e'


class AddressTests(unittest.TestCase):
    def test_the_shared_memory_name_is_the_hash_of_the_install_folder_as_libdbus_makes_it(self):
        # what KDE Connect 26.08 from the Microsoft Store published
        expected = 'DBusDaemonAddressInfo-192c3074b2ac6c201c764a7670f385c819d6a094'
        self.assertEqual(dbus.address_name(STORE), expected)
        self.assertEqual(dbus.address_name(STORE + '\\'), expected)
        self.assertEqual(dbus.address_name(STORE.upper()), expected, 'the folder counts in lower case')

    def test_the_tcp_entry_of_an_address_is_used(self):
        self.assertEqual(dbus.tcp_endpoint(ADDRESS), ('127.0.0.1', 54782))
        self.assertEqual(dbus.tcp_endpoint('nonce-tcp:host=localhost,port=1;tcp:host=127.0.0.1,port=5'), ('127.0.0.1', 5))
        self.assertIsNone(dbus.tcp_endpoint('unix:path=/run/user/1000/bus'))
        self.assertIsNone(dbus.tcp_endpoint(''))

    def test_the_published_address_comes_first(self):
        with patch.object(dbus, 'daemon_roots', return_value=[(STORE, 1704)]), \
                patch.object(dbus, 'read_shared_text', return_value=ADDRESS) as read, \
                patch.object(dbus, 'listening_port') as port:
            self.assertEqual(dbus.find_endpoint(), ('127.0.0.1', 54782))
        read.assert_called_once_with(dbus.address_name(STORE))
        port.assert_not_called()

    def test_without_the_published_address_the_daemons_port_is_used(self):
        with patch.object(dbus, 'daemon_roots', return_value=[(STORE, 1704)]), \
                patch.object(dbus, 'read_shared_text', return_value=None), \
                patch.object(dbus, 'listening_port', return_value=50123):
            self.assertEqual(dbus.find_endpoint(), ('127.0.0.1', 50123))

    def test_without_kdeconnect_running_there_is_no_bus(self):
        with patch.object(dbus, 'daemon_roots', return_value=[]):
            with self.assertRaisesRegex(NotRunning, 'not running'):  # asked again only after a long while: each look scans the processes
                dbus.find_endpoint()

    def test_a_dbus_daemon_of_another_program_is_not_kdeconnects(self):
        class Process:
            def __init__(self, pid, name, exe):
                self.pid, self.info, self._exe = pid, {'name': name}, exe

            def exe(self):
                return self._exe
        processes = [Process(1, 'dbus-daemon.exe', 'C:\\KDE\\kdenlive\\bin\\dbus-daemon.exe'),
                     Process(2, 'dbus-daemon.exe', STORE + '\\bin\\dbus-daemon.exe'),
                     Process(3, 'explorer.exe', 'C:\\Windows\\explorer.exe')]
        with patch('psutil.process_iter', return_value=processes), \
                patch('os.path.exists', side_effect=lambda path: path == STORE + '\\bin\\kdeconnectd.exe'):
            self.assertEqual(dbus.daemon_roots(), [(STORE, 2)])

    def test_a_missing_shared_memory_block_reads_as_none(self):
        self.assertIsNone(dbus.read_shared_text('DBusDaemonAddressInfo-tessera-test-does-not-exist'))


class SignInTests(unittest.TestCase):
    def pair(self):
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        client.settimeout(2)
        server.settimeout(2)
        return client, server

    def test_external_with_the_hex_of_the_sid_then_begin(self):
        client, server = self.pair()
        server.sendall(b'OK 851ef421972c8afc381d114c6aff1a9e\r\n')
        dbus.authenticate(client, 'S-1-5-21-1')
        sent = server.recv(1024)
        while not sent.endswith(b'BEGIN\r\n'):
            sent += server.recv(1024)
        self.assertEqual(sent, b'\0AUTH EXTERNAL 532d312d352d32312d31\r\nBEGIN\r\n')

    def test_a_refusal_is_an_oserror(self):
        client, server = self.pair()
        server.sendall(b'REJECTED DBUS_COOKIE_SHA1\r\n')
        with self.assertRaisesRegex(OSError, 'refused.*REJECTED'):
            dbus.authenticate(client, 'S-1-5-21-1')

    def test_a_closed_connection_is_an_oserror(self):
        client, server = self.pair()
        server.close()
        with self.assertRaises(OSError):
            dbus.authenticate(client, 'S-1-5-21-1')

    def test_the_sid_is_this_users(self):
        self.assertRegex(dbus.user_sid(), r'^S-1-\d+(-\d+)+$')


class ConnectTests(unittest.TestCase):
    def test_kdeconnect_is_asked_on_its_own_bus(self):
        self.assertIsInstance(remote.client.bus, dbus.KdeConnectBus)
        self.assertIsInstance(remote.client.bus, Bus)

    def test_a_refused_sign_in_closes_the_socket(self):
        client, server = socket.socketpair()
        self.addCleanup(server.close)
        server.sendall(b'REJECTED\r\n')
        with patch.object(dbus, 'find_endpoint', return_value=('127.0.0.1', 1)), \
                patch('socket.create_connection', return_value=client), patch.object(dbus, 'user_sid', return_value='S-1-5-21-1'):
            with self.assertRaisesRegex(OSError, 'refused'):
                dbus.KdeConnectBus(0.5).connect()
        self.assertEqual(client.fileno(), -1, 'the socket is closed')

    def test_without_kdeconnect_the_list_is_empty(self):
        remote.reset()
        self.addCleanup(remote.reset)
        with patch.object(dbus, 'daemon_roots', return_value=[]):
            self.assertEqual(remote.list_devices(), [])


if __name__ == '__main__':
    unittest.main()
