"""Runner physics and Qt input integration without hardware."""
import random
from unittest.mock import Mock

import pytest

from awcfree_lib.games.trex import Obstacle, TrexGame
from awcfree_lib.games.snake import Field


def advance(game, seconds):
    for _ in range(round(seconds * 120)):
        game.step(1 / 120)


def test_jump_height_release_and_no_double_jump():
    high, low = TrexGame(), TrexGame()
    for g in (high, low):
        assert g.jump()
        assert not g.jump()
        g.spawn_in = 100
    low.release_jump()
    advance(high, .25)
    advance(low, .25)
    assert high.y > low.y
    advance(high, 1)
    assert high.y == 0 and high.velocity == 0


def test_cactus_collision_and_jump_clearance():
    for jumping in (False, True):
        g = TrexGame()
        g.start()
        if jumping:
            g.jump()
            advance(g, .2)
        g.obstacles = [Obstacle(g.PLAYER_X + 5)]
        g.step(.01)
        assert (g.state == "running") == jumping


def test_duck_avoids_mid_bird_but_not_low_bird():
    for bottom, duck, survives in ((28, True, True), (28, False, False), (0, True, False)):
        g = TrexGame()
        g.start()
        g.ducking = duck
        g.obstacles = [Obstacle(g.PLAYER_X + 5, bottom, 42, 24, "bird")]
        g.step(.01)
        assert (g.state == "running") == survives


def test_fast_fall_pause_and_restart():
    g = TrexGame(high_score=123)
    g.jump()
    advance(g, .2)
    g.ducking = True
    advance(g, .4)
    assert g.y == 0
    g.pause()
    before = g.distance
    advance(g, 2)
    assert g.distance == before and not g.ducking
    g.reset()
    assert g.high_score == 123 and g.score == 0 and g.state == "ready"


def test_difficulty_night_milestone_and_led_bounds():
    g = TrexGame(random.Random(4))
    g.start()
    g.distance = 2999
    assert "kill" in g.step(.02)
    g.distance = 21000
    assert g.night
    g.distance = 42000
    assert not g.night and g.speed == 360
    field = Field(2, 1, 10, 4)
    assert set(g.led_colours(field)) == field.cells
    kinds = {g._spawn().kind for _ in range(100)}
    assert kinds == {"bird", "cactus"}
    with pytest.raises(ValueError):
        g.step(float("nan"))


def test_qt_keyboard_pause_restart_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from awcfree_lib.gui.games import GamesPage
    from awcfree_lib.gui.trex import load_score
    app = QApplication.instance() or QApplication([])
    restore = Mock()
    page = GamesPage(Mock(), lambda: {}, restore)
    page.audio.play = Mock()
    page.show()
    page.activateWindow()
    page.set_mode("trex")
    app.processEvents()
    try:
        QTest.keyPress(page.trex_view, Qt.Key.Key_Space)
        assert page.trex.state == "running" and page.trex.velocity == 600
        QTest.keyRelease(page.trex_view, Qt.Key.Key_Space)
        assert page.trex.velocity == 500
        QTest.keyPress(page.trex_view, Qt.Key.Key_Down)
        assert page.trex.ducking
        QTest.keyRelease(page.trex_view, Qt.Key.Key_Down)
        assert not page.trex.ducking
        page.trex.high_score = 345
        QTest.keyClick(page.trex_view, Qt.Key.Key_P)
        assert page.trex.state == "paused" and not page.timer.isActive()
        assert not page.applied and restore.called
        assert load_score() == 345
        QTest.keyClick(page.trex_view, Qt.Key.Key_P)
        assert page.trex.state == "running"
        QTest.keyClick(page.trex_view, Qt.Key.Key_R)
        assert page.trex.score == 0 and page.timer.isActive()
        # Exercise the vector paint path while running and at night.
        assert not page.trex_view.grab().isNull()
        page.trex.distance = 21000
        assert not page.trex_view.grab().isNull()
        app.sendEvent(page, QEvent(QEvent.Type.WindowDeactivate))
        assert page.trex.state == "paused" and not page.timer.isActive()
        assert not page.applied
        page.toggle_run()
        page.set_mode("snake")
        assert not page.timer.isActive() and page.trex.state == "paused"
    finally:
        page.stop()
        page.close()
        app.removeEventFilter(page)


@pytest.mark.parametrize("reaction", [0, .15, .2])
@pytest.mark.parametrize("score", [0, 300, 1000])
@pytest.mark.parametrize("width", [20, 32, 48])
def test_led_warning_allows_reaction_and_tap_over_tall_cactus(score, width, reaction):
    g = TrexGame()
    g.start()
    g.distance = score * 30
    g.spawn_in = 100
    # Enter the cue window and allow time to see it and react.
    front = g.PLAYER_X + 30 - 6
    g.obstacles = [Obstacle(front + g.speed * .399, 0, width, 50)]
    assert g.jump_cue
    field = Field(2, 1, 10, 4)
    assert (255, 255, 255) in g.led_colours(field).values()
    advance(g, reaction)
    assert g.jump()
    g.release_jump()
    assert not g.jump_cue
    advance(g, 1)
    assert g.state == "running"
    assert not any(o.x + o.width > g.PLAYER_X for o in g.obstacles)


def test_led_dinosaur_occupies_one_column_and_warning_excludes_high_birds():
    g = TrexGame()
    field = Field(2, 1, 10, 4)
    lit = [cell for cell, rgb in g.led_colours(field).items() if rgb == (80, 255, 170)]
    assert len({x for x, y in lit}) == 1
    g.start()
    g.obstacles = [Obstacle(200, 65, 42, 24, "bird")]
    assert not g.jump_cue
