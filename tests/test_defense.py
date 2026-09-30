"""Zombie Defense simulation tests; no keyboard or sound device required."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from awcfree_lib.games.defense import DefenseGame  # noqa: E402


def test_shot_hits_and_kills_with_distinct_sound_events():
    game = DefenseGame()
    zombie = game.spawn(2, health=2)
    zombie.x = 1.4
    game.shoot(2, charge=0.0)
    assert game.step(0.0) == ["hit"]
    assert zombie.health == 1
    game.shoot(2, charge=1.0)
    assert game.step(0.0) == ["hit", "kill"]
    assert game.score == 1
    assert not game.zombies


def test_charged_shot_damages_zombies_in_lower_lanes():
    game = DefenseGame()
    front = game.spawn(2, health=6)
    lower = game.spawn(3, health=6)
    front.x = lower.x = 1.4
    game.shoot(2, charge=1.0)
    assert game.step(0.0) == ["hit"]
    assert front.health == 2
    assert lower.health == 2


def test_zombie_health_is_rendered_as_relative_brightness():
    game = DefenseGame()
    zombie = game.spawn(4, health=4)
    full = game.health_brightness(zombie)
    zombie.health = 1
    assert game.health_brightness(zombie) == 0.25
    assert full > game.health_brightness(zombie)


def test_breach_ends_round():
    game = DefenseGame()
    game.spawn(2, health=2).x = 0.4
    game.step(0.0)
    assert game.over
