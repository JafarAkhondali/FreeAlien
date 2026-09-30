"""Where each keyboard LED physically sits, measured rather than guessed.

Every position was obtained by lighting one LED at a time and locating it with a
webcam: the frame is diffed against a dark reference, masked to the keyboard, and
the *topmost* strong band of the resulting blob taken. Anchoring to the top matters
-- the deck below the keyboard is glossy, so each key throws a specular streak
downwards, and on the bottom row that reflection outshines the key itself, which
drags a plain centroid or argmax a whole row low.

Rows come from gap-clustering the tilt-corrected y. Columns come from one global
origin and pitch, assigned per row by a least-squares strictly-increasing fit; a
greedy "bump the clash right" rule cascades and shunts a whole staggered row sideways.

Three things fell out of the measurement:

* The LED ids run in physical order -- left to right within each row. That the raw
  ids came out ordered is independent evidence the fit is right.
* Of the 92 ids the protocol addresses, only 85 drive a physical LED on this ANSI
  unit. The other seven light nothing: driven together at full white they raise the
  peak frame difference to 9.8, against 136 for seven ordinary keys, and put zero
  pixels over threshold. They are very likely keys that exist on the ISO and ABNT2
  builds of the same chassis. `ALL_LEDS` still carries all 92, because the enable
  mask and the colour frames are built against the protocol's set, not this unit's.
* Lighting one column at a time and then one row at a time, and checking which LEDs
  respond, confirms all 85 in both axes.
"""
from __future__ import annotations

#: Grid cell (column, row) for every LED that physically lights, measured.
CELLS: dict[int, tuple[int, int]] = {
    # row 0
    0x01: (0, 0),
    0x02: (1, 0),
    0x03: (2, 0),
    0x04: (3, 0),
    0x05: (4, 0),
    0x06: (5, 0),
    0x07: (6, 0),
    0x08: (7, 0),
    0x09: (8, 0),
    0x0a: (9, 0),
    0x0b: (10, 0),
    0x0c: (11, 0),
    0x0d: (12, 0),
    0x0e: (13, 0),
    0x0f: (14, 0),
    0x10: (15, 0),
    # row 1
    0x15: (0, 1),
    0x16: (1, 1),
    0x17: (2, 1),
    0x18: (3, 1),
    0x19: (4, 1),
    0x1a: (5, 1),
    0x1b: (6, 1),
    0x1c: (7, 1),
    0x1d: (8, 1),
    0x1e: (9, 1),
    0x1f: (10, 1),
    0x20: (11, 1),
    0x21: (12, 1),
    0x24: (13, 1),
    0x14: (15, 1),
    # row 2
    0x29: (0, 2),
    0x2b: (1, 2),
    0x2c: (2, 2),
    0x2d: (3, 2),
    0x2e: (4, 2),
    0x2f: (5, 2),
    0x30: (6, 2),
    0x31: (7, 2),
    0x32: (8, 2),
    0x33: (9, 2),
    0x34: (10, 2),
    0x35: (11, 2),
    0x36: (12, 2),
    0x38: (13, 2),
    0x11: (15, 2),
    # row 3
    0x3e: (0, 3),
    0x3f: (1, 3),
    0x40: (2, 3),
    0x41: (3, 3),
    0x42: (4, 3),
    0x43: (5, 3),
    0x44: (6, 3),
    0x45: (7, 3),
    0x46: (8, 3),
    0x47: (9, 3),
    0x48: (10, 3),
    0x49: (11, 3),
    0x4b: (13, 3),
    0x13: (15, 3),
    # row 4
    0x52: (0, 4),
    0x54: (2, 4),
    0x55: (3, 4),
    0x56: (4, 4),
    0x57: (5, 4),
    0x58: (6, 4),
    0x59: (7, 4),
    0x5a: (8, 4),
    0x5b: (9, 4),
    0x5c: (10, 4),
    0x5d: (11, 4),
    0x5f: (12, 4),
    0x73: (14, 4),
    0x12: (15, 4),
    # row 5
    0x65: (0, 5),
    0x66: (1, 5),
    0x68: (2, 5),
    0x69: (3, 5),
    0x6c: (6, 5),
    0x70: (9, 5),
    0x6e: (10, 5),
    0x71: (11, 5),
    0x86: (13, 5),
    0x87: (14, 5),
    0x88: (15, 5),
}

