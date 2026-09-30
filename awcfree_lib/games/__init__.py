"""Games drawn on the keyboard's LEDs.

Each game keeps its rules free of I/O -- it manipulates a grid of cells and nothing
else -- so it can be played headless in a test. `runner` is the only part that talks
to a keyboard, and it takes any object with `step`, `render` and `alive`, so a second
game plugs in without touching it.
"""
from .snake import FIELDS, Field, SnakeGame, rect_field, solid_field

__all__ = ["FIELDS", "Field", "SnakeGame", "rect_field", "solid_field"]
