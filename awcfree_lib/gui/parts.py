"""What each lit part of the machine can actually do.

The panel shows one part at a time and offers only what that part supports, so this
table is the single place that knows the difference.  Keeping it here rather than
spread through the window means adding a surface later is a new entry, not a hunt
through the UI code.

The differences are real, not cosmetic:

* the keyboard is 85 individually addressable LEDs driven by the v5 protocol, and
  its effects run on the keyboard's own controller;
* the touchpad and the lid logo are single v4 zones that share one brightness
  control and one set of chassis effects;
* the power button has no colour of its own at all.  Its light is six stored
  profiles that the firmware chooses between as the power state changes, so the
  only meaningful thing to set is what colour it takes on AC and on battery.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..protocol import v4, v5


@dataclass(frozen=True)
class Part:
    key: str
    name: str
    #: v4 zone id, or None for the keyboard, which is a different controller.
    zone: int | None
    #: What the sidebar should offer for this part.
    per_key: bool = False
    effects: tuple[str, ...] = ()
    #: Effects that read a second colour, so slot B is only shown for those.
    pair_effects: frozenset[str] = field(default_factory=frozenset)
    tempo: bool = False
    brightness: bool = False
    persist: bool = False
    power_profiles: bool = False
    blurb: str = ""
    #: Short caption for the card under the keyboard, where space is tight.
    caption: str = ""


#: Chassis effects, in the order they are offered.
CHASSIS_EFFECTS = ("static", "breathe", "pulse", "morph", "spectrum", "off")

#: Only the chassis morph blends two colours; the rest take one or none.
CHASSIS_PAIR = frozenset({"morph"})

#: Keyboard effects that read a second colour, straight from the protocol table.
KEYBOARD_PAIR = frozenset(
    name for name, count in v5.EFFECT_COLOURS.items() if count == 2
)

KEYBOARD = Part(
    key="keyboard",
    name="Keyboard",
    zone=None,
    per_key=True,
    effects=tuple(sorted(v5.EFFECTS)),
    pair_effects=KEYBOARD_PAIR,
    tempo=True,
    blurb="85 keys, each addressable. Effects run on the keyboard's own controller "
          "and take over from per-key colour until you switch back.",
)

TOUCHPAD = Part(
    key="touchpad",
    name="Touchpad",
    zone=v4.ZONE_TOUCHPAD,
    effects=CHASSIS_EFFECTS,
    pair_effects=CHASSIS_PAIR,
    brightness=True,
    persist=True,
    blurb="Only the border of the touchpad lights, not its face.",
    caption="Illuminated border",
)

LOGO = Part(
    key="logo",
    name="Lid emblem",
    zone=v4.ZONE_LOGO,
    effects=CHASSIS_EFFECTS,
    pair_effects=CHASSIS_PAIR,
    brightness=True,
    persist=True,
    blurb="The illuminated emblem on the outside of the lid.",
    caption="Lid emblem",
)

POWER = Part(
    key="power",
    name="Power button",
    zone=v4.ZONE_POWER,
    power_profiles=True,
    blurb="No colour of its own: the firmware picks between six stored profiles as "
          "the power state changes. Set what it shows on AC and on battery.",
    caption="AC & battery colours",
)

ALL: tuple[Part, ...] = (KEYBOARD, TOUCHPAD, LOGO, POWER)
BY_KEY = {p.key: p for p in ALL}


def uses_pair(part: Part, effect: str | None) -> bool:
    """Whether the second colour slot means anything right now."""
    if part.power_profiles:
        return True  # AC colour and battery colour are themselves a pair
    return effect is not None and effect in part.pair_effects
