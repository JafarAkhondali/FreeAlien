"""Regression checks for queued hardware state and Qt control events."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtGui import QColor
from awcfree_lib.gui import parts
from awcfree_lib.gui.app import Hardware
import test_gui

original_hardware_submit = Hardware.submit


class HardwareEventTests(unittest.TestCase):
    def drain(self, hw):
        done = threading.Event()
        hw.submit("barrier", done.set)
        with patch.object(hw, "_open"):
            hw.start()
            try:
                self.assertTrue(done.wait(2), "worker did not drain")
            finally:
                hw.stop()

    def test_closing_drains_pending_colour(self):
        hw = Hardware()
        hw.keyboard = Mock()
        hw.submit("keyboard", hw.write_keys, {1: (255, 0, 0)})
        with patch.object(hw, "_open"):
            hw.start()
            hw.stop()
        hw.keyboard.set_many.assert_called_once_with({1: (255, 0, 0)})
        hw.keyboard.close.assert_called_once()

    def test_power_update_only_writes_requested_profiles(self):
        from awcfree_lib.protocol import v4
        hw = Hardware()
        hw.chassis = Mock()
        hw.set_power_profiles((255, 0, 0), None)
        self.assertEqual([c.args[0] for c in hw.chassis.set_power_profile.call_args_list],
                         [name for name in v4.POWER_PROFILES if name.startswith("ac")])

    def test_latest_keyboard_action_wins(self):
        hw = Hardware()
        hw.keyboard = Mock()
        # The final paint must replace both an old paint and a queued effect.
        hw.submit("keyboard", hw.write_keys, {1: (255, 0, 0)})
        hw.submit("keyboard", hw.run_effect, "breathing", (0, 255, 0), (0, 0, 0), 100)
        hw.submit("keyboard", hw.write_keys, {1: (0, 0, 255)})
        self.assertEqual(hw._jobs.qsize(), 1)
        self.drain(hw)
        hw.keyboard.effect.assert_not_called()
        hw.keyboard.set_many.assert_called_once_with({1: (0, 0, 255)})

    def test_paint_after_running_effect_takes_control(self):
        hw = Hardware()
        hw.keyboard = Mock()
        hw.run_effect("breathing", (255, 0, 0), (0, 0, 0), 100)
        # Coalescing may discard the first paint's explicit take-control request.
        hw.submit("keyboard", hw.keys_take_control, {1: (0, 255, 0)})
        hw.submit("keyboard", hw.write_keys, {1: (0, 0, 255)})
        self.drain(hw)
        hw.keyboard.take_control.assert_called_once()
        hw.keyboard.set_many.assert_called_once_with({1: (0, 0, 255)})


class ControlEventTests(test_gui.StudioTests):
    def test_rapid_actions_deliver_final_rgb_packets(self):
        from awcfree_lib.devices.keyboard import Keyboard
        from awcfree_lib.protocol import v5
        w = self.window
        transport_keyboard = Keyboard(path="/unused")
        transport_keyboard.dev = Mock()
        w.hw.keyboard = transport_keyboard
        # Use the real coalescing queue rather than the UI test's submit mock.
        with patch.object(Hardware, "submit", original_hardware_submit):
            w._set_colour(QColor("#ff0000"))
            w._run_effect("keyboard", "breathing")
            w._effect_off()
            w._set_colour(QColor("#0000ff"))
        with patch.object(w.hw, "_open"):
            w.hw._jobs.put(None)
            w.hw._run()
        packets = [c.args[0] for c in transport_keyboard.dev.send_feature.call_args_list]
        records = dict(record for packet in packets for record in v5.iter_records(packet))
        self.assertEqual(records, {led: (0, 0, 255) for led in w.colours})
        self.assertIn(v5.EFFECT_OFF, packets)
        self.assertFalse(any(p[1] == 0x80 and p != v5.EFFECT_OFF for p in packets))

    def test_hex_edit_and_surface_click_targets_old_surface(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        w = self.window
        w.hex.setFocus()
        w.hex.selectAll()
        QTest.keyClicks(w.hex, "#ff0000")
        w.part_nav_buttons["touchpad"].click()
        self.assertEqual(set(w.colours.values()), {(255, 0, 0)})
        self.assertEqual(w.zone_colours[parts.TOUCHPAD.zone], (0, 0, 0))
        self.assertEqual(w.hw.submit.call_count, 1)

    def test_selection_survives_surface_switch(self):
        w = self.window
        led = next(iter(w.colours))
        w.kbview.set_selection({led})
        w.part_nav_buttons["logo"].click()
        w.part_nav_buttons["keyboard"].click()
        w._set_colour(QColor("#ff0000"))
        self.assertEqual(sum(max(c) > 0 for c in w.colours.values()), 1)

    def test_persistence_toggle_applies_to_current_effect_and_paint(self):
        w = self.window
        w.part_nav_buttons["touchpad"].click()
        w._run_effect("touchpad", "breathe")
        w._persist_touchpad.setChecked(True)
        self.assertTrue(w.hw.submit.call_args.args[-1])
        self.assertEqual(w.hw.submit.call_args.args[3], "breathe")
        w._paint()
        self.assertEqual(w.hw.submit.call_args.args[3], "static")
        self.assertTrue(w.hw.submit.call_args.args[-1])

    def test_dual_colours_editable_in_effects_tab(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        w = self.window
        w.inspector.setCurrentIndex(1)
        for part in (parts.KEYBOARD, parts.TOUCHPAD, parts.LOGO):
            w.part_nav_buttons[part.key].click()
            for effect in part.pair_effects:
                getattr(w, f"_fx_{part.key}")[effect].click()
                self.app.processEvents()
                controls = w.effect_colour_controls[part.key]
                self.assertTrue(controls["a"][0].isVisible())
                self.assertTrue(controls["b"][0].isVisible())
                self.assertIn("A+B", getattr(w, f"_fx_{part.key}")[effect].text())
                primary = w._rgb()
                edit = controls["b"][2]
                edit.setFocus()
                edit.selectAll()
                QTest.keyClicks(edit, "#ff2200")
                QTest.keyClick(edit, Qt.Key.Key_Return)
                self.assertEqual(w._rgb(), primary)
                self.assertEqual(w._rgb_b(), (255, 34, 0))
                args = w.hw.submit.call_args.args
                self.assertEqual(args[3:5] if part.per_key else args[4:6],
                                 (primary, (255, 34, 0)))
                self.assertEqual(w.effect_choice[part.key], effect)
                self.assertEqual(w.inspector.currentIndex(), 1)

    def test_effect_colour_controls_follow_mode_and_picker(self):
        w = self.window
        w._run_effect("keyboard", "double_wave")
        w._use_slot("b")
        w._set_colour(QColor("#00ff00"))
        controls = w.effect_colour_controls["keyboard"]
        self.assertEqual(controls["b"][2].text(), "#00ff00")
        w._run_effect("keyboard", "breathing")
        self.assertTrue(controls["b"][0].isHidden())
        w._run_effect("keyboard", "rainbow")
        self.assertTrue(controls["a"][0].isHidden())
        self.assertTrue(controls["b"][0].isHidden())

    def test_keyboard_actions_share_queue(self):
        w = self.window
        w._paint()
        w._run_effect("keyboard", "breathing")
        w._paint()
        w._effect_off()
        w._all_keys_off()
        self.assertEqual({c.args[0] for c in w.hw.submit.call_args_list}, {"keyboard"})

    def test_zone_actions_share_queue(self):
        w = self.window
        w.part_nav_buttons["touchpad"].click()
        w._paint()
        w._run_effect("touchpad", "breathe")
        w._zone_static((0, 0, 0))
        self.assertEqual(len({c.args[0] for c in w.hw.submit.call_args_list}), 1)

    def test_switching_surface_restores_picker_without_writes(self):
        w = self.window
        w._set_colour(QColor("#ff0000"))
        w.part_nav_buttons["touchpad"].click()
        w._set_colour(QColor("#00ff00"))
        w.hw.submit.reset_mock()
        w.part_nav_buttons["keyboard"].click()
        self.assertEqual(w.hex.text(), "#ff0000")
        w.hw.submit.assert_not_called()

    def test_unedited_hex_does_not_apply_colour(self):
        w = self.window
        w.hex.editingFinished.emit()
        w.hw.submit.assert_not_called()

    def test_brightness_controls_stay_in_sync(self):
        w = self.window
        from PyQt6.QtWidgets import QSlider
        sliders = [w.effects_stack.widget(w.pages[p]).findChild(QSlider)
                   for p in ("touchpad", "logo")]
        sliders[0].setValue(80)
        self.assertEqual(sliders[1].value(), 80)
        w.hw.submit.assert_called_once()

    def test_ac_button_does_not_overwrite_battery(self):
        w = self.window
        w.part_nav_buttons["power"].click()
        w._set_colour(QColor("#ff0000"))
        w._set_power()
        self.assertIsNone(w.hw.submit.call_args.args[-1])

    def test_power_preset_uses_profiles(self):
        w = self.window
        w.part_nav_buttons["power"].click()
        w._set_power(both=True)
        w.preset_name.setText("Power")
        w._save_preset()
        w.hw.submit.reset_mock()
        w._load_preset("Power")
        calls = w.hw.submit.call_args_list
        self.assertTrue(any(c.args[1] == w.hw.set_power_profiles for c in calls))
        self.assertFalse(any(c.args[1] == w.hw.zone_effect and
                            c.args[2] == (parts.POWER.zone,) for c in calls))


if __name__ == "__main__":
    unittest.main()
