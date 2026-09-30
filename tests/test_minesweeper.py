import random

from awcfree_lib import layout
from awcfree_lib.games.minesweeper import COUNT_COLOURS, Minesweeper
from awcfree_lib.games.snake import Field


FIELD = Field(2, 1, 10, 4)


def test_game_rectangle_is_fully_backed_by_measured_leds_and_avoids_f_row():
    assert len(FIELD.cells) == 40
    assert FIELD.cells <= set(layout.CELLS.values())
    assert all(y != 0 for _, y in FIELD.cells)


def test_first_reveal_is_safe_and_expands_empty_region():
    game = Minesweeper(FIELD, mines=8, rng=random.Random(42))
    opening = (6, 2)
    game.reveal(opening)
    assert game.started
    assert opening not in game.mines
    assert not (game.neighbours(opening) & game.mines)
    assert opening in game.revealed


def test_flag_and_reveal_win_state():
    game = Minesweeper(FIELD, mines=8, rng=random.Random(42))
    game.reveal((6, 2))
    mine = next(iter(game.mines))
    game.toggle_flag(mine)
    assert mine in game.flags
    for cell in FIELD.cells - game.mines:
        game.reveal(cell)
    assert game.won


def test_pressing_a_number_chords_when_neighbour_flags_match():
    game = Minesweeper(FIELD, mines=1, rng=random.Random(7))
    number = (2, 2)
    mine = (3, 2)
    game.started = True
    game.mines = {mine}
    game.revealed = {number}
    assert game.count(number) == 1
    assert not game.chord(number)
    game.toggle_flag(mine)
    assert game.chord(number)
    assert game.neighbours(number) - {mine} <= game.revealed
    assert not game.over


def test_chording_with_a_wrong_flag_can_hit_a_mine():
    game = Minesweeper(FIELD, mines=1, rng=random.Random(7))
    number = (2, 2)
    game.started = True
    game.mines = {(3, 2)}
    game.revealed = {number}
    game.flags = {(2, 1)}
    game.reveal(number)
    assert game.over and not game.won
    assert game.exploded == (3, 2)


def test_rainbow_count_colours_follow_f_key_order():
    assert [COUNT_COLOURS[i] for i in range(1, 7)] == [
        (255, 0, 0), (255, 92, 0), (205, 160, 0),
        (0, 145, 35), (0, 64, 220), (112, 15, 165),
    ]
    assert [layout.by_name(f"F{i}") for i in range(1, 7)] == [2, 3, 4, 5, 6, 7]
