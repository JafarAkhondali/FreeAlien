"""Snake rules, played headless.

The game holds no I/O, so entire games run here with no keyboard attached. The
awkward cases -- eating, reversing, chasing your own tail -- are the ones worth
pinning, because they are where a snake implementation usually goes wrong.
"""
from __future__ import annotations

import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from awcfree_lib import layout  # noqa: E402
from awcfree_lib.canvas import Canvas  # noqa: E402
from awcfree_lib.games import Field, SnakeGame, rect_field, solid_field  # noqa: E402


def plain(width=8, height=5, wrap=False) -> Field:
    """A clean field, independent of this machine's key layout.

    Defaults to lethal edges even though the game's own default wraps, so the tests
    that care about walls have to opt in explicitly either way.
    """
    return Field(0, 0, width, height, frozenset(), wrap)


def test_solid_field_has_no_holes():
    f = solid_field()
    occupied = set(layout.CELLS.values())
    assert f.walls == frozenset()
    missing = [c for c in f.cells if c not in occupied]
    assert not missing, f"solid field contains cells with no LED: {missing}"
    assert len(f.cells) == f.width * f.height
    print(f"  ok  solid field {f.width}x{f.height}, {len(f.cells)} cells, all lit")


def test_wider_fields_mark_holes_as_walls():
    f = rect_field(0, 0, layout.GRID_COLS, layout.GRID_ROWS)
    occupied = set(layout.CELLS.values())
    assert f.walls, "the full board does have holes"
    for w in f.walls:
        assert w not in occupied, f"{w} is a wall but has an LED"
    assert not (f.cells & f.walls)
    print(f"  ok  full field marks {len(f.walls)} holes as walls")


def test_moves_and_keeps_length():
    g = SnakeGame(plain(), random.Random(1))
    before = list(g.body)
    g.food = None
    assert g.step()
    assert len(g.body) == len(before)
    assert g.head == (before[0][0] + 1, before[0][1])
    print("  ok  moving keeps length and advances the head")


def test_eating_grows_and_scores():
    g = SnakeGame(plain(), random.Random(2))
    hx, hy = g.head
    g.food = (hx + 1, hy)
    n = len(g.body)
    assert g.step()
    assert g.score == 1, g.score
    assert len(g.body) == n + 1, (n, len(g.body))
    print("  ok  eating grows the snake by one and scores")


def test_wall_kills():
    g = SnakeGame(plain(width=4, height=3), random.Random(3))
    g.food = None
    for _ in range(10):
        if not g.step():
            break
    assert not g.alive
    print("  ok  running into the edge ends the game")


def test_wrapping_is_the_default():
    """A field built the normal way wraps; only opting out makes edges lethal."""
    assert Field(0, 0, 4, 3).wrap is True
    assert solid_field().wrap is True
    assert rect_field(0, 0, 4, 3).wrap is True
    assert solid_field(wrap=False).wrap is False
    print("  ok  fields wrap unless asked not to")


def test_teleports_on_all_four_edges():
    """Each edge must hand the snake to the opposite side, not kill it."""
    cases = {
        "right": ((3, 1), "right", (0, 1)),
        "left":  ((0, 1), "left",  (3, 1)),
        "up":    ((1, 0), "up",    (1, 2)),
        "down":  ((1, 2), "down",  (1, 0)),
    }
    for name, (start, direction, expected) in cases.items():
        g = SnakeGame(plain(width=4, height=3, wrap=True), random.Random(0),
                      start_length=1)
        g.body.clear(); g.occupied.clear()
        g.body.append(start); g.occupied.add(start)
        g.food = None
        g.turn(direction)
        assert g.step(), f"died stepping off the {name} edge"
        assert g.head == expected, f"{name}: landed on {g.head}, expected {expected}"
    print("  ok  all four edges teleport to the opposite side")


def test_only_self_collision_can_kill_on_a_wrapping_solid_field():
    """On the default field there is nothing to die on except yourself."""
    rng = random.Random(21)
    f = solid_field()
    assert f.wrap and not f.walls
    deaths = self_hits = 0
    for seed in range(60):
        g = SnakeGame(f, random.Random(seed))
        for _ in range(500):
            g.turn(rng.choice(("up", "down", "left", "right")))
            head_before = g.head
            dx, dy = g.direction if not g._pending else g._pending[0]
            target = f.normalise((head_before[0] + dx, head_before[1] + dy))
            if not g.step():
                deaths += 1
                # the only legal cause of death: the cell entered was the body
                assert f.contains(target), (
                    f"died on {target}, which is outside a wrapping wall-free field")
                self_hits += 1
                break
    assert deaths, "expected some deaths from self-collision"
    assert deaths == self_hits, f"{deaths - self_hits} deaths were not self-collisions"
    print(f"  ok  {deaths} deaths across 60 games, every one a self-collision")


