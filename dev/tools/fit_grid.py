#!/usr/bin/env python3
"""Turn measured pixel positions into a (column, row) grid.

Rows come from gap-clustering the tilt-corrected y.  Columns come from a single
global origin and pitch, so a key in one row lines up with the key above it -- which
is what a canvas needs, and what per-row normalisation would destroy.
"""
from __future__ import annotations

from pathlib import Path

import json
import os
import sys

import numpy as np

SCRATCH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from awcfree_lib import layout  # noqa: E402

MIN_SCORE = 20.0


def cluster(values, gap):
    """Split sorted values wherever the step exceeds `gap`."""
    order = np.argsort(values)
    groups, current = [], [order[0]]
    for prev, idx in zip(order, order[1:]):
        if values[idx] - values[prev] > gap:
            groups.append(current)
            current = []
        current.append(idx)
    groups.append(current)
    return groups


def main() -> int:
    data = json.load(open(f"{SCRATCH}/positions.json"))
    pts = {int(k, 16): v for k, v in data.items()}
    good = {k: v for k, v in pts.items() if v["score"] >= MIN_SCORE}
    weak = sorted(set(pts) - set(good))

    leds = np.array(sorted(good))
    xs = np.array([good[k]["x"] for k in leds])
    ys = np.array([good[k]["y"] for k in leds])

    # flatten the camera tilt so rows become horizontal
    slope = np.polyfit(xs, ys, 1)[0]
    yf = ys - slope * xs

    row_groups = cluster(yf, gap=11.0)
    row_groups.sort(key=lambda g: yf[g].mean())
    print(f"{len(row_groups)} rows detected:")
    for r, g in enumerate(row_groups):
        print(f"  row {r}: {len(g):2d} keys, y~{yf[g].mean():6.1f}")

    # pitch: median gap between x-neighbours inside a row
    gaps = []
    for g in row_groups:
        sx = np.sort(xs[g])
        gaps += [b - a for a, b in zip(sx, sx[1:]) if b - a > 20]
    pitch = float(np.median(gaps))
    origin = float(xs.min())
    print(f"\npitch={pitch:.1f}px  origin_x={origin:.1f}")

    # Assign columns per row by optimal strictly-increasing assignment.
    #
    # Rounding alone is not enough: the keyboard is staggered, so the home row lands
    # on x.4-x.5 boundaries where two keys round to the same column.  Resolving that
    # greedily -- bump the right-hand key by one -- cascades, and shunts an entire row
    # one column right.  Minimising total displacement instead keeps the row anchored.
    maxcol = int(round((xs.max() - origin) / pitch)) + 2
    cells: dict[int, tuple[int, int]] = {}
    for r, g in enumerate(row_groups):
        order = sorted(g, key=lambda i: xs[i])
        raw = [(xs[i] - origin) / pitch for i in order]
        n = len(order)
        INF = float("inf")
        # best[i][c] = least squared error placing key i at column c, keys strictly
        # increasing; back[i][c] remembers the column chosen for key i-1.
        best = [[INF] * (maxcol + 1) for _ in range(n)]
        back = [[-1] * (maxcol + 1) for _ in range(n)]
        for c in range(maxcol + 1):
            best[0][c] = (c - raw[0]) ** 2
        for i in range(1, n):
            run = INF
            arg = -1
            for c in range(maxcol + 1):
                if c - 1 >= 0 and best[i - 1][c - 1] < run:
                    run = best[i - 1][c - 1]
                    arg = c - 1
                if run < INF:
                    best[i][c] = run + (c - raw[i]) ** 2
                    back[i][c] = arg
        c = min(range(maxcol + 1), key=lambda c: best[n - 1][c])
        chosen = [0] * n
        for i in range(n - 1, -1, -1):
            chosen[i] = c
            c = back[i][c]
        for i, idx in enumerate(order):
            cells[int(leds[idx])] = (chosen[i], r)

    cols = max(c for c, _ in cells.values()) + 1
    rows = len(row_groups)
    print(f"grid: {cols} x {rows}, {len(cells)} placed, {len(weak)} unplaced")

    grid = [[None] * cols for _ in range(rows)]
    for k, (c, r) in cells.items():
        grid[r][c] = k
    print("\nmeasured layout (. = empty):")
    for r, line in enumerate(grid):
        print(f"  row{r} " + "".join("." if k is None else "#" for k in line))
    print("\nwith ids:")
    for r, line in enumerate(grid):
        print(f"  row{r} " + " ".join("--" if k is None else f"{k:02x}" for k in line))

    out = {
        "cells": {f"0x{k:02x}": list(v) for k, v in cells.items()},
        "pixels": {f"0x{k:02x}": [good[k]["x"], good[k]["y"]] for k in good},
        "weak": [f"0x{k:02x}" for k in weak],
        "cols": cols,
        "rows": rows,
    }
    with open(f"{SCRATCH}/grid.json", "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"\nwrote {SCRATCH}/grid.json")
    print(f"not seen by the camera: {' '.join(out['weak'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
