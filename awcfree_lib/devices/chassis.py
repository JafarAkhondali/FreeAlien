"""The AW-ELC chassis controller (187c:0551): touchpad, lid logo, power button.

Three separate surfaces, two of which behave the same way and one of which does
not.  Touchpad and lid logo are ordinary zones driven through the 0x21 animation
verbs.  The power button is a zone too (0x04) but its colours live in six standing
profiles under 0x22 that the firmware switches between on its own as the power
state changes -- so you do not set the power button's colour, you set the colour it
takes in each state.
"""
from __future__ import annotations

from collections.abc import Sequence

from ..errors import DeviceNotFound
from ..protocol import v4
from ..transport import HidrawDevice, find_hidraw

VID = 0x187C
PID = 0x0551

Rgb = tuple[int, int, int]


class Chassis:
    """Touchpad, lid logo and power-button lighting."""

    def __init__(self, path: str | None = None) -> None:
        if path is None:
            path = find_hidraw(VID, PID)
        if path is None:
            raise DeviceNotFound(
                f"no hidraw node for the chassis controller {VID:04x}:{PID:04x}"
            )
        self.dev = HidrawDevice(path, v4.LEN, label="chassis")

    def __enter__(self) -> Chassis:
        self.dev.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.dev.close()

    def open(self) -> None:
        self.dev.open()

    def close(self) -> None:
        self.dev.close()

    def _send(self, packets: Sequence[bytes]) -> int:
        for pkt in packets:
            self.dev.send_output(pkt)
        return len(packets)

    # --- queries -----------------------------------------------------------
    def firmware(self) -> bytes:
        """Raw reply to `03 20 00`.  Not decoded -- returned as bytes."""
        self.dev.send_output(v4.request(v4.REQ_FIRMWARE))
        return self.dev.get_input()

    def elc_config(self) -> bytes:
        """Raw reply to `03 20 02`.

        This is the request that should describe how many zones the controller has
        and which ids they use.  The reply layout is not decoded here; `awcfree
        probe-zones` dumps it so the zone map can be settled empirically.
        """
        self.dev.send_output(v4.request(v4.REQ_ELC_CONFIG))
        return self.dev.get_input()

    # --- zones -------------------------------------------------------------
    def static(self, zone_colours: dict[int, Rgb], *, persist: bool = False) -> int:
        """One flat colour per zone.  `persist` survives a reboot."""
        return self._send(v4.static_sequence(zone_colours, persist=persist))

    def set_touchpad(self, colour: Rgb, *, persist: bool = False) -> int:
        return self.static({v4.ZONE_TOUCHPAD: colour}, persist=persist)

    def set_logo(self, colour: Rgb, *, persist: bool = False) -> int:
        """The illuminated emblem on the lid."""
        return self.static({v4.ZONE_LOGO: colour}, persist=persist)

    def morph(
        self, zone: int, colours: Sequence[Rgb], *,
        duration: int | None = None, tempo: int | None = None,
        persist: bool = False,
    ) -> int:
        """Fade a zone through a colour chain, looping.

        Two colours and three-or-more are encoded differently, and getting that
        wrong is what makes a morph look ragged rather than smooth.  A pair is a
        morph keyframe naming the first colour followed by an action-0x00 keyframe
        with duration 1 naming the second; a longer chain is all morph keyframes
        sharing one duration.  Both forms come straight from the captures.

        Several keyframes ride in one report -- three per report, which is what AWCC
        itself does and what makes a seven-colour spectrum cost three reports rather
        than seven.
        """
        if len(colours) < 2:
            raise ValueError("a morph needs at least two colours")
        if len(colours) == 2:
            frames = v4.morph_pair_frames(
                colours[0], colours[1],
                duration if duration is not None else v4.DURATION_MORPH,
                tempo if tempo is not None else v4.TEMPO_MORPH,
            )
        else:
            frames = v4.spectrum_frames(
                colours,
                duration if duration is not None else v4.DURATION_SPECTRUM_MEDIUM,
                tempo if tempo is not None else v4.TEMPO_SPECTRUM,
            )
        return self._send(v4.keyframe_sequence(zone, frames, persist=persist))

    def pulse(
        self, zone: int, colour: Rgb, *,
        duration: int = v4.DURATION_PULSE, tempo: int = v4.TEMPO_PULSE,
        persist: bool = False,
    ) -> int:
        """Pulse a zone.

        The tempo here is the one AWCC uses. A larger number pulses faster, so the
        chassis default of 0x00FA -- which this used to pass -- flashes about two
        and a half times quicker than the stock software.
        """
        frames = [v4.keyframe(v4.ACTION_PULSE, colour, duration, tempo)]
        return self._send(v4.keyframe_sequence(zone, frames, persist=persist))

    def spectrum(
        self, zone: int, *, duration: int = v4.DURATION_SPECTRUM_MEDIUM,
        persist: bool = False,
    ) -> int:
        """The rainbow cycle, as a morph chain through seven hues."""
        frames = v4.spectrum_frames(v4.SPECTRUM_COLOURS, duration=duration)
        return self._send(v4.keyframe_sequence(zone, frames, persist=persist))

    def brightness(self, level: int, zones: Sequence[int] | None = None) -> int:
        """`03 26` -- 0 to 255 across the given zones."""
        if zones is None:
            zones = v4.CHASSIS_ZONES
        return self._send([v4.set_dim(level, list(zones))])

    def off(self, *, persist: bool = False) -> int:
        return self.static({z: (0, 0, 0) for z in v4.CHASSIS_ZONES}, persist=persist)

    # --- power button ------------------------------------------------------
    def set_power_profile(self, profile: str | int, colours: Sequence[Rgb]) -> int:
        """Set the colour the power button takes in one power state.

        `profile` is a name from `v4.POWER_PROFILES` or a raw id.  Profiles whose
        action is a morph take two colours; the rest take one.  These are written to
        the controller's own storage, so they persist with no `persist` flag.
        """
        pid = v4.POWER_PROFILES[profile] if isinstance(profile, str) else profile
        return self._send(v4.power_profile_sequence(pid, colours))

    def set_power_all(self, ac: Rgb, battery: Rgb) -> int:
        """Set all six profiles: one colour for AC states, one for battery states.

        This is the shape of AWCC's own flow, which writes white to the three AC
        profiles and the user's accent colour to the three battery ones.
        """
        written = 0
        for name, pid in v4.POWER_PROFILES.items():
            colour = ac if name.startswith("ac") else battery
            # One colour throughout: the morph profiles then breathe it against black,
            # which is what AWCC does, rather than fading the colour to itself.
            written += self._send(v4.power_profile_sequence(pid, [colour]))
        return written