def test_wrap_does_not_kill():
    g = SnakeGame(plain(width=4, height=3, wrap=True), random.Random(3))
    g.food = None
    for _ in range(12):
        assert g.step(), "wrapping field should not kill at the edge"
    assert g.alive
    assert g.field.contains(g.head)
    print("  ok  a wrapping field carries the snake round the edge")


def test_cannot_reverse_into_itself():
    g = SnakeGame(plain(), random.Random(4))
    g.food = None
    g.turn("left")            # currently heading right
    assert g.step()
    assert g.alive, "a straight reverse must be ignored, not fatal"
    print("  ok  reversing straight back is ignored")


def test_two_turns_in_one_tick_do_not_reverse():
    """Up then left while moving right must not fold the snake back on itself."""
    g = SnakeGame(plain(), random.Random(5))
    g.food = None
    g.turn("up")
    g.turn("left")            # would be a reverse of the *old* direction
    assert g.step()
    assert g.alive
    assert g.direction == (0, -1), g.direction
    assert g.step() and g.alive
    print("  ok  queued turns cannot combine into a reverse")


def test_following_own_tail_is_legal():
    """The tail vacates its cell as the snake moves, so entering it is fine."""
    g = SnakeGame(plain(), random.Random(6), start_length=4)
    g.food = None
    for name in ("up", "left", "down"):
        g.turn(name)
        assert g.step(), f"died turning {name} onto the vacating tail"
    assert g.alive
    print("  ok  moving into the vacating tail cell is allowed")


def test_biting_body_kills():
    g = SnakeGame(plain(), random.Random(7), start_length=5)
    g.food = None
    # a tight square turns the head into the body
    for name in ("up", "left", "down", "right"):
        g.turn(name)
        if not g.step():
            break
    assert not g.alive, "a full loop of a 5-long snake must bite itself"
    print("  ok  biting the body ends the game")


def test_food_never_lands_on_the_snake():
    g = SnakeGame(plain(), random.Random(8))
    for _ in range(300):
        if g.food is not None:
            assert g.food not in g.occupied, "food placed on the snake"
            assert g.field.contains(g.food), "food placed outside the field"
        hx, hy = g.head
        if g.food:
            fx, fy = g.food
            g.turn("right" if fx > hx else "left" if fx < hx else
                   "down" if fy > hy else "up")
        if not g.step():
            g.reset()
    print("  ok  food always lands on a free playable cell")


def test_filling_the_board_is_a_win():
    g = SnakeGame(plain(width=3, height=2), random.Random(9), start_length=1)
    g.body.clear(); g.occupied.clear()
    for cell in sorted(g.field.cells):
        g.body.append(cell); g.occupied.add(cell)
    g.food = None
    assert g.won, "a snake covering every cell has won"
    print("  ok  covering the board counts as a win")


def test_render_draws_head_body_and_food():
    g = SnakeGame(solid_field(), random.Random(10))
    canvas = Canvas()
    g.render(canvas, phase=1.0)
    lit = [canvas[c] for c in g.body]
    assert lit[0] == (255, 255, 255), lit[0]
    assert all(c != (0, 0, 0) for c in lit), "a body segment was left unlit"
    assert canvas[g.food] != (0, 0, 0), "food not drawn"
    leds = canvas.to_leds()
    assert all(l in layout.CELLS for l in leds)
    print(f"  ok  render lit {sum(1 for v in leds.values() if v != (0,0,0))} LEDs")


def test_long_random_games_never_break_invariants():
    rng = random.Random(11)
    games = deaths = 0
    for seed in range(40):
        g = SnakeGame(solid_field(), random.Random(seed))
        for _ in range(400):
            g.turn(rng.choice(("up", "down", "left", "right")))
            alive = g.step()
            assert len(g.occupied) == len(set(g.body)), "occupied set desynced"
            assert all(g.field.contains(c) for c in g.body), "a segment left the field"
            if not alive:
                deaths += 1
                break
        games += 1
    print(f"  ok  {games} random games, {deaths} deaths, invariants held throughout")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        print(f"{fn.__name__}:")
        try:
            fn()
        except AssertionError as exc:
            print(f"  FAIL {exc}")
            failed.append(fn.__name__)
    print()
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
