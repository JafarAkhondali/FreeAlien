"""Drives a game against the real keyboard.

Kept apart from the game itself so the rules stay I/O-free and the loop can be
reused: anything with `step`, `render` and an `alive` flag plugs in here.
"""
from __future__ import annotations

import math
import time

from ..canvas import Canvas
from ..devices import Keyboard
from . import input as game_input
from .snake import FIELDS, SnakeGame

Rgb = tuple[int, int, int]


class Runner:
    """Fixed-tick game loop with its own frame pacing.

    Ticks (game logic) and frames (rendering) are separate: the snake moves a few
    times a second, but the food keeps pulsing at the frame rate in between, which
    would look like a stutter if both were tied together.
    """

    def __init__(self, keyboard: Keyboard, canvas: Canvas | None = None,
                 fps: float = 30.0) -> None:
        self.kb = keyboard
        self.canvas = canvas or Canvas()
        self.fps = fps

    def _present(self, game, phase: float) -> None:
        game.render(self.canvas, phase=phase)
        self.canvas.present(self.kb)

    def flash(self, colour: Rgb, times: int = 3, period: float = 0.14) -> None:
        for _ in range(times):
            self.canvas.fill(colour)
            self.canvas.present(self.kb)
            time.sleep(period)
            self.canvas.clear()
            self.canvas.present(self.kb)
            time.sleep(period)

    def sweep(self, colour: Rgb, delay: float = 0.03) -> None:
        """A wipe across the board, used to open a round."""
        for col in range(self.canvas.cols):
            self.canvas.clear()
            self.canvas.vline(col, colour)
            self.canvas.present(self.kb)
            time.sleep(delay)
        self.canvas.clear()
        self.canvas.present(self.kb)

    def play(self, game, keys: game_input.KeyReader, *,
             start_tps: float = 5.0, max_tps: float = 14.0,
             speedup: float = 0.35) -> str:
        """Run one round.

        Returns "quit", "restart" or "over".  Speed climbs with the score, which is
        what gives the game its difficulty curve; `max_tps` caps it so it stays
        playable on a board this small.
        """
        frame = 1.0 / self.fps
        tick_due = time.monotonic()
        paused = False
        while True:
            now = time.monotonic()
            action = keys.poll()
            if action == game_input.QUIT:
                return "quit"
            if action == game_input.RESTART:
                return "restart"
            if action == game_input.PAUSE:
                paused = not paused
                tick_due = time.monotonic()
            elif action is not None:
                game.turn(action)
                if paused:  # steering resumes a paused game
                    paused = False
                    tick_due = time.monotonic()

            if not paused and now >= tick_due:
                tps = min(max_tps, start_tps + speedup * game.score)
                tick_due = now + 1.0 / tps
                if not game.step():
                    return "over"
                if game.won:
                    return "won"

            phase = 0.5 + 0.5 * math.sin(now * 6.0)
            self._present(game, 0.0 if paused else phase)
            time.sleep(max(0.0, frame - (time.monotonic() - now)))


def run_snake(*, field: str = "solid", wrap: bool = True, fps: float = 30.0,
              start_tps: float = 5.0, max_tps: float = 14.0,
              seed: int | None = None) -> int:
    """Play snake on the keyboard. Returns the best score of the session."""
    import random

    play_field = FIELDS[field](wrap)
    game = SnakeGame(play_field, random.Random(seed))
    best = 0
    with Keyboard() as kb:
        kb.take_control()
        runner = Runner(kb, Canvas(), fps=fps)
        try:
            with game_input.KeyReader() as keys:
                if not keys.available:
                    print("stdin is not a terminal, so there is no way to steer.")
                    return 0
                edges = "edges wrap" if wrap else "edges are lethal"
                print(f"Field {field}: {play_field.width}x{play_field.height}, "
                      f"{len(play_field.cells)} cells, {edges}.")
                if wrap and not play_field.walls:
                    print("Nothing to crash into but yourself.")
                print("Arrows or WASD to steer, p to pause, r to restart, q to quit.")
                while True:
                    keys.drain()
                    runner.sweep((0, 60, 120))
                    outcome = runner.play(game, keys, start_tps=start_tps,
                                          max_tps=start_tps)
                    best = max(best, game.score)
                    if outcome == "quit":
                        break
                    if outcome == "won":
                        print(f"Board filled. Score {game.score}.")
                        runner.flash((0, 255, 0), times=4)
                    elif outcome == "over":
                        print(f"Game over. Score {game.score}, best {best}.")
                        runner.flash((255, 0, 0))
                    game.reset()
        finally:
            kb.fill((0, 0, 0))
            kb.flush(force=True)
    return best
