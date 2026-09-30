#!/usr/bin/python3 -I
"""Kernel thermal backend and a socket-activated, narrowly scoped root service.

GUI reads stay unprivileged. Service writes require a kernel-verified allowed UID
and an active local logind session. Paths are never supplied by clients.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import struct
import time
from pathlib import Path

HELPER = "/usr/local/libexec/awcfree-thermals"
SOCKET_PATH = "/run/awcfree-thermals.sock"
MAX_REQUEST = 1024
MAX_RESPONSE = 65536
PROFILES = frozenset({"low-power", "cool", "quiet", "balanced",
                      "balanced-performance", "performance", "custom"})


class ThermalError(Exception):
    pass


class ThermalBackend:
    def __init__(self, root: Path = Path("/sys")) -> None:
        self.root = Path(root)

    @staticmethod
    def _text(path: Path) -> str | None:
        try:
            return path.read_text().strip()
        except OSError:
            return None

    def _number(self, path: Path) -> int | None:
        value = self._text(path)
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    def profile_dir(self) -> Path | None:
        for path in sorted((self.root / "class/platform-profile").glob("*")):
            if self._text(path / "name") == "alienware-wmi":
                return path
        return None

    def hwmon_dir(self) -> Path | None:
        for path in sorted((self.root / "class/hwmon").glob("hwmon*")):
            if self._text(path / "name") == "alienware_wmi":
                return path
        return None

    def snapshot(self) -> dict:
        profile = self.profile_dir()
        hwmon = self.hwmon_dir()
        data = {"profile": None, "choices": [], "fans": [], "temperatures": [],
                "available": profile is not None or hwmon is not None}
        if profile:
            data["profile"] = self._text(profile / "profile")
            data["choices"] = [p for p in (self._text(profile / "choices") or "").split()
                               if p in PROFILES]
        if hwmon:
            for i in range(1, 5):
                if not (hwmon / f"fan{i}_input").exists():
                    continue
                data["fans"].append({
                    "id": i, "label": self._text(hwmon / f"fan{i}_label") or f"Fan {i}",
                    "rpm": self._number(hwmon / f"fan{i}_input"),
                    "boost": self._number(hwmon / f"fan{i}_boost"),
                    "controllable": (hwmon / f"fan{i}_boost").exists(),
                })
            for path in sorted(hwmon.glob("temp*_input")):
                raw = self._number(path)
                data["temperatures"].append({
                    "label": self._text(path.with_name(path.name.replace("_input", "_label")))
                             or path.stem,
                    "celsius": raw / 1000 if raw is not None else None,
                })
        return data

    @staticmethod
    def _write(path: Path, value: str) -> None:
        try:
            # Do not create a regular file when a device has disappeared.
            fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
            with os.fdopen(fd, "w") as stream:
                stream.write(value + "\n")
                stream.flush()
        except OSError as exc:
            raise ThermalError(f"Unable to apply thermal setting: {exc.strerror}") from exc

    def set_profile(self, name: str) -> None:
        path = self.profile_dir()
        choices = (self._text(path / "choices") or "").split() if path else []
        if name not in PROFILES or name not in choices:
            raise ThermalError("This thermal profile is not supported by the device")
        self._write(path / "profile", name)
        if self._text(path / "profile") != name:
            raise ThermalError("The firmware did not retain the requested thermal profile")

    def set_boost(self, fan: int, value: int) -> None:
        if not 1 <= fan <= 4 or not 0 <= value <= 255:
            raise ThermalError("Fan must be 1–4 and boost must be 0–255")
        profile = self.profile_dir()
        if profile is None or self._text(profile / "profile") != "custom":
            raise ThermalError("Select the Custom thermal profile before applying fan boost")
        path = self.hwmon_dir()
        if path is None or not (path / f"fan{fan}_boost").exists():
            raise ThermalError("Fan boost is unavailable for this fan")
        self._write(path / f"fan{fan}_boost", str(value))
        actual = self._number(path / f"fan{fan}_boost")
        if actual != value:
            raise ThermalError(f"Firmware reported boost {actual}, requested {value}; refresh to see actual settings")


def active_local_session(uid: int) -> bool:
    """Ask logind through libsystemd; fail closed if session status is unavailable."""
    try:
        lib = ctypes.CDLL("libsystemd.so.0")
        libc = ctypes.CDLL(None)
        libc.free.argtypes = [ctypes.c_void_p]
        libc.free.restype = None
        lib.sd_uid_get_sessions.argtypes = [ctypes.c_uint, ctypes.c_int,
                                           ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))]
        lib.sd_uid_get_sessions.restype = ctypes.c_int
        for name in ("sd_session_is_active", "sd_session_is_remote"):
            getattr(lib, name).argtypes = [ctypes.c_char_p]
            getattr(lib, name).restype = ctypes.c_int
        sessions = ctypes.POINTER(ctypes.c_void_p)()
        count = lib.sd_uid_get_sessions(uid, 1, ctypes.byref(sessions))
        if count < 0:
            return False
        try:
            for i in range(count):
                session = ctypes.cast(sessions[i], ctypes.c_char_p)
                if lib.sd_session_is_active(session) == 1 and lib.sd_session_is_remote(session) == 0:
                    return True
            return False
        finally:
            for i in range(count):
                libc.free(sessions[i])
            libc.free(sessions)
    except (OSError, AttributeError):
        return False


def peer_uid(connection: socket.socket) -> int:
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", credentials)[1]


def read_message(connection: socket.socket, limit: int, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ThermalError("Service request timed out")
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096, limit + 1 - len(data)))
        if not chunk:
            raise ThermalError("Incomplete service message")
        data.extend(chunk)
        if len(data) > limit:
            raise ThermalError("Service message too large")
    line, extra = bytes(data).split(b"\n", 1)
    if extra:
        raise ThermalError("Only one request is allowed per connection")
    try:
        value = json.loads(line)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ThermalError("Invalid service message") from exc
    if not isinstance(value, dict):
        raise ThermalError("Expected a request object")
    return value


class ThermalService:
    """Serial requests, kernel-verified caller identity, no executable/path arguments."""
    def __init__(self, allowed_uid: int, backend=None, session_check=active_local_session):
        self.allowed_uid = allowed_uid
        self.backend = backend or ThermalBackend()
        self.session_check = session_check

    def dispatch(self, uid: int, request: dict) -> dict:
        if uid != 0 and (uid != self.allowed_uid or not self.session_check(uid)):
            raise ThermalError("Thermal access requires the authorised user's active local session")
        action = request.get("action")
        if action in ("ping", "status") and set(request) == {"action"}:
            return {"service": "awcfree-thermals", "version": 1} if action == "ping" else self.backend.snapshot()
        if action == "profile" and set(request) == {"action", "name"}:
            name = request["name"]
            if not isinstance(name, str) or name not in PROFILES:
                raise ThermalError("Invalid thermal profile")
            self.backend.set_profile(name)
        elif action == "boost" and set(request) == {"action", "fan", "value"}:
            fan, value = request["fan"], request["value"]
            if type(fan) is not int or type(value) is not int or not 1 <= fan <= 4 or not 0 <= value <= 255:
                raise ThermalError("Invalid fan or boost value")
            self.backend.set_boost(fan, value)
        else:
            raise ThermalError("Unsupported thermal request")
        print(f"thermal change: uid={uid} action={action}", flush=True)
        return self.backend.snapshot()

    def handle(self, connection: socket.socket) -> None:
        try:
            uid = peer_uid(connection)
            if uid not in (0, self.allowed_uid):
                raise ThermalError("User is not authorised for thermal control")
            request = read_message(connection, MAX_REQUEST, 2)
            response = {"ok": True, "data": self.dispatch(uid, request)}
        except (ThermalError, OSError) as exc:
            response = {"ok": False, "error": str(exc)}
        try:
            connection.settimeout(2)
            connection.sendall(json.dumps(response).encode() + b"\n")
        except OSError:
            pass  # A disconnected client must not stop the service.

    def serve(self) -> None:
        if os.geteuid() != 0:
            raise ThermalError("The thermal service must run as root")
        if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
            raise ThermalError("Start the thermal service through its systemd socket")
        with socket.socket(fileno=3) as listener:
            if listener.family != socket.AF_UNIX or listener.getsockname() != SOCKET_PATH:
                raise ThermalError("Unexpected service socket")
            if not listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
                raise ThermalError("Service socket is not listening")
            while True:
                connection, _ = listener.accept()
                with connection:
                    self.handle(connection)


class ThermalClient:
    def __init__(self, path: str = SOCKET_PATH):
        self.path = path

    def request(self, request: dict) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(5)
                connection.connect(self.path)
                if peer_uid(connection) != 0:
                    raise ThermalError("Refusing a thermal service that is not root-owned")
                connection.sendall(json.dumps(request).encode() + b"\n")
                response = read_message(connection, MAX_RESPONSE, 5)
        except PermissionError as exc:
            raise ThermalError("Your user does not have access to the thermal service") from exc
        except OSError as exc:
            raise ThermalError("Thermal service unavailable; install or start awcfree-thermals.socket") from exc
        if response.get("ok") is not True:
            raise ThermalError(str(response.get("error", "Thermal request failed")))
        if not isinstance(response.get("data"), dict):
            raise ThermalError("Invalid response from thermal service")
        return response["data"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Alienware kernel thermal controls")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status")
    server = actions.add_parser("serve")
    server.add_argument("--uid", type=int, required=True)
    profile = actions.add_parser("profile")
    profile.add_argument("name", choices=sorted(PROFILES))
    boost = actions.add_parser("boost")
    boost.add_argument("fan", type=int, choices=range(1, 5))
    boost.add_argument("value", type=int, choices=range(256))
    args = parser.parse_args()
    backend = ThermalBackend()
    try:
        if args.action == "serve":
            if args.uid <= 0:
                raise ThermalError("Specify a non-root user ID for service access")
            ThermalService(args.uid).serve()
            return 0
        if args.action == "profile":
            backend.set_profile(args.name)
        elif args.action == "boost":
            backend.set_boost(args.fan, args.value)
        print(json.dumps(backend.snapshot()))
        return 0
    except ThermalError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
