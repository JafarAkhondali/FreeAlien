"""Small keyboard-lane defense game rules, independent of Qt and hardware."""
from __future__ import annotations

from dataclasses import dataclass
import random

from .. import layout

Cell = tuple[int, int]


@dataclass
class Zombie:
    x: float
    y: int
    health: int
    maximum: int


@dataclass
class Bullet:
    x: float
    y: int
    damage: int
    splash: bool


class DefenseGame:
    """Zombies advance left through three keyboard rows; charged shots splash below."""

    FIRING_CELLS = {name: layout.CELLS[layout.by_name(name)]
                    for name in ("TAB", "CAPSLOCK", "LSHIFT")}
    LANES = tuple(cell[1] for cell in FIRING_CELLS.values())

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.reset()

    def reset(self) -> None:
        self.zombies: list[Zombie] = []
        self.bullets: list[Bullet] = []
        self.score = 0
        self.wave = 0
        self.over = False
        self.spawn_clock = 0

    def spawn(self, lane: int | None = None, health: int | None = None) -> Zombie:
        lane = lane if lane in self.LANES else self.rng.choice(self.LANES)
        health = health or self.rng.randint(2, 4)
        zombie = Zombie(15.0, lane, health, health)
        self.zombies.append(zombie)
        return zombie

    def shoot(self, lane: int, charge: float = 0.0) -> Bullet:
        """Charge ranges 0..1; full charge pierces its row and splashes lower rows."""
        charge = min(1.0, max(0.0, charge))
        bullet = Bullet(1.0, lane, 1 + int(charge * 3), charge >= 0.55)
        self.bullets.append(bullet)
        return bullet

    def step(self, dt: float = 0.08) -> list[str]:
        """Advance one frame and return hit/kill sounds in occurrence order."""
        if self.over:
            return []
        sounds: list[str] = []
        self.spawn_clock += dt
        spawn_period = max(0.72, 2.6 - self.wave * 0.08)
        if self.spawn_clock >= spawn_period:
            self.spawn_clock -= spawn_period
            self.wave += 1
            self.spawn()
            if self.wave % 4 == 0:
                self.spawn()

        for bullet in self.bullets:
            bullet.x += 0.55
        self.bullets = [b for b in self.bullets if b.x <= 15]

        speed = 0.17 + min(0.10, self.wave * 0.004)
        for zombie in self.zombies:
            zombie.x -= speed

        for bullet in list(self.bullets):
            target = next((z for z in sorted(self.zombies, key=lambda z: z.x)
                           if z.y == bullet.y and abs(z.x - bullet.x) < 0.62), None)
            if target is None:
                continue
            self.bullets.remove(bullet)
            affected = [target]
            if bullet.splash:
                affected += [z for z in self.zombies
                             if z is not target and z.x <= target.x + 0.8
                             and abs(z.x - target.x) <= 1.0
                             and target.y < z.y <= 5]
            for zombie in affected:
                zombie.health -= bullet.damage
            sounds.append("hit")
            killed = [z for z in affected if z.health <= 0]
            if killed:
                self.zombies = [z for z in self.zombies if z not in killed]
                self.score += len(killed)
                sounds.append("kill")

        if any(z.x <= 0.35 for z in self.zombies):
            self.over = True
        return sounds

    @staticmethod
    def health_brightness(zombie: Zombie) -> float:
        return max(0.18, zombie.health / zombie.maximum)
