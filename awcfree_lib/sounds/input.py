"""Read-only keyboard input: evdev on Wayland, or XInput raw events on X11."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import struct

from PyQt6.QtCore import QObject, QProcess, QSocketNotifier, QTimer, pyqtSignal

INPUT_EVENT = struct.Struct("@llHHi")
KEY_NAMES = {1: "ESC", 14: "BACKSPACE", 15: "TAB", 28: "ENTER", 29: "LCTRL",
             42: "LSHIFT", 54: "RSHIFT", 56: "LALT", 57: "SPACE", 58: "CAPSLOCK",
             96: "KPENTER", 97: "RCTRL", 100: "RALT", 103: "UP", 105: "LEFT",
             106: "RIGHT", 108: "DOWN", 111: "DELETE", 125: "WIN", 126: "META"}
for first, labels in ((2, "1234567890-="), (16, "QWERTYUIOP[]"),
                      (30, "ASDFGHJKL;'`"), (43, "\\ZXCVBNM,./")):
    KEY_NAMES.update({first + i: label for i, label in enumerate(labels)})
KEY_NAMES.update({59 + i: f"F{i + 1}" for i in range(10)})
KEY_NAMES.update({87: "F11", 88: "F12"})


def key_name(code):
    return KEY_NAMES.get(code, f"KEY_{code}")


def sound_press(name):
    """Only sound categories leave the background listener, never letter names."""
    if name in ("ENTER", "KPENTER", "SPACE", "BACKSPACE", "DELETE"):
        return name
    if name in ("TAB", "CAPSLOCK", "SHIFT", "LSHIFT", "RSHIFT", "CTRL", "LCTRL", "RCTRL",
                "ALT", "LALT", "RALT", "META", "WIN"):
        return "SHIFT"
    return "KEY"


@dataclass(frozen=True)
class KeyboardDevice:
    path: str
    name: str

    def access_rule(self):
        if not self.name or any(ch in self.name for ch in '\\"\n\r*?[]'):
            raise ValueError("Keyboard name cannot safely be used in a udev match")
        return (f'SUBSYSTEM=="input", KERNEL=="event*", ENV{{ID_INPUT_KEYBOARD}}=="1", '
                f'ATTRS{{name}}=="{self.name}", TAG+="uaccess"\n')


def keyboard_devices(sys_root="/sys/class/input", dev_root="/dev/input"):
    devices = []
    for event in sorted(Path(sys_root).glob("event*")):
        try:
            words = (event / "device/capabilities/key").read_text().split()
            low = int(words[-1], 16)
            # A, Enter, Space: ignore mice, lid switches and media-only input nodes.
            if not all(low & (1 << code) for code in (30, 28, 57)):
                continue
            name = (event / "device/name").read_text().strip()
            # Some mice and security tokens advertise every keyboard key.
            # They are not physical typing keyboards for automatic listening.
            if "yubikey" in name.casefold(): continue
            rel = event / "device/capabilities/rel"
            if rel.exists() and int(rel.read_text().strip(), 16) & 3: continue
            devices.append(KeyboardDevice(str(Path(dev_root) / event.name), name))
        except (OSError, ValueError, IndexError):
            continue
    return devices


class EvdevDecoder:
    """Incremental input_event decoding, preserving record boundaries and dropping repeats."""
    def __init__(self):
        self.buffer = bytearray()
        self.dropped = False

    def feed(self, data):
        self.buffer.extend(data)
        presses = []
        while len(self.buffer) >= INPUT_EVENT.size:
            _, _, kind, code, value = INPUT_EVENT.unpack_from(self.buffer)
            del self.buffer[:INPUT_EVENT.size]
            if kind == 0 and code == 3:  # SYN_DROPPED: wait for the next complete report
                self.dropped = True
            elif kind == 0 and code == 0:
                self.dropped = False
            elif kind == 1 and value == 1 and not self.dropped:
                presses.append(key_name(code))
        return presses


class XInputDecoder:
    def __init__(self):
        self.buffer = ""
        self.raw_press = False
        self.raw_release = False
        self.held = set()

    def feed(self, text):
        self.buffer += text
        presses = []
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.startswith("EVENT type"):
                self.raw_press = "(RawKeyPress)" in line
                self.raw_release = "(RawKeyRelease)" in line
            elif self.raw_press or self.raw_release:
                match = re.search(r"detail:\s+(\d+)", line)
                if match:
                    code = int(match.group(1)) - 8
                    if self.raw_release:
                        self.held.discard(code)
                    elif code not in self.held:
                        self.held.add(code)
                        presses.append(key_name(code))
                    self.raw_press = False
                    self.raw_release = False
        return presses


class GlobalKeyboard(QObject):
    pressed = pyqtSignal(str)
    failed = pyqtSignal(str)
    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fd = None
        self.notifier = None
        self.process = None
        self.decoder = None
        self.streams = {}
        self.denied = {}
        self.automatic = False
        self.poll = QTimer(self)
        self.poll.setInterval(1500)
        self.poll.timeout.connect(self._refresh)

    @staticmethod
    def uses_x11():
        return os.environ.get("XDG_SESSION_TYPE") == "x11" and bool(shutil.which("xinput"))

    def start(self, device=None):
        self.stop()
        if self.uses_x11():
            self.decoder = XInputDecoder()
            self.process = QProcess(self)
            self.process.readyReadStandardOutput.connect(self._xread)
            self.process.finished.connect(self._xfinished)
            self.process.errorOccurred.connect(lambda *_: self.failed.emit("Could not start X11 keyboard input."))
            # Force line buffering when available so piping output never delays key sounds.
            buffering = shutil.which("stdbuf")
            if buffering:
                self.process.start(buffering, ["-oL", shutil.which("xinput"), "test-xi2", "--root"])
            else:
                self.process.start(shutil.which("xinput"), ["test-xi2", "--root"])
            return
        self.automatic = device is None
        if self.automatic:
            self._refresh()
        else:
            self._open(device)
        if not self.streams:
            names = ", ".join(self.denied.values())
            raise OSError(f"Cannot read {names or 'any typing keyboard'}. Enable sounds to set up keyboard access.")
        if self.automatic: self.poll.start()

    def _open(self, device):
        try:
            fd = os.open(device.path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            self.denied[device.path] = device.name
            return
        decoder = EvdevDecoder()
        notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
        self.streams[device.path] = (fd, notifier, decoder, device)
        notifier.activated.connect(lambda *_, p=device.path: self._evread(p))
        self.denied.pop(device.path, None)
        self.fd, self.notifier, self.decoder = fd, notifier, decoder

    def _refresh(self):
        devices = {device.path: device for device in keyboard_devices()}
        before = (tuple(self.streams), tuple(self.denied))
        for path in list(self.streams):
            if path not in devices: self._remove(path)
        self.denied = {path: name for path, name in self.denied.items() if path in devices}
        for path, device in devices.items():
            if path not in self.streams: self._open(device)
        if before != (tuple(self.streams), tuple(self.denied)):
            self.changed.emit(self.description())

    def description(self):
        names = ", ".join(stream[3].name for stream in self.streams.values())
        text = f"Listening to {len(self.streams)} keyboard(s): {names}" if names else "No readable keyboard connected"
        if self.denied:
            text += ". Access needed: " + ", ".join(self.denied.values())
        return text

    def _remove(self, path):
        fd, notifier, _, _ = self.streams.pop(path)
        notifier.setEnabled(False)
        notifier.deleteLater()
        os.close(fd)
        first = next(iter(self.streams.values()), (None, None, None))
        self.fd, self.notifier, self.decoder = first[:3]

    def _evread(self, path):
        stream = self.streams.get(path)
        if stream is None: return
        fd, _, decoder, _ = stream
        try:
            data = os.read(fd, INPUT_EVENT.size * 64)
            if not data: raise OSError("Keyboard disconnected.")
            for name in decoder.feed(data): self.pressed.emit(sound_press(name))
        except BlockingIOError:
            pass
        except OSError as exc:
            self._remove(path)
            if self.automatic:
                self.changed.emit(self.description())
            else:
                self.stop()
                self.failed.emit(str(exc))

    def _xread(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        for name in self.decoder.feed(data): self.pressed.emit(sound_press(name))

    def _xfinished(self, *_):
        self.failed.emit("X11 keyboard input stopped. Check xinput and your desktop session.")

    def stop(self):
        self.poll.stop()
        self.automatic = False
        for path in list(self.streams): self._remove(path)
        self.denied.clear()
        if self.process is not None:
            self.process.finished.disconnect()
            self.process.readyReadStandardOutput.disconnect()
            self.process.errorOccurred.disconnect()
            self.process.kill()
            self.process.deleteLater()
            self.process = None
