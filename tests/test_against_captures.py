"""Check our encoders reproduce the bytes the stock Alienware software sent.

The captures under `tests/fixtures/v3/` are the only ground truth available, so these tests replay
them: build the packet our library would send and require it to equal, byte for
byte, what AWCC put on the wire.  No hardware needed.

Run with: python3 -m pytest tests/ -q   (or python3 tests/test_against_captures.py)
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from awcfree_lib import layout  # noqa: E402
from awcfree_lib.protocol import v4, v5  # noqa: E402

CAPTURES = ROOT / "tests/fixtures/v3"

_LINE = re.compile(
    r"^(?P<ep>\d+)\t(?P<dir>Out|In)\s+\(USB URB Function: \d+\)\t"
    r"[\d.]+\t(?P<len>\d+)\t(?P<hex>(?:[0-9a-f]{2} ?)+)",
    re.I,
)


def load(name: str, *, direction: str = "Out", length: int | None = None) -> list[bytes]:
    packets = []
    with open(CAPTURES / name, errors="replace") as fh:
        for raw in fh:
            m = _LINE.match(raw.rstrip("\n"))
            if not m or m.group("dir") != direction:
                continue
            data = bytes.fromhex(m.group("hex").replace(" ", ""))
            if length is not None and len(data) != length:
                continue
            packets.append(data)
    return packets


def check(name, got, want):
    if got != want:
        raise AssertionError(
            f"{name}\n  got  {bytes(got).rstrip(bytes(1)).hex(' ')}"
            f"\n  want {bytes(want).rstrip(bytes(1)).hex(' ')}"
        )
    print(f"  ok  {name}")


# --- v4 chassis -------------------------------------------------------------
def test_v4_logo_static():
    """`logoback/color/white` -- the lid logo set to white."""
    cap = load("logoback/color/white", length=33)
    check("v4 animation start", v4.animation(v4.CTL_START, 0xFFFF), cap[0])
    check("v4 zone select touchpad", v4.zone_select([v4.ZONE_TOUCHPAD]), cap[1])
    check("v4 zone select logo", v4.zone_select([v4.ZONE_LOGO]), cap[3])
    check(
        "v4 static white on logo",
        v4.add_action([v4.keyframe(v4.ACTION_COLOUR, (0xFF, 0xFF, 0xFF),
                                  v4.DURATION_STATIC, v4.TEMPO_CHASSIS)]),
        cap[4],
    )
    check("v4 finish+play", v4.animation(v4.CTL_FINISH_PLAY, 0x00FF), cap[5])


def test_v4_power_profiles():
    """`statusled/full-flow-black-save-present` -- all six power profiles."""
    cap = load("statusled/full-flow-black-save-present", length=33)
    # Each profile is five packets: remove, start, zone select, action, save.
    ids_seen = []
    for i in range(0, 30, 5):
        remove, start, zsel, action, save = cap[i : i + 5]
        pid = (remove[4] << 8) | remove[5]
        ids_seen.append(pid)
        check(f"v4 power 0x{pid:02x} remove",
              v4.power_profile(v4.CTL_REMOVE, pid), remove)
        check(f"v4 power 0x{pid:02x} start",
              v4.power_profile(v4.CTL_START, pid), start)
        check(f"v4 power 0x{pid:02x} zone", v4.zone_select([v4.ZONE_POWER]), zsel)
        check(f"v4 power 0x{pid:02x} save",
              v4.power_profile(v4.CTL_SAVE, pid), save)
        # the action kind AWCC used must match our table
        assert action[2] == v4.POWER_PROFILE_ACTION[pid], (
            f"0x{pid:02x}: capture uses action 0x{action[2]:02x}, "
            f"table says 0x{v4.POWER_PROFILE_ACTION[pid]:02x}"
        )
    assert ids_seen == list(v4.POWER_PROFILE_IDS), ids_seen
    print(f"  ok  v4 power profile ids {[hex(i) for i in ids_seen]}")


def test_v4_multi_keyframe():
    """A two-colour morph rides in one report -- AWCC does it, so must we."""
    cap = load("statusled/full-flow-white-plugged-purple-battrey-save-present", length=33)
    # Profile 0x5d is the white->purple morph.  Several profiles hold two keyframes,
    # but the breathing ones (0x5b, 0x5e) morph a colour to black, so pick the packet
    # where both keyframes carry a real colour.
    def two_real_colours(pkt):
        frames = list(v4.iter_keyframes(pkt))
        return (
            len(frames) == 2
            and frames[0][3] != frames[1][3]
            and all(f[3] != (0, 0, 0) for f in frames)
        )

    target = next(p for p in cap if p[1] == 0x24 and two_real_colours(p))
    frames = [
        v4.keyframe(v4.ACTION_MORPH, (0xFF, 0xFF, 0xFF),
                    v4.DURATION_POWER_MORPH, v4.TEMPO_POWER),
        v4.keyframe(v4.ACTION_MORPH, (0xFF, 0x00, 0xFF),
                    v4.DURATION_POWER_MORPH, v4.TEMPO_POWER),
    ]
    check("v4 two keyframes in one report", v4.add_action(frames), target)
    decoded = list(v4.iter_keyframes(target))
    assert len(decoded) == 2, decoded
    print(f"  ok  v4 decoded back to {len(decoded)} keyframes")


def test_v4_two_colour_morph_matches_awcc():
    """A pair morph must be morph(A) + colour(B, duration 1), not two morphs.

    Two morph keyframes are accepted by the controller but animate as two separate
    fades. This is the shape the stock software actually sends.
    """
    for name, a, b in (
        ("touchpad/morph/morph-gree-to-purple", (0x00, 0xFF, 0x00), (0xFF, 0x00, 0xFF)),
        ("touchpad/morph/morph-purple-to-green", (0xFF, 0x00, 0xFF), (0x00, 0xFF, 0x00)),
    ):
        cap = load(name, length=33)
        target = next(p for p in cap if p[1] == 0x24 and p[2] == v4.ACTION_MORPH)
        check(f"v4 pair morph {name.rsplit('/', 1)[1]}",
              v4.add_action(v4.morph_pair_frames(a, b)), target)
    frames = v4.morph_pair_frames((1, 2, 3), (4, 5, 6))
    assert frames[0][0] == v4.ACTION_MORPH, frames[0]
    assert frames[1][0] == v4.ACTION_COLOUR, frames[1]
    assert (frames[1][1] << 8) | frames[1][2] == 1, "second frame duration must be 1"
    print("  ok  second keyframe is action 0x00 with duration 1")


def test_v4_morph_timing_presets():
    """The duration and tempo captures must map onto our named constants."""
    for name, duration, tempo in (
        ("touchpad/morph/duration/low", v4.DURATION_MORPH_LOW, v4.TEMPO_MORPH_LOW),
        ("touchpad/morph/duration/medium", v4.DURATION_MORPH_MEDIUM, v4.TEMPO_MORPH_LOW),
        ("touchpad/morph/duration/high", v4.DURATION_MORPH_HIGH, v4.TEMPO_MORPH_LOW),
        ("touchpad/morph/tempo/high", v4.DURATION_MORPH_HIGH, v4.TEMPO_MORPH_HIGH),
    ):
        cap = load(name, length=33)
        target = next(p for p in cap if p[1] == 0x24 and p[2] == v4.ACTION_MORPH)
        got = list(v4.iter_keyframes(target))[0]
        assert got[1] == duration, f"{name}: duration {got[1]:#06x} != {duration:#06x}"
        assert got[2] == tempo, f"{name}: tempo {got[2]:#06x} != {tempo:#06x}"
    print("  ok  morph duration and tempo presets match the captures")


def test_v4_spectrum_matches_awcc():
    """Three or more colours really are all morph keyframes."""
    cap = load("touchpad/spectrum/duration/medium", length=33)
    captured = [p for p in cap if p[1] == 0x24 and p[2] == v4.ACTION_MORPH]
    ours = v4.add_actions(v4.spectrum_frames(v4.SPECTRUM_COLOURS))
    assert len(ours) == len(captured), (len(ours), len(captured))
    for i, (got, want) in enumerate(zip(ours, captured)):
        check(f"v4 spectrum report {i}", got, want)


def test_v4_power_morph_differs_from_zone_morph():
    """The two contexts encode a morph differently, and both forms are captured."""
    power = load("statusled/full-flow-white-plugged-purple-battrey-save-present",
                 length=33)
    pair = next(p for p in power if p[1] == 0x24
                and len(list(v4.iter_keyframes(p))) == 2
                and all(f[3] != (0, 0, 0) for f in v4.iter_keyframes(p)))
    kinds = [f[0] for f in v4.iter_keyframes(pair)]
    assert kinds == [v4.ACTION_MORPH, v4.ACTION_MORPH], kinds

    zone = load("touchpad/morph/morph-gree-to-purple", length=33)
    target = next(p for p in zone if p[1] == 0x24 and p[2] == v4.ACTION_MORPH)
    kinds = [f[0] for f in v4.iter_keyframes(target)]
    assert kinds == [v4.ACTION_MORPH, v4.ACTION_COLOUR], kinds
    print("  ok  power profiles morph+morph, zone animations morph+colour")


def test_v4_pulse_timing_matches_awcc():
    """Pulse must use the tempo AWCC uses, not the generic chassis one."""
    cap = load("logoback/color/black", length=33)
    target = next(p for p in cap if p[1] == 0x24 and p[2] == v4.ACTION_PULSE)
    action, duration, tempo, _ = next(iter(v4.iter_keyframes(target)))
    assert duration == v4.DURATION_PULSE, f"{duration:#06x} != {v4.DURATION_PULSE:#06x}"
    assert tempo == v4.TEMPO_PULSE, f"{tempo:#06x} != {v4.TEMPO_PULSE:#06x}"
    assert v4.TEMPO_PULSE != v4.TEMPO_CHASSIS, "the two must not be conflated again"
    ours = v4.add_action([v4.keyframe(v4.ACTION_PULSE, (0, 0, 0),
                                      v4.DURATION_PULSE, v4.TEMPO_PULSE)])
    check("v4 pulse keyframe", ours, target)


def test_v4_touchpad_morph():
    """`touchpad/morph/morph-gree-to-purple` -- keyframe packing on the touchpad."""
    cap = load("touchpad/morph/morph-gree-to-purple", length=33)
    actions = [p for p in cap if p[1] == 0x24]
    assert actions, "no 0x24 packets in the capture"
    for pkt in actions:
        frames = list(v4.iter_keyframes(pkt))
        rebuilt = v4.add_action([v4.keyframe(a, rgb, d, t) for a, d, t, rgb in frames])
        check(f"v4 round-trip {len(frames)} keyframe(s)", rebuilt, pkt)


# --- v5 keyboard ------------------------------------------------------------
def test_v5_handshake_and_commit():
    cap = load("perkey-rgb/color/all black", length=64)
    check("v5 reset", v5.RESET, cap[0])
    check("v5 status", v5.STATUS, cap[1])
    check("v5 loop", v5.LOOP, cap[-2])
    check("v5 update", v5.UPDATE, cap[-1])


def test_v5_never_emits_the_cc83_command():
    """Nothing we send may contain `cc 83`.

    The bare three-byte form of this command, reconstructed from alienfx-tools'
    listing, put an m16 R2's backlight into a state that only a reboot cleared.
    Until that is understood the library must not emit it at all, and a comment is
    not enough to guarantee that.
    """
    everything = []
    everything += v5.static_sequence({0x15: (255, 0, 0)}, background=(0, 0, 0),
                                     send_mask=True, order=layout.ALL_LEDS)
    everything += [v5.RESET, v5.STATUS, v5.LOOP, v5.UPDATE, v5.EFFECT_OFF]
    everything += [v5.effect(name) for name in v5.EFFECTS]
    offenders = [p.hex(" ") for p in everything if p[1] == 0x83]
    assert not offenders, f"these packets carry cc 83: {offenders}"
    print(f"  ok  none of {len(everything)} generated packets carry cc 83")


def test_v5_colour_frames():
    """Our colour frames must match AWCC's, including id order and grouping."""
    cap = load("perkey-rgb/color/all black", length=64)
    captured = [p for p in cap if p[1] == 0x8C and p[2] == 0x02]
    ours = v5.colour_frames(
        {led: (0, 0, 0) for led in layout.ALL_LEDS}, order=layout.ALL_LEDS
    )
    assert len(ours) == len(captured), (
        f"we emit {len(ours)} colour frames, AWCC emitted {len(captured)}"
    )
    for i, (got, want) in enumerate(zip(ours, captured)):
        check(f"v5 colour frame {i}", got, want)


