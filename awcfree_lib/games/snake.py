"""Snake, played on the keyboard's LEDs.

The game state is deliberately free of any I/O: `SnakeGame` knows about a grid of
cells and nothing about keyboards, canvases or terminals.  That keeps it testable
headless -- `tests/test_snake.py` plays whole games with no hardware -- and leaves
`render` as the only part that touches a canvas.

The playfield is a rectangle of cells that all have an LED behind them.  That
constraint is the interesting one: the board is 16x6 but eleven of those cells have
no LED, and a cell with no LED cannot be drawn, so a wall there would be invisible
and a snake passing over it would vanish.  The default field is therefore the
largest solid rectangle, cols 2-11 of rows 0-4.  Wider fields are available for
anyone who would rather have the space than the fairness.

All four edges wrap by default, so the only way to die is to hit yourself.  On a
board this small that matters: a 10x5 field gives a snake very little room to turn
around, and edges that kill make the first few seconds of a round the dangerous
part rather than the end of a long one.  `wrap=False` restores lethal edges.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field as dc_field

from .. import layout

Cell = tuple[int, int]
Rgb = tuple[int, int, int]

UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)
DIRECTIONS = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT}


@dataclass(frozen=True)
class Field:
    """The rectangle play happens in, plus any cells inside it that are holes."""

    x0: int
    y0: int
    width: int
    height: int
    walls: frozenset[Cell] = dc_field(default_factory=frozenset)
    #: Whether the four edges teleport the snake to the opposite side.  On by
    #: default: with no walls in the solid field, that leaves self-collision as the
    #: only way to lose.
    wrap: bool = True

    @property
    def cells(self) -> set[Cell]:
        return {
            (self.x0 + dx, self.y0 + dy)
            for dx in range(self.width)
            for dy in range(self.height)
        } - set(self.walls)

    def contains(self, cell: Cell) -> bool:
        x, y = cell
        return (
            self.x0 <= x < self.x0 + self.width
            and self.y0 <= y < self.y0 + self.height
            and cell not in self.walls
        )

    def normalise(self, cell: Cell) -> Cell:
        """Bring a cell back inside the field, if the edges wrap.

        Python's modulo is already correct for negatives, so stepping off the left
        or top edge lands on the right or bottom without a special case.
        """
        if not self.wrap:
            return cell
        x, y = cell
        return (
            self.x0 + (x - self.x0) % self.width,
            self.y0 + (y - self.y0) % self.height,
        )


def solid_field(wrap: bool = True) -> Field:
    """The largest rectangle whose every cell has an LED.

    No walls at all, so with `wrap` on the snake can only ever die by running into
    itself.
    """
    occupied = {pos for pos in layout.CELLS.values()}
    best = None
    for y0 in range(layout.GRID_ROWS):
        for y1 in range(y0, layout.GRID_ROWS):
            for x0 in range(layout.GRID_COLS):
                for x1 in range(x0, layout.GRID_COLS):
                    if all((x, y) in occupied
                           for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)):
                        area = (x1 - x0 + 1) * (y1 - y0 + 1)
                        if best is None or area > best[0]:
                            best = (area, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    _, x0, y0, w, h = best
    return Field(x0, y0, w, h, frozenset(), wrap)


def rect_field(x0: int, y0: int, width: int, height: int,
               wrap: bool = True) -> Field:
    """A rectangle where cells without an LED become walls.

    Those walls cannot be drawn -- there is no LED to light -- so they look like
    empty space until the snake dies on one. Playable, but less fair than `solid`,
    and note that wrapping does not save you from them: the edges teleport, the
    holes in the middle still kill.
    """
    occupied = {pos for pos in layout.CELLS.values()}
    walls = frozenset(
        (x0 + dx, y0 + dy)
        for dx in range(width)
        for dy in range(height)
        if (x0 + dx, y0 + dy) not in occupied
    )
    return Field(x0, y0, width, height, walls, wrap)


FIELDS = {
    "solid": lambda wrap: solid_field(wrap),
    "wide": lambda wrap: rect_field(0, 0, layout.GRID_COLS, 5, wrap),
    "full": lambda wrap: rect_field(0, 0, layout.GRID_COLS, layout.GRID_ROWS, wrap),
}


class SnakeGame:
    """Snake state machine. No I/O; step it and read the result."""

    def __init__(self, field: Field, rng: random.Random | None = None,
                 start_length: int = 3) -> None:
        self.field = field
        self.rng = rng or random.Random()
        self.start_length = start_length
        self.reset()

    # --- lifecycle ---------------------------------------------------------
    def reset(self) -> None:
        cx = self.field.x0 + self.field.width // 2
        cy = self.field.y0 + self.field.height // 2
        self.direction: Cell = RIGHT
        self._pending: deque[Cell] = deque()
        body = []
        for i in range(self.start_length):
            cell = (cx - i, cy)
            if not self.field.contains(cell):
                break
            body.append(cell)
        if not body:
            body = [sorted(self.field.cells)[0]]
        self.body: deque[Cell] = deque(body)
        self.occupied: set[Cell] = set(body)
        self.alive = True
        self.score = 0
        self.ticks = 0
        self.food: Cell | None = None
        self._place_food()

    def _place_food(self) -> None:
        free = sorted(self.field.cells - self.occupied)
        self.food = self.rng.choice(free) if free else None

    # --- play --------------------------------------------------------------
    #: Turns buffered ahead of the snake. Two is enough to round a corner cleanly
    #: without the snake continuing to turn long after the player stopped pressing.
    MAX_QUEUED_TURNS = 2

    def turn(self, name: str) -> None:
        """Queue a direction change, to be applied one per tick.

        A queue rather than a single slot, because overwriting loses the first turn
        and lets the second reverse the snake: moving right, pressing up then left
        inside one tick would apply left against right and fold the snake onto
        itself. Queued, the two are honoured on consecutive ticks and each is
        checked against the one before it.
        """
        new = DIRECTIONS.get(name)
        if new is None:
            return
        if len(self._pending) >= self.MAX_QUEUED_TURNS:
            return
        reference = self._pending[-1] if self._pending else self.direction
        if new == reference:
            return  # no-op, do not fill the queue with repeats
        if (new[0] + reference[0], new[1] + reference[1]) == (0, 0) and len(self.body) > 1:
            return  # straight reverse, ignore
        self._pending.append(new)

    @property
    def head(self) -> Cell:
        return self.body[0]

    @property
    def won(self) -> bool:
        return self.alive and not (self.field.cells - self.occupied)

    def step(self) -> bool:
        """Advance one tick. Returns whether the snake is still alive."""
        if not self.alive:
            return False
        if self._pending:
            self.direction = self._pending.popleft()
        self.ticks += 1

        hx, hy = self.head
        dx, dy = self.direction
        nxt = self.field.normalise((hx + dx, hy + dy))

        if not self.field.contains(nxt):
            self.alive = False
            return False

        ate = nxt == self.food
        # The tail cell frees up as the snake moves, so entering it is legal --
        # unless the snake just ate, in which case the tail stays put.
        tail = self.body[-1]
        if nxt in self.occupied and not (nxt == tail and not ate):
            self.alive = False
            return False

        self.body.appendleft(nxt)
        self.occupied.add(nxt)
        if ate:
            self.score += 1
            self._place_food()
        else:
            gone = self.body.pop()
            if gone not in self.body:
                self.occupied.discard(gone)
        return True

    # --- drawing -----------------------------------------------------------
    def render(self, canvas, *, head: Rgb = (255, 255, 255),
               body: Rgb = (0, 200, 60), tail: Rgb = (0, 40, 15),
               food: Rgb = (255, 40, 0), phase: float = 0.0) -> None:
        """Draw the current state.

        The body fades from `body` at the neck to `tail` at the end, which makes the
        direction of travel readable at a glance on a board only a few cells across.
        """
        canvas.clear()
        n = max(1, len(self.body) - 1)
        for i, cell in enumerate(self.body):
            if i == 0:
                canvas[cell] = head
                continue
            t = (i - 1) / n
            canvas[cell] = tuple(
                int(round(body[c] + (tail[c] - body[c]) * t)) for c in range(3)
            )
        if self.food is not None:
            pulse = 0.55 + 0.45 * phase
            canvas[self.food] = tuple(int(round(c * pulse)) for c in food)
