"""Headless checks for studio navigation and existing lighting workflows.

Run with: QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -p test_gui.py
Hardware is mocked; no USB writes are made.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from awcfree_lib.gui import parts, theme
from awcfree_lib.gui.app import Hardware, MainWindow
from awcfree_lib.gui.model import Presets
from awcfree_lib import layout as kb_layout
from awcfree_lib.sounds.input import KeyboardDevice
from awcfree_lib.sounds.input import INPUT_EVENT


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.STYLESHEET)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for method in ("start", "stop", "submit"):
            patcher = patch.object(Hardware, method)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("awcfree_lib.gui.app.Presets", return_value=Presets(self.temp.name + "/presets.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.window.close)

    def test_navigation_and_tabs(self):
        w = self.window
        for part in parts.ALL:
            w.part_nav_buttons[part.key].click()
            self.assertEqual(w.stage_title.text(), part.name)
            self.assertEqual(w.stack.currentIndex(), w.effects_stack.currentIndex())
            self.assertEqual(w.kbview.isEnabled(), part.per_key)
            for tab in range(3):
                w.inspector.setCurrentIndex(tab)
                self.app.processEvents()
                self.assertFalse(w.grab().isNull())
        w.part_nav_buttons["keyboard"].click()
        self.assertEqual(w.part.key, "keyboard")
        w.part_nav_buttons["touchpad"].click()
        self.assertEqual(w.part.key, "touchpad")

    def test_games_live_in_the_left_workspace_navigation(self):
        w = self.window
        w.nav_buttons["games"].click()
        self.assertIs(w.workspaces.currentWidget(), w.games)
        w.games.mines_btn.click()
        self.assertEqual(w.games.mode, "mines")
        self.assertEqual(len(w.games.snake.field.cells), 40)
        w.nav_buttons["lighting"].click()
        self.assertEqual(w.workspaces.currentIndex(), 0)

    def test_minesweeper_keyboard_controls_and_round_states(self):
        w = self.window
        QTest.keyClick(w, Qt.Key.Key_M,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertIs(w.workspaces.currentWidget(), w.games)
        self.assertEqual(w.games.mode, "mines")
        self.assertEqual(w.games.mine_state, "ready")
        # Ctrl+the cap starts play and flags that measured square; a plain cap
        # press reveals its own square without using the mouse.
        QTest.keyClick(w.games.board, Qt.Key.Key_5, Qt.KeyboardModifier.ControlModifier)
        self.assertIn((5, 1), w.games.mines.flags)
        self.assertEqual(w.games.board.banner, "READY")
        QTest.keyClick(w.games.board, Qt.Key.Key_W)
        self.assertIn((2, 2), w.games.mines.revealed)
        self.assertEqual(w.games.mine_state, "playing")
        start = w.games.mine_cursor
        QTest.keyClick(w.games.board, Qt.Key.Key_Right)
        self.assertEqual(w.games.mine_cursor, (start[0] + 1, start[1]))
        QTest.keyClick(w.games.board, Qt.Key.Key_Return)
        self.assertTrue(w.games.mines.started)
        w.games.start_btn.click()
        self.assertEqual(w.games.mine_state, "ended")
        self.assertEqual(w.games.start_btn.text(), "Start game")
        self.assertEqual(w.games.board.banner, "ROUND OVER")

        game = w.games.mines
        game.started = True
        game.mines = {(3, 2)}
        game.revealed = {(2, 2)}
        game.flags.clear()
        game.over = game.won = False
        w.games.mine_state = "playing"
        w.games._draw_mines()
        QTest.keyClick(w.games.board, Qt.Key.Key_W)
        self.assertIn("Flag 1 more", w.games.status.text())
        QTest.keyClick(w.games.board, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
        self.assertIn((3, 2), game.flags)
        QTest.keyClick(w.games.board, Qt.Key.Key_W)
        self.assertTrue(game.neighbours((2, 2)) - game.mines <= game.revealed)

    def test_zombie_defense_uses_hold_and_release_keys(self):
        w = self.window
        w.nav_buttons["games"].click()
        w.games.defense_btn.click()
        self.assertEqual(w.games.mode, "defense")
        self.assertEqual(w.games.board.field.width, 16)
        self.assertEqual(w.games.board.field.y0, 2)
        self.assertEqual(w.games.board.field.height, 3)
        w.games.start_btn.click()
        self.assertEqual(w.games.defense_state, "playing")
        frame = w.hw.submit.call_args.args[-1]
        for name in ("TAB", "CAPSLOCK", "LSHIFT"):
            led = kb_layout.by_name(name)
            cell = kb_layout.CELLS[led]
            self.assertEqual(w.games.board.labels[cell], name)
            self.assertEqual(w.games.board.colours[cell], (30, 90, 255))
            self.assertEqual(frame[led], (30, 90, 255))
        grave = kb_layout.by_name("`")
        self.assertNotIn(kb_layout.CELLS[grave], w.games.board.field.cells)
        self.assertEqual(frame[grave], w.colours[grave])
        with patch.object(w.games.audio, "play") as play:
            QTest.keyPress(w.games.board, Qt.Key.Key_Tab)
            QTest.qWait(500)
            QTest.keyRelease(w.games.board, Qt.Key.Key_Tab)
            self.assertEqual(len(w.games.defense.bullets), 1)
            self.assertGreater(w.games.defense.bullets[0].damage, 1)
            self.assertEqual(w.games.defense.bullets[0].y,
                             kb_layout.CELLS[kb_layout.by_name("TAB")][1])
            play.assert_called_once_with("shot")
        w.games.start_btn.click()
        self.assertEqual(w.games.defense_state, "ended")
        self.assertEqual(w.games.board.banner, "ROUND OVER")

    def test_colour_effect_and_selection(self):
        w = self.window
        led = next(iter(w.colours))
        w.kbview.set_selection({led})
        w._set_colour(QColor("#7ee2c4"))
        self.assertEqual(w.colours[led], (126, 226, 196))
        self.assertEqual(sum(max(c) > 0 for c in w.colours.values()), 1)
        effect = next(iter(parts.KEYBOARD.pair_effects))
        w._run_effect("keyboard", effect)
        self.assertFalse(w.slot_b.isHidden())
        self.assertEqual(w.mode_label.text(), effect.replace("_", " ").upper())
        w._effect_off()
        self.assertTrue(w.slot_b.isHidden())
        self.assertEqual(w.mode_label.text(), "PER-KEY COLOUR")

    def test_saved_setup(self):
        w = self.window
        w._set_colour(QColor("#7ee2c4"))
        expected = dict(w.colours)
        w.preset_name.setText("Mint")
        w._save_preset()
        w._all_keys_off()
        w._load_preset("Mint")
        self.assertEqual(w.colours, expected)
        w._delete_preset("Mint")
        self.assertEqual(w.presets.names(), [])

    def test_keyboard_sounds_keep_typing_and_vary_enter_and_mute(self):
        w = self.window
        w.nav_buttons["sounds"].click()
        sounds = w.sounds
        sounds.scope.setCurrentIndex(0)
        self.assertIs(w.workspaces.currentWidget(), sounds)
        self.assertFalse(sounds.enabled)
        with patch.object(sounds.engine, "play") as play:
            sounds.pack_buttons["farts"].click()
            sounds.preview.setFocus()
            QTest.keyClick(sounds.preview, Qt.Key.Key_Enter)
            self.assertEqual(play.call_args.args[:2], ("farts", "KPENTER"))
            sounds.enable_btn.click()
            w.nav_buttons["lighting"].click()
            # An ignored key propagates from this button to the window: one sound.
            target = w.nav_buttons["lighting"]
            target.setFocus()
            play.reset_mock()
            QTest.keyClick(target, Qt.Key.Key_A)
            self.assertEqual(play.call_count, 1)
            first = play.call_args.args[2]
            QTest.keyClick(target, Qt.Key.Key_A)
            self.assertEqual(play.call_count, 2)
            self.assertNotEqual(first, play.call_args.args[2])
            w.hex.setFocus()
            w.hex.selectAll()
            QTest.keyClicks(w.hex, "#ff0000")
            self.assertEqual(w.hex.text(), "#ff0000")
            sounds.enable_btn.setChecked(False)
            play.reset_mock()
            QTest.keyClick(target, Qt.Key.Key_B)
            play.assert_not_called()

    def test_global_sound_input_does_not_duplicate_gui_and_reports_access_failure(self):
        sounds = self.window.sounds
        self.window.nav_buttons["sounds"].click()
        self.assertEqual(sounds.scope.currentData(), "app")
        sounds.scope.setCurrentIndex(1)
        with patch.object(sounds.listener, "start") as start, patch.object(sounds.engine, "play") as play:
            sounds.enable_btn.click()
            start.assert_called_once()
            sounds.preview.setFocus()
            QTest.keyClick(sounds.preview, Qt.Key.Key_A)
            play.assert_not_called()
            sounds.listener.pressed.emit("ENTER")
            self.assertEqual(play.call_args.args[1], "ENTER")
            # Native presses keep playing after focus loss and minimization.
            self.window.showMinimized()
            QTest.qWait(20)
            with patch.object(self.window, "isActiveWindow", return_value=False):
                sounds.listener.pressed.emit("SPACE")
                self.assertEqual(play.call_args.args[1], "SPACE")
            sounds.enable_btn.setChecked(False)
            play.reset_mock()
            sounds.listener.pressed.emit("A")
            play.assert_not_called()
        with patch.object(sounds.listener, "start", side_effect=OSError("Keyboard access denied")), \
             patch.object(sounds, "_selected_devices", return_value=[]):
            sounds.enable_btn.click()
            self.assertFalse(sounds.enabled)
            self.assertFalse(sounds.enable_btn.isChecked())
            self.assertEqual(sounds.status.text(), "Keyboard access denied")

    def test_enable_handles_background_setup_cancel_success_and_retry_failure(self):
        sounds = self.window.sounds
        self.window.nav_buttons["sounds"].click()
        sounds.scope.setCurrentIndex(1)
        sounds.devices.clear()
        device = KeyboardDevice("/dev/input/event3", "Test keyboard")
        sounds.devices.addItem(device.name, device)
        for code, retry_fails in ((126, False), (0, False), (0, True)):
            process = Mock()
            process.readAllStandardError.return_value = b""
            outcomes = [OSError("Permission denied"), OSError("Still denied") if retry_fails else None]
            with patch("awcfree_lib.gui.sounds.shutil.which", return_value="/usr/bin/pkexec"), \
                 patch("awcfree_lib.gui.sounds.QProcess", return_value=process) as process_type, \
                 patch.object(sounds.listener, "uses_x11", return_value=False), \
                 patch.object(sounds.listener, "start", side_effect=outcomes) as start:
                process_type.ExitStatus = QProcess.ExitStatus
                process_type.ProcessError = QProcess.ProcessError
                sounds.enable_btn.click()
                self.assertFalse(sounds.enable_btn.isEnabled())
                self.assertFalse(sounds.scope.isEnabled())
                self.assertFalse(sounds.enabled)
                arguments = process.start.call_args.args
                self.assertEqual(arguments[0], "/usr/bin/pkexec")
                self.assertEqual(arguments[1][-2:], ["--device", "event3"])
                sounds._setup_access()
                process.start.assert_called_once()
                sounds._setup_finished(code, QProcess.ExitStatus.NormalExit)
                self.assertTrue(sounds.enable_btn.isEnabled())
                self.assertTrue(sounds.devices.isEnabled())
                self.assertTrue(sounds.scope.isEnabled())
                process.deleteLater.assert_called_once()
                self.assertEqual(sounds.enabled, code == 0 and not retry_fails)
                self.assertEqual(sounds.enable_btn.isChecked(), sounds.enabled)
                self.assertEqual(start.call_count, 1 if code else 2)
                sounds.enable_btn.setChecked(False)

    def test_background_press_does_not_display_or_pass_letter_identity(self):
        sounds = self.window.sounds
        sounds.preview.setText("A\nPrevious audition")
        sounds.scope.setCurrentIndex(1)
        self.assertNotIn("Previous audition", sounds.preview.text())
        with patch.object(sounds.listener, "start"), patch.object(sounds.engine, "play") as play:
            sounds.enable_btn.click()
            preview = sounds.preview.text()
            sounds.listener.pressed.emit("A")
            self.assertEqual(play.call_args.args[1], "KEY")
            self.assertEqual(sounds.preview.text(), preview)

    def test_app_typing_outside_audition_does_not_display_key_names(self):
        sounds = self.window.sounds
        self.window.nav_buttons["sounds"].click()
        with patch.object(sounds.engine, "play") as play:
            sounds.enable_btn.click()
            preview = sounds.preview.text()
            target = sounds.pack_buttons["gaming"]
            target.setFocus()
            QTest.keyClick(target, Qt.Key.Key_A)
            self.assertTrue(play.called)
            self.assertEqual(sounds.preview.text(), preview)
            sounds.preview.setFocus()
            QTest.keyClick(sounds.preview, Qt.Key.Key_B)
            self.assertEqual(sounds.preview.text(), preview)

    def test_enter_without_accent_uses_the_ordinary_shuffle_bag(self):
        sounds = self.window.sounds
        sounds.accent.setChecked(False)
        with patch.object(sounds.picker, "next", return_value=0) as pick, \
             patch.object(sounds.engine, "play"):
            sounds._play("ENTER")
            pick.assert_called_once_with("gaming", "normal")

    def test_external_keyboard_native_events_play_while_main_window_is_minimized(self):
        sounds = self.window.sounds
        sounds.scope.setCurrentIndex(1)
        self.assertIsNone(sounds.devices.currentData())
        devices = [KeyboardDevice("/dev/input/event3", "Laptop"),
                   KeyboardDevice("/dev/input/event7", "External")]
        pipes = [os.pipe(), os.pipe()]
        try:
            with patch.object(sounds.listener, "uses_x11", return_value=False), \
                 patch("awcfree_lib.sounds.input.keyboard_devices", return_value=devices), \
                 patch("awcfree_lib.sounds.input.os.open", side_effect=[p[0] for p in pipes]), \
                 patch.object(sounds.engine, "play") as play:
                sounds.enable_btn.click()
                self.assertTrue(sounds.enabled)
                self.assertEqual(len(sounds.listener.streams), 2)
                self.window.showMinimized()
                QTest.qWait(20)
                with patch.object(self.window, "isActiveWindow", return_value=False):
                    os.write(pipes[1][1], INPUT_EVENT.pack(0, 0, 1, 28, 1))
                    QTest.qWait(20)
                play.assert_called_once()
                self.assertEqual(play.call_args.args[1], "ENTER")
                self.assertIn("External", sounds.capture_note.text())
        finally:
            sounds.enable_btn.setChecked(False)
            for _, writer in pipes: os.close(writer)


if __name__ == "__main__":
    unittest.main()
