"""Packet encoders for the AlienFX "v4" chassis controller (AW-ELC 187c:0551).

33-byte HID *output* reports.  The report id is 0, so the id byte is not part of
the packet -- the transport prepends it.  Every packet starts with the 0x03
preamble.

Byte-level sources, in order of authority:
  * the captures under `tests/fixtures/v3/` -- `logoback/`, `touchpad/` and especially
    `statusled/full-flow-*`, which is where the 0x22 power-button surface and the
    multi-keyframe form of 0x24 come from.
  * T-Troll/alienfx-tools `alienfx-controls.h` (MIT) and tr1xem/AWCC
    `include/LightFX.h` (both agree on 0x20/0x21/0x23/0x24/0x26).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

LEN = 33
PREAMBLE = 0x03

Rgb = tuple[int, int, int]

# --- zones ------------------------------------------------------------------
# Confirmed against the captures: 0x00 is written by everything under
# `tests/fixtures/v3/touchpad/`, 0x02 by `tests/fixtures/v3/logoback/`, and 0x04 only ever appears inside the
# 0x22 power-button transactions in `tests/fixtures/v3/statusled/`.  0x01 and 0x03 are accepted
# by the encoder but were never seen in a capture on this machine; use
# `awcfree probe-zones` to find out what, if anything, they drive.
ZONE_TOUCHPAD = 0x00
ZONE_LOGO = 0x02  # the illuminated emblem on the lid
ZONE_POWER = 0x04  # the illuminated power button
CHASSIS_ZONES: tuple[int, ...] = (ZONE_TOUCHPAD, ZONE_LOGO)
ZONE_NAMES: dict[str, int] = {
    "touchpad": ZONE_TOUCHPAD,
    "logo": ZONE_LOGO,
    "lid": ZONE_LOGO,
    "power": ZONE_POWER,
}

# --- commands ---------------------------------------------------------------
_REQUEST = 0x20
_ANIMATION = 0x21
_POWER_PROFILE = 0x22
_ZONE_SELECT = 0x23
_ADD_ACTION = 0x24
_SET_DIM = 0x26

# Sub-commands shared by 0x21 (animations) and 0x22 (power-button profiles).  That
# they are shared is a finding from `tests/fixtures/v3/statusled/full-flow-*`, where 0x22 is
# driven with exactly the same 01/02/04 codes as 0x21.
CTL_START = 0x01
CTL_SAVE = 0x02
CTL_FINISH_PLAY = 0x03
CTL_REMOVE = 0x04
CTL_PLAY = 0x05
CTL_SET_DEFAULT = 0x06
CTL_SET_STARTUP = 0x07

# Request sub-commands for 0x20.
REQ_FIRMWARE = 0x00
REQ_STATUS = 0x01
REQ_ELC_CONFIG = 0x02
REQ_ANIMATION_COUNT = 0x03

# Action kinds for 0x24.
ACTION_COLOUR = 0x00
ACTION_PULSE = 0x01
ACTION_MORPH = 0x02

#: Animation id AWCC uses for the chassis zones; both the statusled captures and
#: tr1xem/AWCC settle on this one.
ANIMATION_ID = 0x0061

#: Scratch id for effects that should not be persisted.
ANIMATION_ID_VOLATILE = 0xFFFF

# --- power-button profiles --------------------------------------------------
# Six ids, each a standing profile the firmware selects on its own according to
# the power state.  Decoded from `tests/fixtures/v3/statusled/full-flow-*`: the "black" capture
# writes 0x5b..0x60 in order with a fixed action kind per id, and the
# "white-plugged / purple-battery" capture gives the white ones to 0x5b-0x5d and
# the purple ones to 0x5e-0x60.
#
# The split into an AC trio and a battery trio is solid.  The *names* within each
# trio are inferred from the action kind AWCC pairs with each id (morph for a
# breathing sleep light, static for idle, pulse for a warning) and have not been
# confirmed by watching the hardware, so they may need swapping.
POWER_PROFILES: dict[str, int] = {
    "ac_sleep": 0x5B,
    "ac_on": 0x5C,
    "ac_charging": 0x5D,
    "battery_sleep": 0x5E,
    "battery_on": 0x5F,
    "battery_low": 0x60,
}
POWER_PROFILE_IDS: tuple[int, ...] = tuple(POWER_PROFILES.values())

#: The action kind AWCC uses for each profile id.
POWER_PROFILE_ACTION: dict[int, int] = {
    0x5B: ACTION_MORPH,
    0x5C: ACTION_COLOUR,
    0x5D: ACTION_MORPH,
    0x5E: ACTION_MORPH,
    0x5F: ACTION_COLOUR,
    0x60: ACTION_PULSE,
}

# Durations and tempos lifted from the captures so our packets match AWCC's.
DURATION_STATIC = 0x07D0
TEMPO_CHASSIS = 0x00FA
TEMPO_POWER = 0x0064

# Morph timings, read straight off `tests/fixtures/v3/touchpad/morph/duration/*` and `tempo/*`.
# Duration is how long a leg of the fade lasts, so a larger number is a slower
# morph; tempo runs the other way, which is why "high" is the smaller value.
DURATION_MORPH_LOW = 0x07CF
DURATION_MORPH_MEDIUM = 0x0BB7
DURATION_MORPH_HIGH = 0x1387
DURATION_MORPH = DURATION_MORPH_MEDIUM
TEMPO_MORPH_LOW = 0x00FA
TEMPO_MORPH_HIGH = 0x0064
TEMPO_MORPH = TEMPO_MORPH_HIGH

# Pulse, from `tests/fixtures/v3/logoback/color/black` -- the only pulse AWCC sends in any
# capture. We were using TEMPO_CHASSIS (0x00FA) here, which pulses roughly two and
# a half times too fast.
DURATION_PULSE = 0x07D0
TEMPO_PULSE = 0x0064

# The power-button profiles morph differently again: duration 0x03E8, and *two*
# action-0x02 keyframes rather than the morph-then-colour pair a zone animation
# uses.  Both shapes are in the captures, so the difference is real and not a
# transcription slip -- see `tests/fixtures/v3/statusled/full-flow-*` against
# `tests/fixtures/v3/touchpad/morph/*`.
DURATION_POWER_MORPH = 0x03E8

# Spectrum runs a different pair entirely: short legs and a very low tempo number.
DURATION_SPECTRUM_LOW = 0x00D6
DURATION_SPECTRUM_MEDIUM = 0x0282
TEMPO_SPECTRUM = 0x000F

#: A finished-and-played transaction is committed under this id, not under the id
#: it was opened with. AWCC opens with 0xFFFF and closes with 0x00FF in every
#: capture; closing with 0xFFFF is accepted but is not what the stock software does.
ANIMATION_ID_PLAY = 0x00FF

#: Keyframe is 8 bytes and the first starts at offset 2, so this many fit.
MAX_KEYFRAMES = (LEN - 2) // 8


def _pad(prefix: Sequence[int]) -> bytes:
    if len(prefix) > LEN:
        raise ValueError(f"v4 packet longer than {LEN} bytes: {len(prefix)}")
    buf = bytearray(LEN)
    buf[: len(prefix)] = bytes(prefix)
    return bytes(buf)


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _u16(v: int) -> tuple[int, int]:
    return (v >> 8) & 0xFF, v & 0xFF


def request(kind: int) -> bytes:
    """`03 20 <kind>` -- firmware, status, ELC config or animation count."""
    return _pad([PREAMBLE, _REQUEST, kind])


def animation(ctl: int, animation_id: int = ANIMATION_ID) -> bytes:
    """`03 21 00 <ctl> <id>` -- open, save, play or drop a stored animation."""
    hi, lo = _u16(animation_id)
    return _pad([PREAMBLE, _ANIMATION, 0x00, ctl, hi, lo])


def power_profile(ctl: int, profile_id: int) -> bytes:
    """`03 22 00 <ctl> <id>` -- the same verbs as `animation`, for the power button."""
    hi, lo = _u16(profile_id)
    return _pad([PREAMBLE, _POWER_PROFILE, 0x00, ctl, hi, lo])


def zone_select(zones: Sequence[int], loop: int = 1) -> bytes:
    """`03 23 <loop> <count> <zones...>` -- pick the zones the next actions apply to."""
    if not zones:
        raise ValueError("zone_select needs at least one zone")
    hi, lo = _u16(len(zones))
    return _pad([PREAMBLE, _ZONE_SELECT, loop, hi, lo, *zones])


def keyframe(
    action: int, colour: Rgb, duration: int = DURATION_STATIC, tempo: int = TEMPO_CHASSIS
) -> list[int]:
    """One 8-byte keyframe: `<action> <duration:2> <tempo:2> <r> <g> <b>`."""
    dhi, dlo = _u16(duration)
    thi, tlo = _u16(tempo)
    r, g, b = (_clamp(c) for c in colour)
    return [action, dhi, dlo, thi, tlo, r, g, b]


def add_action(frames: Sequence[Sequence[int]]) -> bytes:
    """`03 24` carrying up to three keyframes in one report.

    Packing several keyframes into a single report is what AWCC itself does -- the
    two-colour morphs in `tests/fixtures/v3/statusled/full-flow-*` arrive as one 18-byte packet
    holding two frames.  tr1xem/AWCC and alienfx-tools both send one keyframe per
    report instead, which works but costs a report per frame.
    """
    if not frames:
        raise ValueError("add_action needs at least one keyframe")
    if len(frames) > MAX_KEYFRAMES:
        raise ValueError(f"at most {MAX_KEYFRAMES} keyframes per report, got {len(frames)}")
    payload: list[int] = [PREAMBLE, _ADD_ACTION]
    for f in frames:
        if len(f) != 8:
            raise ValueError(f"keyframe must be 8 bytes, got {len(f)}")
        payload += list(f)
    return _pad(payload)


def add_actions(frames: Sequence[Sequence[int]]) -> list[bytes]:
    """Split any number of keyframes across as many `03 24` reports as needed."""
    return [
        add_action(frames[i : i + MAX_KEYFRAMES])
        for i in range(0, len(frames), MAX_KEYFRAMES)
    ]


def set_dim(level: int, zones: Sequence[int]) -> bytes:
    """`03 26 <level> <count> <zones...>` -- brightness, 0 to 255."""
    hi, lo = _u16(len(zones))
    return _pad([PREAMBLE, _SET_DIM, _clamp(level), hi, lo, *zones])


# --- composed transactions --------------------------------------------------


def static_sequence(
    zone_colours: dict[int, Rgb],
    *,
    animation_id: int = ANIMATION_ID_VOLATILE,
    persist: bool = False,
) -> list[bytes]:
    """Set one flat colour per zone.

    With `persist` the transaction is saved and marked default so it survives a
    reboot, mirroring what AWCC does at the end of its status-LED flow; otherwise
    it is finished-and-played, which is the cheap volatile path.
    """
    out = [animation(CTL_START, animation_id)]
    for zone, colour in zone_colours.items():
        out.append(zone_select([zone]))
        out.append(add_action([keyframe(ACTION_COLOUR, colour)]))
    if persist:
        out.append(animation(CTL_SAVE, animation_id))
        out.append(animation(CTL_SET_DEFAULT, animation_id))
    else:
        out.append(animation(CTL_FINISH_PLAY, ANIMATION_ID_PLAY))
    return out


def keyframe_sequence(
    zone: int,
    frames: Sequence[Sequence[int]],
    *,
    animation_id: int = ANIMATION_ID_VOLATILE,
    persist: bool = False,
) -> list[bytes]:
    """Run an arbitrary keyframe chain on one zone -- morph, spectrum, pulse."""
    out = [animation(CTL_START, animation_id), zone_select([zone])]
    out += add_actions(frames)
    if persist:
        out += [animation(CTL_SAVE, animation_id), animation(CTL_SET_DEFAULT, animation_id)]
    else:
        out.append(animation(CTL_FINISH_PLAY, ANIMATION_ID_PLAY))
    return out


def power_profile_sequence(profile_id: int, colours: Sequence[Rgb]) -> list[bytes]:
    """Write one power-button profile, following AWCC's remove/start/save order.

    The action kind comes from `POWER_PROFILE_ACTION` so the result matches what
    AWCC writes for that id.  A morph id wants two colours; the others want one.
    """
    action = POWER_PROFILE_ACTION.get(profile_id, ACTION_COLOUR)
    if not colours:
        raise ValueError("need at least one colour")
    if action == ACTION_MORPH:
        pair = list(colours[:2])
        if len(pair) == 1:
            # AWCC's own breathing profiles (0x5b, 0x5e) morph the colour to black
            # and back, so a single colour means breathe, not hold.  Duplicating the
            # colour instead would fade it to itself and look static.
            pair = [pair[0], (0, 0, 0)]
        frames = [
            keyframe(ACTION_MORPH, c, DURATION_POWER_MORPH, TEMPO_POWER) for c in pair
        ]
    else:
        frames = [keyframe(action, colours[0], DURATION_STATIC, TEMPO_POWER)]
    return [
        power_profile(CTL_REMOVE, profile_id),
        power_profile(CTL_START, profile_id),
        zone_select([ZONE_POWER]),
        add_action(frames),
        power_profile(CTL_SAVE, profile_id),
    ]


def morph_pair_frames(
    first: Rgb, second: Rgb,
    duration: int = DURATION_MORPH, tempo: int = TEMPO_MORPH,
) -> list[list[int]]:
    """The two keyframes AWCC uses to fade between a pair of colours.

    Not two morph keyframes.  The capture is unambiguous: the first frame is a
    morph carrying the starting colour, the duration and the tempo, and the second
    is an *action 0x00* frame with a duration of 1 that names the destination.
    Sending two morph frames instead is accepted by the controller but animates
    differently and looks wrong -- it reads as two separate fades rather than one
    transition.

    Chains of three or more colours are a different shape; see `spectrum_frames`.
    """
    return [
        keyframe(ACTION_MORPH, first, duration, tempo),
        keyframe(ACTION_COLOUR, second, 0x0001, tempo),
    ]


def spectrum_frames(
    colours: Sequence[Rgb],
    duration: int = DURATION_SPECTRUM_MEDIUM,
    tempo: int = TEMPO_SPECTRUM,
) -> list[list[int]]:
    """A cycle through three or more colours.

    Here every frame *is* a morph, all sharing one duration and tempo, which is
    what `tests/fixtures/v3/touchpad/spectrum/duration/*` shows. The two-colour case is the odd
    one out, not this.
    """
    return [keyframe(ACTION_MORPH, c, duration, tempo) for c in colours]


SPECTRUM_COLOURS: tuple[Rgb, ...] = (
    (255, 0, 0),
    (255, 165, 0),
    (255, 255, 0),
    (0, 128, 0),
    (0, 191, 255),
    (0, 0, 255),
    (128, 0, 128),
)


def is_plausible(packet: bytes | bytearray) -> bool:
    return (
        len(packet) == LEN
        and packet[0] == PREAMBLE
        and packet[1] in (_REQUEST, _ANIMATION, _POWER_PROFILE, _ZONE_SELECT,
                          _ADD_ACTION, _SET_DIM)
    )


def iter_keyframes(packet: bytes) -> Iterable[tuple[int, int, int, Rgb]]:
    """Decode a `03 24` report back into (action, duration, tempo, rgb).  For tests."""
    if packet[1] != _ADD_ACTION:
        return
    for i in range(2, 2 + MAX_KEYFRAMES * 8, 8):
        chunk = packet[i : i + 8]
        if len(chunk) < 8 or chunk == b"\x00" * 8:
            continue
        yield (
            chunk[0],
            (chunk[1] << 8) | chunk[2],
            (chunk[3] << 8) | chunk[4],
            (chunk[5], chunk[6], chunk[7]),
        )
