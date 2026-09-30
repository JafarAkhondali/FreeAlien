"""A façade holding both controllers, so callers need not know which is which.

Some surfaces live on the keyboard controller and some on the chassis controller,
and which is which is not obvious from the outside -- the power button's indicator
is on the *chassis* controller, not the keyboard.  `Lighting` hides the split and
degrades gracefully when only one controller is reachable.
"""
from __future__ import annotations

from collections.abc import Sequence

from .devices import Chassis, Keyboard
from .errors import AwcfreeError
from .protocol import v4

Rgb = tuple[int, int, int]


class Lighting:
    """Both controllers together.

    `keyboard` and `chassis` are None when that controller could not be opened, so
    a machine with only one still works. `problems` says why.
    """

    def __init__(self, *, keyboard: bool = True, chassis: bool = True) -> None:
        self.keyboard: Keyboard | None = None
        self.chassis: Chassis | None = None
        self.problems: dict[str, str] = {}
        if keyboard:
            try:
                self.keyboard = Keyboard()
            except AwcfreeError as exc:
                self.problems["keyboard"] = str(exc)
        if chassis:
            try:
                self.chassis = Chassis()
            except AwcfreeError as exc:
                self.problems["chassis"] = str(exc)

    def __enter__(self) -> Lighting:
        if self.keyboard:
            self.keyboard.open()
        if self.chassis:
            self.chassis.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.keyboard:
            self.keyboard.close()
        if self.chassis:
            self.chassis.close()

    @property
    def available(self) -> bool:
        return self.keyboard is not None or self.chassis is not None

    def all_static(self, colour: Rgb, *, persist: bool = False) -> None:
        """One colour across every surface we can reach."""
        if self.keyboard:
            self.keyboard.static(colour)
        if self.chassis:
            self.chassis.static(
                {z: colour for z in v4.CHASSIS_ZONES}, persist=persist
            )

    def off(self, *, persist: bool = False) -> None:
        self.all_static((0, 0, 0), persist=persist)
