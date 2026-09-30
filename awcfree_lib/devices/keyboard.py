"""The per-key keyboard (Darfon 0d62:d2b1) as a stateful object.

The point of this class over calling `protocol.v5` directly is frame diffing.  A
full refresh of 92 LEDs costs 8 colour reports; a snake moving one cell costs one.
Anything animated -- games, scrolling text, host-side effects -- goes through
`set` then `flush`, and only what actually changed is sent.
"""
from __future__ import annotations

import time
from collections.abc import Iterable, Mapping

from .. import layout
from ..errors import DeviceNotFound
from ..protocol import v5
from ..transport import HidrawDevice, find_hidraw

VID = 0x0D62
PID = 0xD2B1

Rgb = tuple[int, int, int]

_ADDRESSABLE = frozenset(layout.ALL_LEDS)

#: The report descriptor of the interface that takes lighting commands declares
#: report id 0xcc.  The other interfaces on this device do not.
_DESCRIPTOR_MARK = b"\x85\xcc"


class Keyboard:
    """Per-key RGB.

    `set`/`set_many`/`fill` stage colours; `flush` sends only the difference from
    what the hardware last received.  `pending` is how many LEDs are dirty.
    """

    def __init__(self, path: str | None = None, *, send_mask: bool = False) -> None:
        if path is None:
            path = find_hidraw(VID, PID, descriptor_contains=_DESCRIPTOR_MARK,
                              interface="00")
        if path is None:
            path = find_hidraw(VID, PID, descriptor_contains=_DESCRIPTOR_MARK)
        if path is None:
            raise DeviceNotFound(
                f"no hidraw node for the keyboard controller {VID:04x}:{PID:04x}"
            )
        self.dev = HidrawDevice(path, v5.LEN, label="keyboard")
        # Whether to send the 180-slot LED enable mask alongside colours.  AWCC sends
        # it; per-key colour works without it, so it stays off to save three reports
        # per full refresh.  Turn it on if the controller ever ignores an LED.
        self.send_mask = send_mask
        self._staged: dict[int, Rgb] = {}
        self._onwire: dict[int, Rgb] = {}
        self._handshaken = False

    # --- lifecycle ---------------------------------------------------------
    def __enter__(self) -> Keyboard:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        self.dev.open()

    def close(self) -> None:
        self.dev.close()
        self._handshaken = False

    def handshake(self, force: bool = False) -> None:
        """`cc 94` then `cc 93`.  Done once per open; animations must not repeat it.

        Deliberately does not send `cc 83` -- see `protocol.v5.turn_on` for what
        happened when it did.
        """
        if self._handshaken and not force:
            return
        self.dev.send_feature(v5.RESET)
        self.dev.send_feature(v5.STATUS)
        self._handshaken = True

    def probe(self) -> bytes:
        """Raw reply to `cc 94`.

        Contains what look like capability or LED-count bytes, but the layout is not
        decoded, so this hands back the bytes rather than pretending to parse them.
        """
        self.dev.send_feature(v5.RESET)
        return self.dev.get_feature(v5.REPORT_ID)

    # --- staging -----------------------------------------------------------
    def set(self, led: int, colour: Rgb) -> None:
        """Stage one LED.

        Any of the 92 addressable ids is accepted, including the seven that light
        nothing on this unit -- writing them is harmless and keeps our packets
        identical to the stock software's.
        """
        if led not in _ADDRESSABLE:
            raise KeyError(f"0x{led:02x} is not an addressable LED on this keyboard")
        self._staged[led] = colour

    def set_many(self, colours: Mapping[int, Rgb]) -> None:
        for led, colour in colours.items():
            self.set(led, colour)

    def fill(self, colour: Rgb, leds: Iterable[int] | None = None) -> None:
        """Stage every LED (or a subset) to one colour."""
        for led in layout.ALL_LEDS if leds is None else leds:
            self._staged[led] = colour

    def clear(self) -> None:
        self.fill((0, 0, 0))

    @property
    def pending(self) -> int:
        """How many staged LEDs differ from what the hardware has."""
        return sum(1 for led, c in self._staged.items() if self._onwire.get(led) != c)

    # --- committing --------------------------------------------------------
    def flush(self, *, force: bool = False, background: Rgb | None = None) -> int:
        """Send staged colours.  Returns the number of reports written.

        Only LEDs whose colour changed are sent unless `force`.  A flush with
        nothing dirty writes nothing at all and returns 0.
        """
        self.handshake()
        if force:
            changed = dict(self._staged)
        else:
            changed = {
                led: c for led, c in self._staged.items() if self._onwire.get(led) != c
            }
        if not changed:
            return 0
        packets = v5.static_sequence(
            changed, background=background, send_mask=self.send_mask and force,
            order=layout.ALL_LEDS,
        )
        for pkt in packets:
            self.dev.send_feature(pkt)
        self._onwire.update(changed)
        return len(packets)

    def invalidate(self) -> None:
        """Forget what the hardware has, so the next flush is a full refresh.

        Call after anything else touches the keyboard -- a hardware effect, a resume
        from suspend, another process.
        """
        self._onwire.clear()

    # --- controller-side effects -------------------------------------------
    def effect(
        self,
        name: str,
        *,
        tempo: int = 0x64,
        colour_mode: int = 1,
        primary: Rgb = (255, 0, 0),
        secondary: Rgb = (0, 0, 255),
    ) -> None:
        """Hand the keyboard over to one of its built-in effects.

        These cost no host CPU but can only draw fixed patterns.  They take the
        LEDs away from per-key control, so the diff cache is dropped.
        """
        # Reject unsupported effects before even resetting the staging area.
        packet = v5.effect(name, tempo=tempo, colour_mode=colour_mode,
                           primary=primary, secondary=secondary)
        self.handshake()
        self.dev.send_feature(packet)
        self.invalidate()

    def effect_off(self) -> None:
        """Return to per-key control after `effect`."""
        self.handshake()
        self.dev.send_feature(v5.EFFECT_OFF)
        self.invalidate()

    def take_control(self) -> None:
        """Make sure per-key colours will actually be honoured.

        While a controller-side effect is running it owns the LEDs, and colour
        records are accepted but not shown -- so a keyboard left in the stock effect
        by the firmware or by Windows ignores everything we send.  There is no way to
        ask whether an effect is active, so this just sends the off command
        unconditionally; it is harmless when nothing was running.
        """
        self.effect_off()

    # --- convenience -------------------------------------------------------
    def static(self, colour: Rgb) -> int:
        """One colour on every key, in a single call."""
        self.fill(colour)
        return self.flush()

    def animate(
        self,
        frames: Iterable[Mapping[int, Rgb]],
        *,
        fps: float = 20.0,
        settle: float = 0.0,
    ) -> None:
        """Drive a sequence of frames at a target rate.

        `settle` is a per-report delay; leave it at 0 and raise it only if the
        controller starts dropping reports.  Frame pacing accounts for the time the
        writes actually took, so a slow frame does not compound.
        """
        period = 1.0 / fps if fps > 0 else 0.0
        self.handshake()
        for frame in frames:
            started = time.monotonic()
            self.set_many(frame)
            self.flush()
            if settle:
                time.sleep(settle)
            if period:
                remaining = period - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
