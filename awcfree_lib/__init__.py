"""FreeAlien -- Alienware lighting control for Linux, built on hidraw.

Layout:
  protocol/  pure packet encoders (v4 chassis, v5 per-key keyboard), no I/O
  transport/ hidraw device access
  devices/   Keyboard and Chassis, stateful, with frame diffing
  layout     the 92 real LED ids and where they sit physically
  canvas     a grid framebuffer over those LEDs, for games and text
  session    both controllers behind one object

See CREDITS.md for the projects this protocol knowledge came from.
"""
from .canvas import Canvas
from .devices import Chassis, Keyboard
from .errors import (
    AwcfreeError,
    DeviceBusy,
    DeviceNotFound,
    ProtocolError,
    TransportError,
)
from .session import Lighting

__version__ = "0.1.0"

__all__ = [
    "Canvas", "Chassis", "Keyboard", "Lighting",
    "AwcfreeError", "DeviceBusy", "DeviceNotFound", "ProtocolError", "TransportError",
    "__version__",
]
