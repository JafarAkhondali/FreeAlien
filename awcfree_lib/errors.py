"""Exception types.  Everything the library raises derives from AwcfreeError."""
from __future__ import annotations


class AwcfreeError(Exception):
    """Base class for every error this library raises."""


class DeviceNotFound(AwcfreeError):
    """No hidraw node matched the controller we were looking for."""


class DeviceBusy(AwcfreeError):
    """The node exists but we cannot take it -- permissions, or another writer."""


class TransportError(AwcfreeError):
    """A read or write to the device failed."""


class ProtocolError(AwcfreeError):
    """A packet could not be built, or a reply made no sense."""
