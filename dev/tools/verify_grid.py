#!/usr/bin/env python3
"""Check the fitted grid.

A warning about what cannot be tested here.  The tempting check -- light column c,
photograph it, confirm those LEDs lit -- is circular.  It lights LED X based on
`CELLS[X]` and then looks at `PIXELS[X]`, X's own measured position, which is bright
regardless of what column the fit assigned.  A deliberately shuffled layout scores
full marks on it.  Encoding the column index across several frames does not help
either: the pattern is both written and read from the same assignment.

`PIXELS` is the ground truth (each LED measured on its own) and `CELLS` is a pure
function of it, so nothing a camera does at `PIXELS[X]` can validate `CELLS[X]`.
What can be checked:

  * that `PIXELS` is unambiguous -- no two LEDs measured close enough to be confused;
  * that the fit from `PIXELS` to `CELLS` is well behaved -- columns strictly
    increasing with x in every row, residuals well under a key width;
  * by eye, that a pattern defined in grid terms lands on the right physical keys.

`--numeric` does the first two and needs no hardware.  `--pattern` lights the third:
alternating columns, which a human can check in one glance because any misassignment
breaks the alternation.  `--rows` colours each row separately for the same purpose.
"""
from __future__ import annotations

from pathlib import Path

import argparse
import collections
import math
import os
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from awcfree_lib import layout  # noqa: E402

PITCH = 58.2  # px between adjacent keys, from the measurement


def numeric() -> int:
    P, C = layout.PIXELS, layout.CELLS
    problems = 0

    closest, pair = math.inf, None
    leds = [l for l in P if l in C]
    for i, a in enumerate(leds):
        for b in leds[i + 1:]:
            d = math.hypot(P[a][0] - P[b][0], P[a][1] - P[b][1])
            if d < closest:
                closest, pair = d, (a, b)
    ratio = closest / PITCH
    print(f"closest two measured LEDs: {closest:.1f}px = {ratio:.2f} key pitches "
          f"(0x{pair[0]:02x}, 0x{pair[1]:02x})")
    if ratio < 0.35:
        print("  PROBLEM: two LEDs measured too close to tell apart")
        problems += 1

    byrow = collections.defaultdict(list)
    for led, (c, r) in C.items():
        byrow[r].append(led)
    origin = min(P[l][0] for l in C)
    worst = 0.0
    for r in sorted(byrow):
        row = sorted(byrow[r], key=lambda l: P[l][0])
        cols = [C[l][0] for l in row]
        if cols != sorted(cols) or len(set(cols)) != len(cols):
            print(f"  PROBLEM: row {r} columns not strictly increasing with x: {cols}")
            problems += 1
        res = [C[l][0] - (P[l][0] - origin) / PITCH for l in row]
        worst = max(worst, max(abs(v) for v in res))
        mean = sum(res) / len(res)
        print(f"row {r}: {len(row):2d} keys, cols {min(cols):2d}..{max(cols):2d}, "
              f"stagger offset {mean:+.2f}, max residual {max(abs(v) for v in res):.2f}")
    if worst > 0.75:
        print(f"  PROBLEM: a key sits {worst:.2f} key widths from its assigned column")
        problems += 1

    print()
    print(f"{len(C)} wired LEDs, {len(layout.DEAD_LEDS)} addressable but not wired, "
          f"{len(layout.NAMES)} named")
    print("OK" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


def pattern(mode: str) -> int:
    from awcfree_lib.devices import Keyboard

    with Keyboard() as kb:
        kb.take_control()
        kb.fill((0, 0, 0))
        if mode == "cols":
            for led, (c, r) in layout.CELLS.items():
                if c % 2 == 0:
                    kb.set(led, (0, 90, 255) if c % 4 == 0 else (255, 90, 0))
            print("Even columns lit, alternating blue / orange; odd columns dark.")
            print("Every lit key must have dark keys either side of it, and the lit")
            print("keys must line up vertically down the board.")
        else:
            palette = [(255, 0, 0), (0, 255, 0), (0, 80, 255),
                       (255, 255, 0), (255, 0, 255), (0, 255, 255)]
            for led, (c, r) in layout.CELLS.items():
                kb.set(led, palette[r % len(palette)])
            print("Each row a single colour. Every physical row must be uniform.")
        kb.flush(force=True)
        time.sleep(0.2)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--numeric", action="store_true", help="checks needing no hardware")
    ap.add_argument("--pattern", choices=("cols", "rows"),
                    help="light a pattern to be checked by eye")
    args = ap.parse_args()
    if args.pattern:
        return pattern(args.pattern)
    return numeric()


if __name__ == "__main__":
    sys.exit(main())
