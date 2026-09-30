"""Minesweeper on the largest contiguous block of measured keyboard LEDs."""
from __future__ import annotations

import random
from .. import layout
from .snake import Field, solid_field

Cell = tuple[int, int]

# Dark, saturated rainbow in count order. The first six F keys mirror these.
COUNT_COLOURS = {
    1: (255, 0, 0), 2: (255, 92, 0), 3: (205, 160, 0),
    4: (0, 145, 35), 5: (0, 64, 220), 6: (112, 15, 165),
    7: (190, 20, 100), 8: (115, 125, 140),
}


class Minesweeper:
    """Deferred board generation guarantees the opening cell is safe."""
    def __init__(self, field: Field | None = None, mines: int = 8,
                 rng: random.Random | None = None):
        self.field = field or solid_field()
        self.rng = rng or random.Random()
        self.mine_count = max(1, min(mines, len(self.field.cells) - 9))
        self.reset()

    def reset(self):
        self.mines: set[Cell] = set()
        self.revealed: set[Cell] = set()
        self.flags: set[Cell] = set()
        self.started = False
        self.over = False
        self.won = False
        self.exploded: Cell | None = None

    def neighbours(self, cell: Cell) -> set[Cell]:
        x, y = cell
        return {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and (x + dx, y + dy) in self.field.cells}

    def count(self, cell: Cell) -> int:
        return len(self.neighbours(cell) & self.mines)

    def reveal(self, cell: Cell) -> None:
        if self.over or cell not in self.field.cells or cell in self.flags:
            return
        if cell in self.revealed:
            self.chord(cell)
            return
        if not self.started:
            safe = {cell} | self.neighbours(cell)
            choices = sorted(self.field.cells - safe)
            self.mines = set(self.rng.sample(choices, min(self.mine_count, len(choices))))
            self.started = True
        if cell in self.mines:
            self.exploded = cell
            self.over = True
            return
        pending = [cell]
        while pending:
            here = pending.pop()
            if here in self.revealed or here in self.mines or here in self.flags:
                continue
            self.revealed.add(here)
            if self.count(here) == 0:
                pending.extend(self.neighbours(here) - self.revealed)
        self._check_win()

    def chord(self, cell: Cell) -> bool:
        """Open a numbered key's covered neighbours when its flags agree.

        Returns false when this is not a revealed number or the player has not
        flagged exactly the displayed count. Incorrect flags can expose a mine,
        just as in ordinary Minesweeper.
        """
        if self.over or cell not in self.revealed:
            return False
        count = self.count(cell)
        if count == 0:
            return False
        neighbours = self.neighbours(cell)
        if len(neighbours & self.flags) != count:
            return False
        targets = neighbours - self.revealed - self.flags
        for target in sorted(targets):
            self.reveal(target)
            if self.over:
                break
        self._check_win()
        return True

    def toggle_flag(self, cell: Cell) -> None:
        if self.over or cell in self.revealed or cell not in self.field.cells:
            return
        if cell in self.flags:
            self.flags.remove(cell)
        elif len(self.flags) < self.mine_count:
            self.flags.add(cell)
        self._check_win()

    def _check_win(self):
        if self.started and self.field.cells - self.mines <= self.revealed:
            self.won = self.over = True