def test_v5_global_block():
    cap = load("perkey-rgb/color/all black", length=64)
    captured = next(p for p in cap if p[1] == 0x8C and p[2] == 0x01)
    check("v5 global block (black)", v5.global_block((0, 0, 0)), captured)


def test_v5_mask_payload():
    """We must be able to reproduce AWCC's three selection reports verbatim."""
    cap = load("perkey-rgb/color/all black", length=64)
    captured = [p for p in cap if p[1] == 0x8C and p[2] in (0x05, 0x06, 0x07)]
    assert len(captured) == 3, len(captured)
    payload = []
    for pkt in captured:
        payload += list(pkt[4:64])
    assert len(payload) == v5.MASK_SLOTS, len(payload)
    rebuilt = v5.mask_frames(payload)
    for i, (got, want) in enumerate(zip(rebuilt, captured)):
        check(f"v5 enable report {i}", got, want)
    # The decoded meaning: slot i enables wire id i+1, and exactly the 92 real LEDs
    # are enabled.  If this holds, mask_for() can rebuild AWCC's bytes from ids alone.
    enabled = {i + 1 for i, v in enumerate(payload) if v}
    assert enabled == set(layout.ALL_LEDS), (
        f"mask does not decode to the 92 LEDs\n"
        f"  only in mask:   {sorted(hex(x) for x in enabled - set(layout.ALL_LEDS))}\n"
        f"  only in layout: {sorted(hex(x) for x in set(layout.ALL_LEDS) - enabled)}"
    )
    print(f"  ok  mask decodes to exactly the {len(enabled)} known LEDs (slot i -> id i+1)")
    for i, (got, want) in enumerate(zip(v5.mask_for(layout.ALL_LEDS), captured)):
        check(f"v5 mask_for() rebuilds report {i} from ids alone", got, want)


