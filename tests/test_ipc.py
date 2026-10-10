import json
import os
import socket
import stat
import tempfile
import unittest
from unittest import mock

from mothership import ipc


def handler(cmd, args):
    if cmd == "echo":
        return args
    if cmd == "boom":
        raise ValueError("kaboom")
    if cmd == "unserialisable":
        return object()
    raise KeyError(f"unknown command {cmd}")


class IpcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "m.sock")

    def server(self, path=None):
        s = ipc.Server(path or self.path, handler)
        s.start()
        self.addCleanup(s.stop)
        return s

    def connect(self):
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(5)
        c.connect(self.path)
        self.addCleanup(c.close)
        return c, c.makefile("rb")

    def test_round_trip_and_mode(self):
        self.server()
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(ipc.request("echo", {"a": [1, "b"]}, path=self.path), {"a": [1, "b"]})
        self.assertEqual(ipc.request("echo", path=self.path), {})

    def test_handler_exception_becomes_error(self):
        self.server()
        with self.assertRaisesRegex(RuntimeError, "kaboom"):
            ipc.request("boom", path=self.path)
        with self.assertRaisesRegex(RuntimeError, "not JSON-serialisable"):
            ipc.request("unserialisable", path=self.path)
        self.assertEqual(ipc.request("echo", {"still": "up"}, path=self.path), {"still": "up"})

    def test_ping(self):
        self.server()
        self.assertEqual(ipc.request("ping", path=self.path), "pong")

    def test_malformed_lines(self):
        self.server()
        c, f = self.connect()
        for line in (b"not json\n", b"[1,2]\n", b'{"args": {}}\n', b'{"cmd": "echo", "args": 3}\n'):
            c.sendall(line)
            self.assertEqual(json.loads(f.readline()), {"ok": False, "error": "bad request"})
        c.sendall(b'{"cmd": "ping"}\n')
        self.assertEqual(json.loads(f.readline()), {"ok": True, "result": "pong"})
        self.assertEqual(ipc.request("ping", path=self.path), "pong")

    def test_oversized_line_rejected(self):
        self.server()
        c, f = self.connect()
        try:
            c.sendall(b"x" * (ipc.MAX_LINE + 10))
        except OSError:
            pass  # the server may close before reading it all
        resp = json.loads(f.readline())
        self.assertFalse(resp["ok"])
        self.assertIn("too large", resp["error"])
        self.assertEqual(ipc.request("ping", path=self.path), "pong")

    def test_multiple_requests_on_one_connection(self):
        self.server()
        c, f = self.connect()
        c.sendall(b'{"cmd": "echo", "args": {"n": 1}}\n{"cmd": "echo", "args": {"n": 2}}\n')
        self.assertEqual(json.loads(f.readline()), {"ok": True, "result": {"n": 1}})
        self.assertEqual(json.loads(f.readline()), {"ok": True, "result": {"n": 2}})
        c.sendall(b'\n{"cmd": "boom"}\n')
        self.assertEqual(json.loads(f.readline()), {"ok": False, "error": "kaboom"})

    def test_stale_socket_file_replaced(self):
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(self.path)
        stale.close()  # file left behind, nobody listening
        self.assertTrue(os.path.exists(self.path))
        self.server()
        self.assertEqual(ipc.request("ping", path=self.path), "pong")

    def test_stale_regular_file_replaced(self):
        open(self.path, "w").close()
        self.server()
        self.assertEqual(ipc.request("ping", path=self.path), "pong")

    def test_second_server_on_live_path_raises(self):
        self.server()
        second = ipc.Server(self.path, handler)
        with self.assertRaisesRegex(RuntimeError, "already running"):
            second.start()
        self.assertEqual(ipc.request("echo", {"first": True}, path=self.path), {"first": True})

    def test_stop_unlinks_and_request_without_server(self):
        s = ipc.Server(self.path, handler)
        s.start()
        s.stop()
        self.assertFalse(os.path.exists(self.path))
        s.stop()  # idempotent
        with self.assertRaises(ConnectionError):
            ipc.request("ping", path=self.path)

    def test_request_refused_on_dead_socket(self):
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(self.path)
        stale.close()
        with self.assertRaises(ConnectionError):
            ipc.request("ping", path=self.path)

    def test_stop_leaves_a_replacement_socket_alone(self):
        s = ipc.Server(self.path, handler)
        s.start()
        os.unlink(self.path)  # someone else took the path over
        other = self.server()
        s.stop()
        self.assertEqual(ipc.request("ping", path=other.path), "pong")

    def test_socket_path_env(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1234"}):
            self.assertEqual(ipc.socket_path(), "/run/user/1234/mothership.sock")
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(ipc.socket_path(), f"/tmp/mothership-{os.getuid()}.sock")

    def test_request_default_path_from_env(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name}):
            s = ipc.serve(ipc.socket_path(), handler)
            self.addCleanup(s.stop)
            self.assertEqual(ipc.request("echo", {"x": 1}), {"x": 1})


if __name__ == "__main__":
    unittest.main()
