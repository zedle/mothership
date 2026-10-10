"""Line-delimited JSON over a Unix socket: the daemon's control channel (CLI, UI, agents).

Each line is one JSON object. Request `{"cmd": "keyboard.effect", "args": {...}}`, response
`{"ok": true, "result": ...}` or `{"ok": false, "error": "..."}`, one line each; a connection may
send several requests in turn. `ping` is answered by the server itself. A bad line gets an error
response and never takes the server down; a line over 1 MiB gets an error and the connection is
closed (the rest of that line can't be told apart from a next request).
"""
import json
import os
import socket
import socketserver
import stat
import threading

MAX_LINE = 1 << 20


def socket_path():
    d = os.environ.get("XDG_RUNTIME_DIR", "")
    if os.path.isabs(d):
        return os.path.join(d, "mothership.sock")
    return f"/tmp/mothership-{os.getuid()}.sock"


def _line(obj):
    return (json.dumps(obj) + "\n").encode()


def _error(msg):
    return {"ok": False, "error": msg}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        while True:
            try:
                raw = self.rfile.readline(MAX_LINE + 1)
            except OSError:
                return
            if not raw:
                return
            if len(raw) > MAX_LINE:
                self._send(_error(f"request too large (max {MAX_LINE} bytes)"))
                return
            if not raw.strip():
                continue
            if not self._send(self.server.mothership.dispatch(raw)):
                return

    def _send(self, obj):
        try:
            data = _line(obj)
        except (TypeError, ValueError) as e:
            data = _line(_error(f"result is not JSON-serialisable: {e}"))
        try:
            self.wfile.write(data)
            self.wfile.flush()
            return True
        except OSError:
            return False


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


class Server:
    def __init__(self, path, handler):
        self.path = path
        self.handler = handler
        self._srv = None
        self._thread = None
        self._ino = None

    def dispatch(self, raw):
        try:
            req = json.loads(raw)
        except ValueError:
            return _error("bad request")
        if not isinstance(req, dict) or not isinstance(req.get("cmd"), str):
            return _error("bad request")
        args = req.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _error("bad request")
        cmd = req["cmd"]
        if cmd == "ping":
            return {"ok": True, "result": "pong"}
        try:
            result = self.handler(cmd, args)
        except Exception as e:  # noqa: BLE001 - every failure becomes an error response
            return _error(str(e) or type(e).__name__)
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            return _error(f"result is not JSON-serialisable: {e}")
        return {"ok": True, "result": result}

    def _clear_stale(self):
        try:
            st = os.lstat(self.path)
        except FileNotFoundError:
            return
        if stat.S_ISDIR(st.st_mode):
            raise RuntimeError(f"{self.path} is a directory")
        if stat.S_ISSOCK(st.st_mode):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1.0)
            try:
                s.connect(self.path)
            except OSError:
                pass  # nobody listening: stale
            else:
                # Something accepts connections there. Whether or not it answers the ping, removing
                # its socket would orphan it, so refuse.
                try:
                    s.sendall(_line({"cmd": "ping"}))
                    s.recv(256)
                except OSError:
                    pass
                raise RuntimeError(f"already running ({self.path})")
            finally:
                s.close()
        os.unlink(self.path)

    def start(self):
        if self._srv is not None:
            raise RuntimeError("server already started")
        self._clear_stale()
        srv = _UnixServer(self.path, _Handler, bind_and_activate=False)
        old = os.umask(0o177)  # the socket is born 0600, no window with wider access
        try:
            srv.server_bind()
        except BaseException:
            srv.server_close()
            raise
        finally:
            os.umask(old)
        try:
            os.chmod(self.path, 0o600)
            self._ino = os.lstat(self.path).st_ino
            srv.server_activate()
        except BaseException:
            srv.server_close()
            self._unlink_own()
            raise
        srv.mothership = self
        self._srv = srv
        self._thread = threading.Thread(target=srv.serve_forever, name="mothership-ipc", daemon=True)
        self._thread.start()

    def _unlink_own(self):
        """Remove the socket file only if it is still the one this server bound."""
        try:
            if self._ino is not None and os.lstat(self.path).st_ino == self._ino:
                os.unlink(self.path)
        except OSError:
            pass
        self._ino = None

    def stop(self):
        srv, self._srv = self._srv, None
        if srv is None:
            return
        srv.shutdown()
        srv.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._unlink_own()


def serve(path, handler):
    """Start a Server on `path` and return it (convenience for the daemon)."""
    s = Server(path, handler)
    s.start()
    return s


def request(cmd, args=None, path=None, timeout=5.0):
    path = path or socket_path()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        try:
            s.connect(path)
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise ConnectionError(f"mothership daemon is not running ({path}): {e.strerror}") from None
        s.sendall(_line({"cmd": cmd, "args": args or {}}))
        with s.makefile("rb") as f:
            raw = f.readline(MAX_LINE + 1)
    finally:
        s.close()
    if not raw:
        raise ConnectionError(f"mothership daemon closed the connection ({path})")
    try:
        resp = json.loads(raw)
    except ValueError:
        raise RuntimeError("bad response from daemon") from None
    if not isinstance(resp, dict):
        raise RuntimeError("bad response from daemon")
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error") or "request failed")
    return resp.get("result")
