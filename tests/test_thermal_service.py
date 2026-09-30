"""Privilege boundary and protocol tests, without touching host cooling."""
import json
import os
import socket
import threading
import unittest
from unittest.mock import Mock, patch

from awcfree_lib.thermals import ThermalService, ThermalError, read_message, MAX_REQUEST


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.snapshot.return_value = {"profile": "custom"}
        self.session = Mock(return_value=True)
        self.service = ThermalService(1000, self.backend, self.session)

    def test_wrong_user_denied_even_with_active_session(self):
        with self.assertRaises(ThermalError):
            self.service.dispatch(1001, {"action": "profile", "name": "quiet"})
        self.backend.set_profile.assert_not_called()

    def test_inactive_or_remote_only_session_denied(self):
        self.session.return_value = False
        with self.assertRaises(ThermalError):
            self.service.dispatch(1000, {"action": "boost", "fan": 1, "value": 100})
        self.backend.set_boost.assert_not_called()

    def test_session_is_checked_again_for_every_request(self):
        self.service.dispatch(1000, {"action": "ping"})
        self.session.return_value = False
        with self.assertRaises(ThermalError):
            self.service.dispatch(1000, {"action": "profile", "name": "quiet"})
        self.assertEqual(self.session.call_count, 2)

    def test_valid_request_uses_only_validated_arguments(self):
        data = self.service.dispatch(1000, {"action": "boost", "fan": 2, "value": 123})
        self.backend.set_boost.assert_called_once_with(2, 123)
        self.assertEqual(data, {"profile": "custom"})

    def test_rejects_paths_shell_commands_extra_keys_and_bad_types(self):
        requests = [
            {"action": "exec", "command": "id"},
            {"action": "profile", "name": "../../etc/passwd"},
            {"action": "profile", "name": ["quiet"]},
            {"action": "profile", "name": "quiet", "root": "/tmp"},
            {"action": "boost", "fan": True, "value": 50},
            {"action": "boost", "fan": 1, "value": "50"},
            {"action": "boost", "fan": 1, "value": 256},
            {"action": "boost", "fan": 1, "value": -1},
            {"action": "boost", "fan": 9, "value": 1},
            {"action": "ping", "path": "/etc/shadow"},
        ]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(ThermalError):
                self.service.dispatch(1000, request)
        self.backend.set_boost.assert_not_called()
        self.backend.set_profile.assert_not_called()

    def exchange(self, payload, uid=1000):
        client, server = socket.socketpair()
        with client, server, patch('awcfree_lib.thermals.peer_uid', return_value=uid):
            worker = threading.Thread(target=self.service.handle, args=(server,))
            worker.start()
            client.sendall(payload)
            response = read_message(client, 65536, 3)
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            return response

    def test_real_socket_request_response_and_readback(self):
        response = self.exchange(b'{"action":"profile","name":"balanced"}\n')
        self.assertTrue(response["ok"])
        self.backend.set_profile.assert_called_once_with("balanced")

    def test_malformed_request_does_not_kill_handler(self):
        for payload in (b'not json\n', b'[]\n', b'{}\n{}\n', b'x' * (MAX_REQUEST+1)):
            self.assertFalse(self.exchange(payload)["ok"])
        self.assertTrue(self.exchange(b'{"action":"ping"}\n')["ok"])

    def test_readback_error_returned_to_client(self):
        self.backend.set_profile.side_effect = ThermalError("Firmware rejected profile")
        response = self.exchange(b'{"action":"profile","name":"quiet"}\n')
        self.assertFalse(response["ok"])
        self.assertIn("Firmware rejected", response["error"])

    def test_incomplete_message_has_deadline(self):
        client, server = socket.socketpair()
        with client, server:
            client.sendall(b'{')
            with self.assertRaises((ThermalError, TimeoutError)):
                read_message(server, MAX_REQUEST, .02)

    def test_unprivileged_fake_server_rejected_by_client(self):
        from awcfree_lib.thermals import ThermalClient
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        with patch('awcfree_lib.thermals.socket.socket', return_value=connection), \
             patch('awcfree_lib.thermals.peer_uid', return_value=1000):
            with self.assertRaisesRegex(ThermalError, "not root-owned"):
                ThermalClient().request({"action": "ping"})
        connection.sendall.assert_not_called()

    def test_daemon_requires_systemd_activation(self):
        with patch.dict(os.environ, {}, clear=True), patch('os.geteuid', return_value=0):
            with self.assertRaisesRegex(ThermalError, "systemd socket"):
                self.service.serve()


if __name__ == '__main__':
    unittest.main()
