"""Bundled recorded sound packs, with shuffle bags and key-specific accents."""
from __future__ import annotations

from array import array
from functools import lru_cache
import json
from pathlib import Path
import random
import sys
import wave

RATE = 24000
ASSETS = Path(__file__).with_name("assets")
MANIFEST = json.loads((ASSETS / "manifest.json").read_text())
PACKS = {
    "farts": ("Fart Lab", "Recorded foley: short splutters, raspberries and longer rumbles.", "💨"),
    "gaming": ("Gaming Keyboard", "32 recorded Cherry keyboard strikes, with a double clack for Enter.", "⌨"),
    "guns": ("Freedom mode", "1911, AR-15, AK-47, shotgun and PPQ recordings. Enter unleashes a burst.", "🇺🇸"),
}
ROLES = ("normal", "enter", "space", "backspace", "modifier")


def key_role(name: str) -> str:
    if name in ("ENTER", "KPENTER"): return "enter"
    if name == "SPACE": return "space"
    if name in ("BACKSPACE", "DELETE"): return "backspace"
    if name in ("TAB", "CAPSLOCK", "SHIFT", "LSHIFT", "RSHIFT", "CTRL",
                "LCTRL", "RCTRL", "ALT", "LALT", "RALT", "META", "WIN"):
        return "modifier"
    return "normal"


@lru_cache(maxsize=15)
def sample_bank(pack, role):
    if pack not in PACKS or role not in ROLES:
        raise ValueError("Unknown sound pack or key role")
    clips = MANIFEST["packs"][pack]["clips"]
    ordered = sorted(range(len(clips)), key=lambda i: clips[i]["end"] - clips[i]["start"])
    if pack == "guns":
        kind = "burst" if role == "enter" else "shotgun" if role == "space" else None
        selected = [i for i in ordered if clips[i].get("kind") == kind] if kind else [
            i for i in ordered if clips[i].get("kind") != "burst"]
        if role == "backspace": selected = [i for i in selected if "pistol" in clips[i]["weapon"]]
        if role == "modifier": selected = selected[:max(2, len(selected) // 2)]
        return tuple(selected)
    # Keep the longer recorded performances for the Enter finale.
    if pack != "gaming":
        cutoff = 1.5 if pack == "farts" else 1.0
        long = [i for i in ordered if clips[i]["end"] - clips[i]["start"] >= cutoff]
        short = [i for i in ordered if i not in long]
        if role == "enter" and long: return tuple(long)
        if role in ("normal", "backspace") and short: return tuple(short)
    if role == "modifier": return tuple(ordered[:max(2, len(ordered) // 2)])
    return tuple(ordered)


def variant_count(pack, role):
    return len(sample_bank(pack, role))


class VariantPicker:
    """Shuffle every recording before reuse, avoiding repeats at bag boundaries."""
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.bags = {}
        self.last = {}

    def next(self, pack, role):
        identity = (pack, role)
        bag = self.bags.get(identity)
        if not bag:
            bag = list(range(variant_count(pack, role)))
            self.rng.shuffle(bag)
            if len(bag) > 1 and bag[-1] == self.last.get(identity):
                bag[-1], bag[0] = bag[0], bag[-1]
            self.bags[identity] = bag
        variant = bag.pop()
        self.last[identity] = variant
        return variant


@lru_cache(maxsize=64)
def recording(pack, index):
    path = ASSETS / MANIFEST["packs"][pack]["clips"][index]["file"]
    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != RATE:
            raise ValueError(f"Unsupported recording format: {path.name}")
        pcm = array("h")
        pcm.frombytes(stream.readframes(stream.getnframes()))
    if sys.byteorder != "little": pcm.byteswap()
    return array("f", (value / 32768 for value in pcm))


@lru_cache(maxsize=128)
def _sound(pack, role, variant):
    bank = sample_bank(pack, role)
    samples = recording(pack, bank[variant % len(bank)])
    gain = 1.08 if role == "enter" else .7 if role == "modifier" else .82
    result = array("f", (value * gain for value in samples))
    if role == "enter" and pack == "gaming":
        # An accented double strike uses two existing recordings, not synthesis.
        result.extend([0.0] * (RATE // 40))
        second = recording(pack, bank[(variant + 1) % len(bank)])
        result.extend(value * gain for value in second)
    return result


def sound_for_key(pack, name, variant, accented=True):
    role = key_role(name)
    if role == "enter" and not accented: role = "normal"
    return _sound(pack, role, variant)
