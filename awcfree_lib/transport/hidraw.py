"""hidraw transport: user space, no libusb, no kernel-driver detach.

Driving these controllers over libusb means claiming interface 0 and detaching
whatever kernel driver holds it.  On the keyboard that is the HID driver, so
typing stops for as long as the lighting is held.  hidraw avoids the whole
problem: the kernel keeps its driver, we just send reports through it.

The two controllers want different report mechanics, which the capture makes
plain -- the keyboard's reports carry an explicit 0xcc report id and go out as
HID *feature* reports, while the chassis controller has report id 0 and takes
plain *output* reports.

Credit: the hidraw approach and the `\\x85\\xcc` descriptor probe are how
cryptoconspiracy/alien-thunder does it; its `hw.py` is the proof that this works
without root on this hardware.
"""
from __future__ import annotations

import fcntl
import glob
import os
import struct
from collections.abc import Iterable, Sequence

from ..errors import DeviceBusy, DeviceNotFound, TransportError

# linux/hidraw.h ioctl plumbing.  _IOC(dir, type, nr, size) with type 'H'.
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("H") << 8) | nr


def _HIDIOCSFEATURE(size: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, 0x06, size)


def _HIDIOCGFEATURE(size: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, 0x07, size)


def _HIDIOCGINPUT(size: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, 0x0A, size)


def find_hidraw(
    vid: int, pid: int, *, descriptor_contains: bytes | None = None,
    interface: str | None = None,
) -> str | None:
    """Locate the /dev/hidrawN node for a USB vid:pid.

    Devices with several HID interfaces expose several nodes, only one of which
    takes lighting commands.  `descriptor_contains` picks the right one by looking
    for a byte run in the report descriptor (0x85 0xcc is "report id 0xcc").
    """
    want = f"{vid:08X}:{pid:08X}"
    for sysfs in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sysfs, "device/uevent")) as fh:
                uevent = fh.read()
        except OSError:
            continue
        if want not in uevent.upper():
            continue
        if interface is not None and f"ID_USB_INTERFACE_NUM={interface}" not in uevent:
            continue
        if descriptor_contains is not None:
            try:
                with open(os.path.join(sysfs, "device/report_descriptor"), "rb") as fh:
                    if descriptor_contains not in fh.read():
                        continue
            except OSError:
                continue
        return "/dev/" + os.path.basename(sysfs)
    return None


class HidrawDevice:
    """A single hidraw node.  Reference-counted open, so nesting `with` is safe."""

    def __init__(self, path: str, report_len: int, label: str = "device") -> None:
        self.path = path
        self.report_len = report_len
        self.label = label
        self._fd: int | None = None
        self._depth = 0

    # --- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        self._depth += 1
        if self._fd is not None:
            return
        try:
            self._fd = os.open(self.path, os.O_RDWR)
        except PermissionError as exc:
            self._depth -= 1
            raise DeviceBusy(
                f"{self.label}: no permission for {self.path}. Install the udev rule "
                f"(freealien install-udev) or run as root."
            ) from exc
        except FileNotFoundError as exc:
            self._depth -= 1
            raise DeviceNotFound(f"{self.label}: {self.path} is gone") from exc

    def close(self) -> None:
        self._depth = max(0, self._depth - 1)
        if self._depth == 0 and self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> HidrawDevice:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise TransportError(f"{self.label}: not open")
        return self._fd

    # --- I/O ---------------------------------------------------------------
    def _buffer(self, packet: bytes | bytearray) -> bytearray:
        if len(packet) > self.report_len:
            raise TransportError(
                f"{self.label}: packet is {len(packet)} bytes, report is {self.report_len}"
            )
        buf = bytearray(self.report_len)
        buf[: len(packet)] = packet
        return buf

    def send_feature(self, packet: bytes | bytearray) -> None:
        """HIDIOCSFEATURE.  `packet[0]` must already be the report id."""
        buf = self._buffer(packet)
        try:
            fcntl.ioctl(self.fd, _HIDIOCSFEATURE(len(buf)), buf)
        except OSError as exc:
            raise TransportError(f"{self.label}: feature write failed: {exc}") from exc

    def get_feature(self, report_id: int) -> bytes:
        """HIDIOCGFEATURE for one report id."""
        buf = bytearray(self.report_len)
        buf[0] = report_id
        try:
            n = fcntl.ioctl(self.fd, _HIDIOCGFEATURE(len(buf)), buf)
        except OSError as exc:
            raise TransportError(f"{self.label}: feature read failed: {exc}") from exc
        return bytes(buf[: n if n > 0 else len(buf)])

    def send_output(self, packet: bytes | bytearray, report_id: int = 0x00) -> None:
        """A plain write, with the report id prepended."""
        buf = self._buffer(packet)
        payload = bytes([report_id]) + bytes(buf)
        try:
            written = os.write(self.fd, payload)
        except OSError as exc:
            raise TransportError(f"{self.label}: output write failed: {exc}") from exc
        if written != len(payload):
            raise TransportError(
                f"{self.label}: short write, {written} of {len(payload)} bytes"
            )

    def get_input(self) -> bytes:
        """HIDIOCGINPUT -- read the current input report without blocking on events."""
        buf = bytearray(self.report_len)
        try:
            fcntl.ioctl(self.fd, _HIDIOCGINPUT(len(buf)), buf)
        except OSError as exc:
            raise TransportError(f"{self.label}: input read failed: {exc}") from exc
        return bytes(buf)


def single_instance_lock(path: str) -> int:
    """Take an advisory lock so two writers cannot interleave transactions.

    The controllers keep state between reports -- open a transaction, select zones,
    add actions, commit -- so two processes writing at once corrupts both.
    """
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise DeviceBusy(f"another FreeAlien process holds {path}") from exc
    os.write(fd, str(os.getpid()).encode())
    return fd