#: Ids the protocol accepts that light nothing on this unit. Kept so callers can
#: tell "not wired here" from "unknown", and so ALL_LEDS stays the protocol's set.
DEAD_LEDS: tuple[int, ...] = (
    0x22, 0x37, 0x3c, 0x4a, 0x53, 0x6a, 0x6f,
)

#: Measured camera position, kept as provenance for the fit above.
PIXELS: dict[int, tuple[float, float]] = {
    0x01: (126.4, 88.7),
    0x02: (181.1, 90.9),
    0x03: (236.4, 83.8),
    0x04: (290.7, 81.4),
    0x05: (346.9, 78.8),
    0x06: (400.8, 77.4),
    0x07: (458.8, 75.4),
    0x08: (516.9, 74.3),
    0x09: (575.9, 72.7),
    0x0a: (631.1, 70.3),
    0x0b: (691.3, 68.8),
    0x0c: (750.0, 66.5),
    0x0d: (811.9, 67.4),
    0x0e: (868.0, 64.8),
    0x0f: (928.5, 62.2),
    0x10: (990.3, 61.6),
    0x11: (990.9, 164.9),
    0x12: (987.7, 276.5),
    0x13: (988.5, 218.0),
    0x14: (990.4, 106.6),
    0x15: (130.0, 121.4),
    0x16: (183.7, 123.7),
    0x17: (233.4, 123.5),
    0x18: (288.9, 120.7),
    0x19: (344.2, 116.7),
    0x1a: (398.9, 115.5),
    0x1b: (456.7, 113.8),
    0x1c: (517.1, 110.2),
    0x1d: (572.8, 109.6),
    0x1e: (630.6, 108.8),
    0x1f: (691.0, 106.0),
    0x20: (747.8, 102.0),
    0x21: (806.5, 102.9),
    0x24: (893.7, 96.5),
    0x29: (136.3, 178.7),
    0x2b: (204.5, 181.9),
    0x2c: (258.7, 181.4),
    0x2d: (316.4, 177.6),
    0x2e: (369.5, 174.6),
    0x2f: (429.8, 170.7),
    0x30: (488.9, 169.7),
    0x31: (544.5, 168.7),
    0x32: (603.1, 164.7),
    0x33: (660.9, 165.6),
    0x34: (718.0, 165.9),
    0x35: (774.5, 161.4),
    0x36: (836.9, 159.8),
    0x38: (911.3, 158.5),
    0x3e: (140.3, 236.7),
    0x3f: (218.5, 236.7),
    0x40: (276.7, 234.5),
    0x41: (328.9, 234.0),
    0x42: (387.2, 230.2),
    0x43: (443.9, 229.4),
    0x44: (503.7, 227.9),
    0x45: (561.8, 223.7),
    0x46: (615.2, 225.3),
    0x47: (674.5, 222.0),
    0x48: (733.3, 220.4),
    0x49: (790.6, 218.5),
    0x4b: (893.0, 217.2),
    0x52: (151.9, 299.2),
    0x54: (249.9, 292.2),
    0x55: (305.0, 290.3),
    0x56: (363.6, 287.9),
    0x57: (420.2, 287.4),
    0x58: (475.7, 286.6),
    0x59: (532.2, 285.8),
    0x5a: (590.5, 285.0),
    0x5b: (648.0, 280.5),
    0x5c: (703.4, 279.2),
    0x5d: (763.6, 279.6),
    0x5f: (844.8, 279.5),
    0x65: (130.0, 352.4),
    0x66: (195.6, 351.8),
    0x68: (248.6, 349.2),
    0x69: (299.9, 351.2),
    0x6c: (491.0, 337.8),
    0x6e: (704.3, 346.1),
    0x70: (648.5, 340.8),
    0x71: (784.0, 338.6),
    0x73: (929.0, 276.3),
    0x86: (869.2, 337.4),
    0x87: (929.4, 337.0),
    0x88: (988.0, 335.7),
}