def test_v5_effect_carries_two_colours():
    """The pair-taking effects must actually put both colours on the wire."""
    a, b = (0x11, 0x22, 0x33), (0xAA, 0xBB, 0xCC)
    for name, uses in v5.EFFECT_COLOURS.items():
        pkt = v5.effect(name, colour_mode=uses, primary=a, secondary=b)
        assert pkt[2] == v5.EFFECTS[name], f"{name}: wrong effect type byte"
        assert pkt[9] == uses - 1, f"{name}: colour mode byte is {pkt[9]}, want {uses-1}"
        assert tuple(pkt[10:13]) == a, f"{name}: primary not at offset 10"
        assert tuple(pkt[13:16]) == b, f"{name}: secondary not at offset 13"
    two = [n for n, u in v5.EFFECT_COLOURS.items() if u == 2]
    assert set(two) == {"double_wave", "morph"}, two
    print(f"  ok  all {len(v5.EFFECT_COLOURS)} effects encode both colours; "
          f"{two} declare a pair")


def test_v5_effect_mode_changes_the_packet():
    """A one-colour and a two-colour request must not produce identical bytes."""
    a, b = (255, 0, 0), (0, 0, 255)
    one = v5.effect("morph", colour_mode=1, primary=a, secondary=b)
    pair = v5.effect("morph", colour_mode=2, primary=a, secondary=b)
    assert one != pair, "colour mode is not reaching the wire"
    assert one[9] == 0 and pair[9] == 1
    print("  ok  colour mode is visible in the packet")


