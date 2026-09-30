#!/usr/bin/env python3
"""Measure where each keyboard LED physically sits, using the webcam.

Lights one LED at a time, diffs the frame against a dark reference and takes the
centroid of the brightest blob.  That gives a pixel position per LED, which beats
guessing from a photograph and costs no vision tokens.

Usage:
  map_keys.py --trial          a few known keys, to sanity-check the rig
  map_keys.py                  all 92 LEDs -> positions.json
"""
from __future__ import annotations

from pathlib import Path

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from awcfree_lib import layout  # noqa: E402
from awcfree_lib.devices import Keyboard  # noqa: E402

DEVICE = "/dev/video4"
WIDTH, HEIGHT = 1280, 720

#: Height in pixels of the band taken from the top of a blob; about half a key.
BAND = 22


class Camera:
    def __init__(self, device: str = DEVICE) -> None:
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            raise SystemExit(f"cannot open {device}")
        for _ in range(10):  # let auto-exposure settle
            self.cap.read()

    def frame(self, drop: int = 4) -> np.ndarray:
        """Grab a fresh frame, discarding buffered ones."""
        for _ in range(drop):
            self.cap.grab()
        ok, img = self.cap.retrieve()
        if not ok:
            raise SystemExit("frame grab failed")
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)

    def average(self, n: int = 3) -> np.ndarray:
        return np.mean([self.frame() for _ in range(n)], axis=0)

    def release(self) -> None:
        self.cap.release()


def locate(lit: np.ndarray, dark: np.ndarray,
           roi: np.ndarray | None = None) -> tuple[float, float, float]:
    """Centroid and strength of the brightest region that appeared.

    `roi` restricts the search to the keyboard.  Without it the detector latches onto
    specular highlights off nearby glossy surfaces, which respond to *any* key and so
    give every LED nearly the same coordinates.

    Returns (x, y, score); score is the peak of the blurred difference, so an LED the
    camera cannot see scores near zero.
    """
    diff = cv2.GaussianBlur(np.clip(lit - dark, 0, None), (0, 0), 3.0)
    if roi is not None:
        diff = diff * roi
    peak = float(diff.max())
    if peak <= 0:
        return (float("nan"), float("nan"), 0.0)
    # Take the topmost strong band rather than the whole blob.  The deck below the
    # keyboard is glossy, so every key throws a specular streak downwards -- on the
    # bottom row that reflection is brighter than the key itself, and both a centroid
    # and a plain argmax land on it.  The key is always above its own reflection, so
    # anchoring to the top edge of the strong region is what stays correct.
    strong = diff >= peak * 0.5
    ys, xs = np.nonzero(strong)
    top = ys.min()
    band = ys <= top + BAND
    ys, xs = ys[band], xs[band]
    w = diff[ys, xs]
    return (float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum()), peak)


def keyboard_roi(cam, kb, dark, settle: float, samples: int) -> np.ndarray:
    """Light every LED at once; whatever brightens is the keyboard."""
    kb.fill((255, 255, 255))
    kb.flush(force=True)
    time.sleep(settle * 3)
    allon = cam.average(samples)
    kb.fill((0, 0, 0))
    kb.flush(force=True)
    time.sleep(settle)
    diff = cv2.GaussianBlur(np.clip(allon - dark, 0, None), (0, 0), 5.0)
    thresh = diff.max() * 0.10
    mask = (diff >= thresh).astype(np.uint8)
    # keep the largest blob only, then grow it a little so edge keys are not clipped
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = (labels == biggest).astype(np.uint8)
    mask = cv2.dilate(mask, np.ones((25, 25), np.uint8))
    x, y, w, h = cv2.boundingRect(mask)
    print(f"  keyboard ROI: x={x} y={y} w={w} h={h}, {int(mask.sum())} px", flush=True)
    return mask.astype(np.float32)


def measure(leds, settle: float, samples: int, redark_every: int,
            send_mask: bool = False) -> dict:
    cam = Camera()
    results: dict[int, dict] = {}
    try:
        with Keyboard(send_mask=send_mask) as kb:
            kb.take_control()
            kb.fill((0, 0, 0))
            kb.flush(force=True)
            time.sleep(0.4)
            dark = cam.average(samples)
            roi = keyboard_roi(cam, kb, dark, settle, samples)
            dark = cam.average(samples)

            for i, led in enumerate(leds):
                if redark_every and i and i % redark_every == 0:
                    kb.fill((0, 0, 0))
                    kb.flush()
                    time.sleep(settle)
                    dark = cam.average(samples)

                kb.fill((0, 0, 0))
                kb.set(led, (255, 255, 255))
                kb.flush(force=True)
                time.sleep(settle)
                lit = cam.average(samples)
                x, y, score = locate(lit, dark, roi)
                results[led] = {"x": x, "y": y, "score": score}
                name = layout.NAMES.get(led, "")
                print(f"  0x{led:02x} {name:<20} x={x:7.1f} y={y:7.1f} score={score:6.1f}",
                      flush=True)

            kb.fill((0, 0, 0))
            kb.flush(force=True)
    finally:
        cam.release()
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", action="store_true", help="a handful of known keys only")
    ap.add_argument("--leds", nargs="*", default=None, help="specific ids, e.g. 0x22")
    ap.add_argument("--mask", action="store_true", help="send the LED enable mask too")
    ap.add_argument("--settle", type=float, default=0.25)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--redark-every", type=int, default=16)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "positions.json"))
    args = ap.parse_args()

    if args.leds:
        leds = [int(v, 16) for v in args.leds]
    elif args.trial:
        # spread across the board: far left, middle, far right, top and bottom
        wanted = ["ESC", "1", "0", "G", "SPACE", "F1", "F12"]
        leds = []
        for name in wanted:
            try:
                leds.append(layout.by_name(name))
            except KeyError:
                pass
        leds = list(dict.fromkeys(leds))
    else:
        leds = list(layout.ALL_LEDS)

    print(f"measuring {len(leds)} LEDs")
    results = measure(leds, args.settle, args.samples, args.redark_every,
                      send_mask=args.mask)
    with open(args.out, "w") as fh:
        json.dump({f"0x{k:02x}": v for k, v in results.items()}, fh, indent=1)
    print(f"\nwrote {args.out}")

    scores = [r["score"] for r in results.values()]
    weak = [f"0x{k:02x}" for k, r in results.items() if r["score"] < 8]
    print(f"score min={min(scores):.1f} median={sorted(scores)[len(scores)//2]:.1f} "
          f"max={max(scores):.1f}")
    if weak:
        print(f"weak/not seen ({len(weak)}): {' '.join(weak)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