#: Every id the controller addresses, in the order the stock software writes them.
#: `protocol.v5.colour_frames(..., order=ALL_LEDS)` reproduces its packets exactly.
ALL_LEDS: tuple[int, ...] = (
    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c,
    0x0d, 0x0e, 0x0f, 0x10, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c,
    0x1d, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x24, 0x14, 0x29, 0x2b, 0x2c, 0x2d,
    0x2e, 0x2f, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x11,
    0x3c, 0x3e, 0x3f, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
    0x49, 0x4a, 0x4b, 0x13, 0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5a, 0x5b, 0x5c, 0x5d, 0x5f, 0x73, 0x12, 0x65, 0x66, 0x68, 0x69, 0x6a,
    0x6f, 0x6c, 0x70, 0x71, 0x6e, 0x86, 0x87, 0x88,
)

PLACED_LEDS: tuple[int, ...] = tuple(sorted(CELLS))
UNPLACED_LEDS: tuple[int, ...] = DEAD_LEDS

GRID_COLS = 16
GRID_ROWS = 6

#: Human labels. Deliberately sparse: the labels inherited from the earlier
#: hand-built map were shown to be wrong by the measurement (the id once called
#: "ESC" measures two rows below the function row), so only names confirmed against
#: a photograph of the lit keyboard appear here. `awcfree identify` adds more.
NAMES: dict[int, str] = {
    0x01: 'ESC',
    0x02: 'F1',
    0x03: 'F2',
    0x04: 'F3',
    0x05: 'F4',
    0x06: 'F5',
    0x07: 'F6',
    0x08: 'F7',
    0x09: 'F8',
    0x0a: 'F9',
    0x0b: 'F10',
    0x0c: 'F11',
    0x0d: 'F12',
    0x0e: 'HOME',
    0x0f: 'END',
    0x10: 'DEL',
    0x15: '`',
    0x16: '1',
    0x17: '2',
    0x18: '3',
    0x19: '4',
    0x1a: '5',
    0x1b: '6',
    0x1c: '7',
    0x1d: '8',
    0x1e: '9',
    0x1f: '0',
    0x20: '-',
    0x21: '=',
    0x24: 'BACKSPACE',
    0x29: 'TAB',
    0x2b: 'Q',
    0x2c: 'W',
    0x2d: 'E',
    0x2e: 'R',
    0x2f: 'T',
    0x30: 'Y',
    0x31: 'U',
    0x32: 'I',
    0x33: 'O',
    0x34: 'P',
    0x35: '[',
    0x36: ']',
    0x38: '\\',
    0x3e: 'CAPSLOCK',
    0x3f: 'A',
    0x40: 'S',
    0x41: 'D',
    0x42: 'F',
    0x43: 'G',
    0x44: 'H',
    0x45: 'J',
    0x46: 'K',
    0x47: 'L',
    0x48: ';',
    0x49: "'",
    0x4b: 'ENTER',
    0x52: 'LSHIFT',
    0x54: 'Z',
    0x55: 'X',
    0x56: 'C',
    0x57: 'V',
    0x58: 'B',
    0x59: 'N',
    0x5a: 'M',
    0x5b: ',',
    0x5c: '.',
    0x5d: '/',
    0x5f: 'RSHIFT',
    0x73: 'UP',
    0x65: 'LCTRL',
    0x66: 'FN',
    0x68: 'WIN',
    0x69: 'LALT',
    0x6c: 'SPACE',
    0x70: 'RALT',
    0x6e: 'WINLOCK',
    0x71: 'RCTRL',
    0x86: 'LEFT',
    0x87: 'DOWN',
    0x88: 'RIGHT',
}


def cell(led: int) -> tuple[int, int] | None:
    """Grid cell for an LED, or None when it lights nothing on this unit."""
    return CELLS.get(led)


def at(col: int, row: int) -> tuple[int, ...]:
    """Every LED in a grid cell."""
    return tuple(led for led, pos in CELLS.items() if pos == (col, row))


def by_name(name: str) -> int:
    """Look an LED up by label, case-insensitively."""
    want = name.strip().lower()
    for led, label in NAMES.items():
        if label.lower() == want:
            return led
    raise KeyError(name)

