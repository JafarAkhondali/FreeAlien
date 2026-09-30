#!/usr/bin/env python3
"""Write layout.py from the measured grid."""
from __future__ import annotations

from pathlib import Path

import json
import os
import sys

SCRATCH = os.path.dirname(os.path.abspath(__file__))
OUT = str(Path(__file__).resolve().parents[2] / "awcfree_lib/layout.py")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

grid = json.load(open(f"{SCRATCH}/grid.json"))
cells = {int(k, 16): tuple(v) for k, v in grid["cells"].items()}
pixels = {int(k, 16): v for k, v in grid["pixels"].items()}
dead = [int(v, 16) for v in grid["weak"]]

# ALL_LEDS keeps the protocol's 92: the mask and the colour frames are built from
# that set, and AWCC writes all of them regardless of what is physically wired.
all_leds = sorted(set(cells) | set(dead))
order_src = json.load(open(f"{SCRATCH}/wire_order.json"))
wire_order = [int(v, 16) for v in order_src]
assert set(wire_order) == set(all_leds), "wire order disagrees with measurements"


# Labels read off photographs of the lit keyboard taken during the measurement
# (rows coloured individually, then a tight crop of the arrow cluster). Keyed by
# grid cell, so they survive a re-measurement.
LABELS = {
 (0,0):"ESC",(1,0):"F1",(2,0):"F2",(3,0):"F3",(4,0):"F4",(5,0):"F5",(6,0):"F6",
 (7,0):"F7",(8,0):"F8",(9,0):"F9",(10,0):"F10",(11,0):"F11",(12,0):"F12",
 (13,0):"HOME",(14,0):"END",(15,0):"DEL",
 (0,1):"`",(1,1):"1",(2,1):"2",(3,1):"3",(4,1):"4",(5,1):"5",(6,1):"6",(7,1):"7",
 (8,1):"8",(9,1):"9",(10,1):"0",(11,1):"-",(12,1):"=",(13,1):"BACKSPACE",
 (0,2):"TAB",(1,2):"Q",(2,2):"W",(3,2):"E",(4,2):"R",(5,2):"T",(6,2):"Y",(7,2):"U",
 (8,2):"I",(9,2):"O",(10,2):"P",(11,2):"[",(12,2):"]",(13,2):"\\",
 (0,3):"CAPSLOCK",(1,3):"A",(2,3):"S",(3,3):"D",(4,3):"F",(5,3):"G",(6,3):"H",
 (7,3):"J",(8,3):"K",(9,3):"L",(10,3):";",(11,3):"'",(13,3):"ENTER",
 (0,4):"LSHIFT",(2,4):"Z",(3,4):"X",(4,4):"C",(5,4):"V",(6,4):"B",(7,4):"N",
 (8,4):"M",(9,4):",",(10,4):".",(11,4):"/",(12,4):"RSHIFT",(14,4):"UP",
 (0,5):"LCTRL",(1,5):"FN",(2,5):"WIN",(3,5):"LALT",(6,5):"SPACE",(9,5):"RALT",
 (10,5):"WINLOCK",(11,5):"RCTRL",(13,5):"LEFT",(14,5):"DOWN",(15,5):"RIGHT",
}

rows = grid["rows"]
cols = grid["cols"]

body = ['''"""Where each keyboard LED physically sits, measured rather than guessed.

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
CELLS: dict[int, tuple[int, int]] = {''']

by_cell = sorted(cells.items(), key=lambda kv: (kv[1][1], kv[1][0]))
last_row = None
for led, (c, r) in by_cell:
    if r != last_row:
        body.append(f"    # row {r}")
        last_row = r
    body.append(f"    0x{led:02x}: ({c}, {r}),")
body.append("}")
body.append("")
body.append('''#: Ids the protocol accepts that light nothing on this unit. Kept so callers can
#: tell "not wired here" from "unknown", and so ALL_LEDS stays the protocol's set.
DEAD_LEDS: tuple[int, ...] = (''')
body.append("    " + ", ".join(f"0x{v:02x}" for v in sorted(dead)) + ",")
body.append(")")
body.append("")
body.append("#: Measured camera position, kept as provenance for the fit above.")
body.append("PIXELS: dict[int, tuple[float, float]] = {")
for led in sorted(pixels):
    x, y = pixels[led]
    body.append(f"    0x{led:02x}: ({x:.1f}, {y:.1f}),")
body.append("}")
body.append("")
body.append('''#: Every id the controller addresses, in the order the stock software writes them.
#: `protocol.v5.colour_frames(..., order=ALL_LEDS)` reproduces its packets exactly.
ALL_LEDS: tuple[int, ...] = (''')
for i in range(0, len(wire_order), 12):
    body.append("    " + " ".join(f"0x{v:02x}," for v in wire_order[i : i + 12]))
body.append(")")
body.append("")
names_body = "\n".join(
    f'    0x{led:02x}: {LABELS[pos]!r},' for led, pos in sorted(cells.items(), key=lambda kv:(kv[1][1],kv[1][0])) if pos in LABELS
)
body.append(f'''PLACED_LEDS: tuple[int, ...] = tuple(sorted(CELLS))
UNPLACED_LEDS: tuple[int, ...] = DEAD_LEDS

GRID_COLS = {cols}
GRID_ROWS = {rows}

#: Human labels. Deliberately sparse: the labels inherited from the earlier
#: hand-built map were shown to be wrong by the measurement (the id once called
#: "ESC" measures two rows below the function row), so only names confirmed against
#: a photograph of the lit keyboard appear here. `awcfree identify` adds more.
NAMES: dict[int, str] = {{
{names_body}
}}


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
''')

open(OUT, "w").write("\n".join(body) + "\n")
print(f"wrote {OUT}: {len(cells)} placed, {len(dead)} dead, grid {cols}x{rows}")
