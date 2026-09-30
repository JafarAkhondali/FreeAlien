"""Packet encoders for the AlienFX "v5" per-key keyboard (Darfon 0d62:d2b1).

64-byte HID *feature* reports, report id 0xcc in byte 0.  Nothing here touches the
device; every function returns bytes, which keeps the wire format testable against
the captures in `tests/fixtures/v3/` without hardware.

Byte-level sources, in order of authority:
  * `tests/fixtures/v3/perkey-rgb/color/all black` -- a capture of the stock Alienware Command
    Centre blacking out the keyboard.  This is where the 92 real LED ids, the
    `cc 8c 01` global block and the three `cc 8c 05/06/07` payloads come from.
  * T-Troll/alienfx-tools, `AlienFX-SDK/AlienFX_SDK/alienfx-controls.h` (MIT) for
    the command names and the `cc 80` effect layout.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

LEN = 64
REPORT_ID = 0xCC

#: `cc 8c 02` carries at most this many (id, r, g, b) records per report.
RECORDS_PER_FRAME = 15

# --- cc 8c sub-commands -----------------------------------------------------
# alienfx-controls.h notes only that byte 2 "can be 1,2,5,6,7,13"; the meaning of
# 1 and 5/6/7 is left as unknown there.  The names below come from reading the
# AWCC capture.
_SUB_GLOBAL = 0x01  # global / background block, see global_block()
_SUB_COLOUR = 0x02  # per-key colour records
_SUB_MASK_A = 0x05  # first 59 bytes of the 177-byte selection payload
_SUB_MASK_B = 0x06  # next 59
_SUB_MASK_C = 0x07  # last 59
_SUB_LOOP = 0x13  # end of a colour transaction

Rgb = tuple[int, int, int]


def _pad(prefix: Sequence[int]) -> bytes:
    if len(prefix) > LEN:
        raise ValueError(f"v5 packet longer than {LEN} bytes: {len(prefix)}")
    buf = bytearray(LEN)
    buf[: len(prefix)] = bytes(prefix)
    return bytes(buf)


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


# --- handshake --------------------------------------------------------------

#: Ask the controller to reset its colour staging area.  Reply carries what looks
#: like capability bytes; `Keyboard.probe()` returns them raw rather than guessing.
RESET = _pad([REPORT_ID, 0x94])

#: Status query.  AWCC sends it straight after RESET and ignores the reply.
STATUS = _pad([REPORT_ID, 0x93])

#: Closes a colour transaction.  Must precede UPDATE.
LOOP = _pad([REPORT_ID, 0x8C, _SUB_LOOP])

#: Commits the staged colours to the LEDs.
UPDATE = _pad([REPORT_ID, 0x8B, 0x01, 0xFF])

def turn_on(enabled: bool = True) -> bytes:
    """`cc 83 38 9c <on>` -- the master LED enable.

    alienfx-tools lists this as `COMMV5_turnOnSet` with three payload bytes and no
    argument, which is a trap: the byte after them is an on/off flag, and a packet
    that stops at `9c` is zero-padded and therefore means *off*.  Sending the bare
    form blanks the keyboard until it is explicitly switched back on.

    DO NOT SEND THIS.  Nothing in this library calls it, deliberately.

    Sending the bare three-byte form on an m16 R2 put the keyboard backlight into an
    off state that did not come back: not from re-sending this command with any
    value from 0x00 to 0xff, not from the `cc 94` handshake, not from a hardware
    effect, not from a USBDEVFS_RESET of the device.  It took a reboot.

    What the trailing byte means is therefore unresolved.  It is kept here only so
    the command is documented and so nobody reconstructs the bare constant from
    alienfx-tools' three-byte listing and hits the same wall.
    """
    return _pad([REPORT_ID, 0x83, 0x38, 0x9C, 0x01 if enabled else 0x00])


#: The exact bytes that caused the problem, kept so a test can assert we never
#: emit them rather than relying on a comment to stop someone.
DANGEROUS_TURN_ON_SET = turn_on(False)


def colour_frames(
    colours: Mapping[int, Rgb], order: Sequence[int] | None = None
) -> list[bytes]:
    """`cc 8c 02 00` frames, 15 records of `id r g b` each.

    Ids go on the wire exactly as given.  They are *not* shifted here: the AWCC
    capture writes 0x01 first and 0x88 last, and `layout.ALL_LEDS` holds that same
    set, so ids taken from `layout` need no adjustment.  (The +1 relative to the
    controller's internal numbering is already baked into those ids; see the mask
    section below.)

    `order` fixes the sequence records go out in.  AWCC does *not* emit them in
    ascending id order -- it follows its own layout order -- so passing
    `layout.ALL_LEDS` reproduces its packets byte for byte.  Without it, ids are
    sorted, which the hardware accepts just as happily since every record names its
    own id.
    """
    if order is None:
        records = sorted((int(led), rgb) for led, rgb in colours.items())
    else:
        rank = {led: i for i, led in enumerate(order)}
        records = [
            (int(led), colours[led])
            for led in sorted(colours, key=lambda k: (rank.get(k, len(rank)), k))
        ]
    frames = []
    for start in range(0, len(records), RECORDS_PER_FRAME):
        payload = [REPORT_ID, 0x8C, _SUB_COLOUR, 0x00]
        for led, (r, g, b) in records[start : start + RECORDS_PER_FRAME]:
            if not 0 <= led <= 0xFF:
                raise ValueError(f"LED id out of range: {led}")
            payload += [led, _clamp(r), _clamp(g), _clamp(b)]
        frames.append(_pad(payload))
    return frames


def global_block(primary: Rgb = (0, 0, 0), secondary: Rgb | None = None) -> bytes:
    """The `cc 8c 01` block AWCC sends once per colour transaction.

    The eight constant bytes after the sub-command are copied verbatim from the
    capture; their individual meanings are not known.  The two RGB triples at
    offsets 11 and 14 were both zero in the all-black capture, so their effect is
    inferred from the surrounding structure rather than observed -- treat them as
    provisional.  `secondary` defaults to `primary`.
    """
    if secondary is None:
        secondary = primary
    pr, pg, pb = (_clamp(c) for c in primary)
    sr, sg, sb = (_clamp(c) for c in secondary)
    return _pad(
        [REPORT_ID, 0x8C, _SUB_GLOBAL,
         0x01, 0x01, 0x00, 0x00, 0x01, 0x01, 0x01, 0x00,
         pr, pg, pb, sr, sg, sb, 0x01]
    )


# --- the LED enable mask ----------------------------------------------------
# Three reports of 60 payload bytes, 180 slots in total.  alienfx-controls.h calls
# this a "Mask command (purpose unknown)" and alien-thunder omits it entirely, but
# it decodes cleanly against the AWCC capture: exactly 92 slots are set, which is
# exactly the number of LEDs, and slot `i` enables wire id `i + 1`.
#
# So the controller's internal id space is 0-based with room for 180 LEDs, and the
# ids in a colour record are that internal id plus one.  This is the same off-by-one
# alien-thunder applies when it writes `led + 1` into its colour frames, arrived at
# from the other direction.
#
# Per-key colour works without ever sending the mask, so the flows here leave it
# out by default and `Keyboard(send_mask=True)` turns it on.
_MASK_SUBS = (_SUB_MASK_A, _SUB_MASK_B, _SUB_MASK_C)
MASK_SLOTS = 180
MASK_CHUNK = 60


def mask_frames(payload: Sequence[int]) -> list[bytes]:
    """Split a 180-slot enable payload into its three `cc 8c 05/06/07` reports."""
    if len(payload) != MASK_SLOTS:
        raise ValueError(f"enable payload must be {MASK_SLOTS} bytes, got {len(payload)}")
    return [
        _pad([REPORT_ID, 0x8C, sub, 0x00] + list(payload[i : i + MASK_CHUNK]))
        for sub, i in zip(_MASK_SUBS, range(0, MASK_SLOTS, MASK_CHUNK))
    ]


def mask_payload(leds: Iterable[int]) -> list[int]:
    """Build the 180-slot payload enabling the given wire ids."""
    payload = [0x00] * MASK_SLOTS
    for led in leds:
        slot = led - 1
        if not 0 <= slot < MASK_SLOTS:
            raise ValueError(f"LED id 0x{led:02x} falls outside the {MASK_SLOTS} slots")
        payload[slot] = 0x01
    return payload


def mask_for(leds: Iterable[int]) -> list[bytes]:
    """The three enable reports for a set of wire ids."""
    return mask_frames(mask_payload(leds))


# --- hardware effects -------------------------------------------------------
# `COMMV5_setEffect`.  These run on the keyboard's own controller, so they cost no
# host CPU, but they can only draw fixed patterns -- anything with arbitrary
# content (text, a game) has to be driven frame by frame from the host instead.
# Pulse (8) is unreliable on the m16 R2; Laser (11) freezes the previous
# pattern on reported hardware. Do not offer either without device validation.
EFFECTS: dict[str, int] = {
    "breathing": 2,
    "side_wave": 3,
    "double_wave": 4,
    "morph": 9,
    "bounce": 10,
    "rainbow": 14,
}

#: How many colours each effect actually uses, which is also the `colour_mode` it
#: wants.  alienfx-tools names type 4 "dual color wave" and type 9 "mix pulse (2
#: colors)", so those two read a second colour from the packet; rainbow generates
#: its own hues and ignores both; the rest use the primary alone.  Sending mode 2 to
#: a one-colour effect is accepted but the second colour has no visible effect.
EFFECT_COLOURS: dict[str, int] = {
    "breathing": 1,
    "side_wave": 1,
    "double_wave": 2,
    "morph": 2,
    "bounce": 1,
    "rainbow": 3,
}

#: Hands control back to the per-key colours.
EFFECT_OFF = _pad([REPORT_ID, 0x80, 0x01, 0xFE, 0x00, 0x00, 0x01, 0x01, 0x01])


def effect(
    name: str,
    tempo: int = 0x64,
    colour_mode: int = 1,
    primary: Rgb = (255, 0, 0),
    secondary: Rgb = (0, 0, 255),
) -> bytes:
    """Encode a controller-side effect.  `colour_mode` is 1, 2 or 3 (rainbow)."""
    try:
        etype = EFFECTS[name]
    except KeyError:
        raise ValueError(f"unknown effect {name!r}; have {sorted(EFFECTS)}") from None
    if colour_mode not in (1, 2, 3):
        raise ValueError("colour_mode must be 1, 2 or 3")
    buf = bytearray(_pad([REPORT_ID, 0x80, 0x02, 0x07, 0x00, 0x00, 0x01, 0x01, 0x01]))
    buf[2] = etype
    buf[3] = _clamp(tempo)
    buf[9] = colour_mode - 1
    buf[10:13] = bytes(_clamp(c) for c in primary)
    buf[13:16] = bytes(_clamp(c) for c in secondary)
    return bytes(buf)


def static_sequence(
    colours: Mapping[int, Rgb],
    *,
    background: Rgb | None = None,
    send_mask: bool = False,
    order: Sequence[int] | None = None,
) -> list[bytes]:
    """The full report sequence for a set of per-key colours, after the handshake.

    Ordering matters and is the ordering AWCC uses: enable mask, global block,
    colour frames, LOOP, UPDATE.  `cc 83` is deliberately absent -- see `turn_on`.
    """
    out: list[bytes] = []
    if send_mask:
        out += mask_for(colours)
    if background is not None:
        out.append(global_block(background))
    out += colour_frames(colours, order=order)
    out += [LOOP, UPDATE]
    return out


def is_plausible(packet: bytes | bytearray) -> bool:
    """Cheap sanity check used by the tests and the packet dumper."""
    return (
        len(packet) == LEN
        and packet[0] == REPORT_ID
        and packet[1] in (0x80, 0x83, 0x8B, 0x8C, 0x93, 0x94)
    )


def iter_records(packet: bytes) -> Iterable[tuple[int, Rgb]]:
    """Decode a `cc 8c 02` frame back into (id, rgb) pairs.  For tests and debugging."""
    if packet[1] != 0x8C or packet[2] != _SUB_COLOUR:
        return
    for i in range(4, LEN - 3, 4):
        led = packet[i]
        rgb = (packet[i + 1], packet[i + 2], packet[i + 3])
        if led == 0 and rgb == (0, 0, 0):
            continue
        yield led, rgb
