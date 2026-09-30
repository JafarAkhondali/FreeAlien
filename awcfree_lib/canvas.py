"""A grid framebuffer over the keyboard, for anything that draws rather than tints.

The protocol addresses LEDs by id, and those ids carry no spatial meaning -- they
run roughly left to right, top to bottom, but with gaps, and nothing in a packet
says where a key sits.  `layout.CELLS` supplies the measured geometry; this module
turns it into a plain 2D buffer that games and text effects can draw into without
knowing any of that.

The cell-to-id resolution happens once in the constructor, so drawing is a list
assignment and `present` is a dict comprehension over dirty cells only.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence

from . import layout

Rgb = tuple[int, int, int]


class Canvas:
    """A `cols` x `rows` grid of colours backed by the keyboard's LEDs.

    Several keys can land in the same cell (wide keys, and ids that share a
    position), in which case they all take that cell's colour.  Cells with no key
    behind them are still writable -- they simply do not light anything, which keeps
    drawing code free of special cases.
    """

    def __init__(
        self,
        cols: int = layout.GRID_COLS,
        rows: int = layout.GRID_ROWS,
        *,
        background: Rgb = (0, 0, 0),
    ) -> None:
        self.cols = cols
        self.rows = rows
        self.background = background
        self._buf: list[Rgb] = [background] * (cols * rows)
        # cell index -> the LED ids that live in it
        self._cell_leds: list[list[int]] = [[] for _ in range(cols * rows)]
        for led, (col, row) in layout.CELLS.items():
            if 0 <= col < cols and 0 <= row < rows:
                self._cell_leds[row * cols + col].append(led)
        self._lit: tuple[int, ...] = tuple(
            i for i, leds in enumerate(self._cell_leds) if leds
        )

    # --- geometry ----------------------------------------------------------
    def __len__(self) -> int:
        return self.cols * self.rows

    @property
    def lit_cells(self) -> tuple[int, ...]:
        """Indices of the cells that actually have an LED behind them."""
        return self._lit

    def leds_at(self, col: int, row: int) -> Sequence[int]:
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            return ()
        return tuple(self._cell_leds[row * self.cols + col])

    # --- drawing -----------------------------------------------------------
    def __getitem__(self, pos: tuple[int, int]) -> Rgb:
        col, row = pos
        return self._buf[row * self.cols + col]

    def __setitem__(self, pos: tuple[int, int], colour: Rgb) -> None:
        col, row = pos
        if 0 <= col < self.cols and 0 <= row < self.rows:
            self._buf[row * self.cols + col] = colour

    def fill(self, colour: Rgb | None = None) -> None:
        colour = self.background if colour is None else colour
        self._buf = [colour] * (self.cols * self.rows)

    def clear(self) -> None:
        self.fill(self.background)

    def hline(self, row: int, colour: Rgb, x0: int = 0, x1: int | None = None) -> None:
        x1 = self.cols if x1 is None else x1
        for col in range(max(0, x0), min(self.cols, x1)):
            self[col, row] = colour

    def vline(self, col: int, colour: Rgb, y0: int = 0, y1: int | None = None) -> None:
        y1 = self.rows if y1 is None else y1
        for row in range(max(0, y0), min(self.rows, y1)):
            self[col, row] = colour

    def rect(self, x: int, y: int, w: int, h: int, colour: Rgb) -> None:
        for row in range(y, y + h):
            for col in range(x, x + w):
                self[col, row] = colour

    def blit(
        self, sprite: Sequence[Sequence[int]], x: int, y: int,
        colour: Rgb, *, transparent: bool = True, off: Rgb | None = None,
    ) -> None:
        """Draw a 2D mask of truthy/falsy cells.

        With `transparent` the falsy cells are left alone; otherwise they take
        `off`, defaulting to the background.
        """
        blank = self.background if off is None else off
        for dy, line in enumerate(sprite):
            for dx, on in enumerate(line):
                if on:
                    self[x + dx, y + dy] = colour
                elif not transparent:
                    self[x + dx, y + dy] = blank

    # --- output ------------------------------------------------------------
    def to_leds(self) -> dict[int, Rgb]:
        """Project the buffer onto LED ids.

        Only cells with an LED behind them are visited, so this is proportional to
        the number of keys, not the grid area.
        """
        out: dict[int, Rgb] = {}
        for cell in self._lit:
            colour = self._buf[cell]
            for led in self._cell_leds[cell]:
                out[led] = colour
        return out

    def present(self, keyboard, **flush_kwargs) -> int:
        """Push the buffer to a `Keyboard` and flush.

        The keyboard diffs against what it last sent, so a canvas where one cell
        changed costs one report.
        """
        keyboard.set_many(self.to_leds())
        return keyboard.flush(**flush_kwargs)

    # --- debugging ---------------------------------------------------------
    def rows_as_text(self, on: str = "#", off: str = ".") -> Iterator[str]:
        """Render to text, for testing a game without a keyboard attached."""
        for row in range(self.rows):
            line = []
            for col in range(self.cols):
                cell = row * self.cols + col
                if not self._cell_leds[cell]:
                    line.append(" ")
                else:
                    line.append(on if self._buf[cell] != self.background else off)
            yield "".join(line)