def test_layout_matches_capture():
    """`layout.ALL_LEDS` must be exactly the ids AWCC writes -- no more, no fewer."""
    cap = load("perkey-rgb/color/all black", length=64)
    wire = []
    for pkt in cap:
        if pkt[1] == 0x8C and pkt[2] == 0x02:
            for led, _rgb in v5.iter_records(pkt):
                wire.append(led)
    assert len(wire) == 92, f"expected 92 LEDs on the wire, saw {len(wire)}"
    assert tuple(wire) == layout.ALL_LEDS, (
        f"layout disagrees with the capture\n"
        f"  only in layout: {sorted(set(layout.ALL_LEDS) - set(wire))}\n"
        f"  only on wire:   {sorted(set(wire) - set(layout.ALL_LEDS))}"
    )
    print(f"  ok  layout matches capture exactly ({len(wire)} LEDs)")


def test_canvas_cells_are_distinct():
    """Adjacent unit-width keys must not share a grid cell."""
    from awcfree_lib.canvas import Canvas

    canvas = Canvas()
    # every wired LED must land in its own cell: the measurement found no two keys
    # closer than 18px, so any collision here is a fitting bug, not real geometry.
    seen: dict[tuple[int, int], int] = {}
    clashes = []
    for led, pos in layout.CELLS.items():
        if pos in seen:
            clashes.append((pos, seen[pos], led))
        seen[pos] = led
    assert not clashes, f"cells shared by two LEDs: {clashes}"
    print(f"  ok  all {len(layout.CELLS)} wired LEDs occupy distinct cells")
    assert len(canvas.lit_cells) == len(layout.CELLS), (
        f"{len(canvas.lit_cells)} lit cells for {len(layout.CELLS)} LEDs"
    )
    print(f"  ok  canvas has {len(canvas.lit_cells)} lit cells")



def test_v4_power_breathing_is_morph_to_black():
    """A one-colour morph profile must fade to black, the way AWCC does it."""
    cap = load("statusled/full-flow-white-plugged-purple-battrey-save-present", length=33)
    # 0x5e is the battery breathing profile; purple in this capture.
    groups = [cap[i : i + 5] for i in range(0, 30, 5)]
    group = next(g for g in groups if ((g[0][4] << 8) | g[0][5]) == 0x5E)
    ours = v4.power_profile_sequence(0x5E, [(0xFF, 0x00, 0xFF)])
    for i, (got, want) in enumerate(zip(ours, group)):
        check(f"v4 breathing profile 0x5e packet {i}", got, want)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        print(f"{fn.__name__}:")
        try:
            fn()
        except AssertionError as exc:
            print(f"  FAIL {exc}")
            failed.append(fn.__name__)
    print()
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
