"""Offline T-Rex runner simulation; independent of Qt and hardware."""
from __future__ import annotations

from dataclasses import dataclass
import math
import random


@dataclass
class Obstacle:
    x: float
    bottom: float = 0
    width: float = 24
    height: float = 38
    kind: str = "cactus"


class TrexGame:
    WIDTH = 900
    PLAYER_X = 110

    def __init__(self, rng=None, high_score=0):
        self.rng = rng or random.Random()
        self.high_score = max(0, int(high_score))
        self.reset()

    def reset(self):
        self.state = "ready"
        self.y = self.velocity = self.distance = self.elapsed = 0.0
        self.ducking = False
        self.obstacles = []
        self.spawn_in = 1.8
        self.milestone = 0

    @property
    def score(self):
        return int(self.distance / 30)

    @property
    def speed(self):
        return min(360, 240 + self.score * .18)

    @property
    def night(self):
        return (self.score // 700) % 2 == 1

    @property
    def player_box(self):
        duck = self.ducking and self.y == 0
        return (self.PLAYER_X, self.y, 48 if duck else 30, 23 if duck else 44)

    def start(self):
        if self.state == "over":
            self.reset()
        self.state = "running"

    def pause(self):
        if self.state == "running":
            self.state = "paused"
        self.ducking = False
        self.release_jump()

    def jump(self):
        if self.state in ("ready", "over"):
            self.start()
        if self.state == "running" and self.y == 0 and not self.ducking:
            self.velocity = 600
            self.y = .01
            return True
        return False

    def release_jump(self):
        self.velocity = min(self.velocity, 500)

    def _spawn(self):
        if self.score >= 100 and self.rng.random() < .3:
            return Obstacle(self.WIDTH, self.rng.choice((0, 28, 65)), 42, 24, "bird")
        return Obstacle(self.WIDTH, 0, self.rng.choice((20, 32, 48)),
                        self.rng.choice((30, 42, 50)))

    def step(self, dt):
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        events = []
        # Small substeps prevent tunnelling at high speed; ignore long UI stalls.
        remaining = min(dt, .25)
        while remaining > 1e-9 and self.state == "running":
            delta = min(remaining, 1 / 120)
            remaining -= delta
            self.elapsed += delta
            if self.y > 0:
                self.velocity -= (4200 if self.ducking else 1200) * delta
                self.y = max(0, self.y + self.velocity * delta)
                if self.y == 0:
                    self.velocity = 0
            travel = self.speed * delta
            self.distance += travel
            self.spawn_in -= delta
            if self.spawn_in <= 0:
                self.obstacles.append(self._spawn())
                self.spawn_in = self.rng.uniform(1.15, 1.85)
            px, py, pw, ph = self.player_box
            for obstacle in self.obstacles:
                obstacle.x -= travel
                if (px + 3 < obstacle.x + obstacle.width - 3
                        and px + pw - 3 > obstacle.x + 3
                        and py + 3 < obstacle.bottom + obstacle.height - 3
                        and py + ph - 3 > obstacle.bottom + 3):
                    self.state = "over"
                    self.ducking = False
                    events.append("hit")
                    break
            self.obstacles = [o for o in self.obstacles if o.x + o.width > 0]
            self.high_score = max(self.high_score, self.score)
            if self.score // 100 > self.milestone:
                self.milestone = self.score // 100
                events.append("kill")
        return events

    @property
    def jump_cue(self):
        """A stable warning roughly 400 ms before a ground hazard reaches us."""
        if self.state != "running" or self.y > 0 or self.ducking:
            return False
        x, _, width, _ = self.player_box
        return any(o.bottom < 23 and 0 <= (o.x + 3 - (x + width - 3)) / self.speed <= .4
                   for o in self.obstacles)

    def led_colours(self, field):
        colours = {cell: ((3, 7, 18) if self.night else (16, 24, 30))
                   for cell in field.cells}
        def draw(x, bottom, width, height, colour):
            # Compress the track onto the physical key block, retaining height.
            left = field.x0 + int(x / self.WIDTH * field.width)
            right = field.x0 + int((x + width) / self.WIDTH * field.width)
            low = field.y0 + field.height - 1 - int(bottom / 40)
            high = field.y0 + field.height - 1 - int((bottom + height - 1) / 40)
            for cell in colours:
                if left <= cell[0] <= right and high <= cell[1] <= low:
                    colours[cell] = colour
        for o in self.obstacles:
            draw(o.x, o.bottom, o.width, o.height,
                 (255, 170, 0) if o.kind == "bird" else (255, 50, 20))
        draw(*self.player_box, (255, 0, 0) if self.state == "over" else
             (255, 255, 255) if self.jump_cue else (80, 255, 170))
        return colours
