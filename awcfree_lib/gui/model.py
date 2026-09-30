"""What the browser needs to draw the keyboard, and the state it manipulates.

The on-screen keyboard is built from the measured layout, not from a hand-drawn
picture, so it is the real key arrangement of this machine.  Grid cells give each
key its position; widths come from the table below, because the grid alone cannot
say whether the hole beside a key belongs to that key (a wide Backspace) or to its
neighbour (a wide Enter reaching left).
"""
from __future__ import annotations

import json
import os
import threading

from .. import layout
from ..protocol import v4

Rgb = tuple[int, int, int]

#: label -> (column offset, width in grid cells) for keys that are not one cell
#: wide.  Everything absent from here is a single cell.  Each entry was checked
#: against the hole pattern: a wide key is always followed (or preceded) by cells
#: with no LED, and these spans cover exactly those holes.
WIDE_KEYS: dict[str, tuple[int, int]] = {
    "BACKSPACE": (0, 2),
    "\\": (0, 2),
    "ENTER": (-1, 3),
    "LSHIFT": (0, 2),
    "RSHIFT": (0, 2),
    "RCTRL": (0, 2),
    "SPACE": (-2, 5),
}

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "awcfree"
)
PRESET_FILE = os.path.join(CONFIG_DIR, "presets.json")


def keyboard_layout() -> list[dict]:
    """One entry per wired LED: id, grid position, span and label."""
    keys = []
    for led, (col, row) in sorted(layout.CELLS.items(), key=lambda kv: (kv[1][1], kv[1][0])):
        label = layout.NAMES.get(led, "")
        offset, width = WIDE_KEYS.get(label, (0, 1))
        keys.append({
            "id": led,
            "hex": f"0x{led:02x}",
            "col": col + offset,
            "row": row,
            "w": width,
            "label": label,
            "named": bool(label),
        })
    return keys


def chassis_zones() -> list[dict]:
    return [
        {"id": v4.ZONE_TOUCHPAD, "name": "Touchpad", "key": "touchpad"},
        {"id": v4.ZONE_LOGO, "name": "Lid emblem", "key": "logo"},
        {"id": v4.ZONE_POWER, "name": "Power button", "key": "power"},
    ]


class Presets:
    """Named colour sets on disk.

    A preset stores per-key colours plus the chassis zones, so restoring one puts
    the whole machine back rather than just the keys.
    """

    def __init__(self, path: str = PRESET_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path) as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.data, fh, indent=1)
        os.replace(tmp, self.path)

    def put(self, name: str, payload: dict) -> None:
        with self._lock:
            self.data[name] = payload
            self.save()

    def drop(self, name: str) -> bool:
        with self._lock:
            if name in self.data:
                del self.data[name]
                self.save()
                return True
        return False

    def names(self) -> list[str]:
        return sorted(self.data)
