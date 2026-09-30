"""Thermals on a temporary sysfs tree. Never changes the host's cooling."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication
from awcfree_lib.thermals import ThermalBackend, ThermalError
from awcfree_lib.gui.thermals import ThermalsPage
from awcfree_lib.gui import theme


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profile = self.root / "class/platform-profile/platform-profile-9"
        self.hwmon = self.root / "class/hwmon/hwmon42"
        for directory, values in (
            (self.profile, {"name": "alienware-wmi", "choices": "quiet balanced performance custom",
                            "profile": "performance"}),
            (self.hwmon, {"name": "alienware_wmi", "fan1_label": "CPU Fan", "fan1_input": "3200",
                          "fan1_boost": "100", "fan2_label": "GPU Fan", "fan2_input": "3100",
                          "fan2_boost": "80", "temp1_label": "CPU", "temp1_input": "55500",
                          "temp2_label": "GPU", "temp2_input": "49000"}),
        ):
            directory.mkdir(parents=True)
            for name, value in values.items():
                (directory / name).write_text(value + "\n")
        self.backend = ThermalBackend(self.root)

    def test_discovers_by_driver_name_and_reads_units(self):
        data = self.backend.snapshot()
        self.assertEqual(data["profile"], "performance")
        self.assertEqual(data["temperatures"][0]["celsius"], 55.5)
        self.assertEqual(data["fans"][1]["rpm"], 3100)

    def test_profile_validation_and_readback(self):
        self.backend.set_profile("quiet")
        self.assertEqual(self.backend.snapshot()["profile"], "quiet")
        for value in ("cool", "../../etc/passwd", "quiet\nperformance"):
            with self.assertRaises(ThermalError):
                self.backend.set_profile(value)
        self.assertEqual(self.backend.snapshot()["profile"], "quiet")

    def test_boost_requires_custom_and_changes_only_requested_fan(self):
        with self.assertRaises(ThermalError):
            self.backend.set_boost(1, 200)
        self.backend.set_profile("custom")
        self.backend.set_boost(1, 200)
        self.assertEqual(self.backend.snapshot()["fans"][0]["boost"], 200)
        self.assertEqual(self.backend.snapshot()["fans"][1]["boost"], 80)

    def test_rejects_out_of_range_and_unavailable_fans(self):
        self.backend.set_profile("custom")
        for fan, value in ((0, 20), (5, 20), (1, -1), (1, 256), (3, 50)):
            with self.assertRaises(ThermalError):
                self.backend.set_boost(fan, value)

    def test_missing_sensor_does_not_become_zero(self):
        (self.hwmon / "temp1_input").write_text("bad value")
        self.assertIsNone(self.backend.snapshot()["temperatures"][0]["celsius"])

    def test_missing_driver_is_unavailable(self):
        self.assertFalse(ThermalBackend(self.root / "absent").snapshot()["available"])

    def test_disappeared_attribute_is_not_created(self):
        self.backend.set_profile("custom")
        target = self.hwmon / "fan1_boost"
        target.unlink()
        with self.assertRaises(ThermalError):
            self.backend.set_boost(1, 20)
        self.assertFalse(target.exists())

    def test_readback_mismatch_is_reported(self):
        with patch.object(self.backend, "_write"):
            with self.assertRaisesRegex(ThermalError, "did not retain"):
                self.backend.set_profile("balanced")

    def test_write_errors_are_reported(self):
        with patch("awcfree_lib.thermals.os.open", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaisesRegex(ThermalError, "Permission denied"):
                self.backend.set_profile("balanced")


class ThermalsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.STYLESHEET)

    def setUp(self):
        self.page = ThermalsPage()
        self.addCleanup(self.page.close)
        self.data = {"available": True, "service_ready": True, "profile": "performance",
                     "choices": ["balanced", "performance", "custom"],
                     "temperatures": [{"label": "CPU", "celsius": 50}, {"label": "GPU", "celsius": 45}],
                     "fans": [{"id": 1, "label": "CPU Fan", "rpm": 3000, "boost": 100, "controllable": True},
                              {"id": 2, "label": "GPU Fan", "rpm": 3100, "boost": 80, "controllable": True}]}
        self.page.writer = Mock()
        self.page._received(self.data)

    def test_reading_never_writes(self):
        self.page.writer.submit.assert_not_called()
        self.assertEqual(self.page.metrics["cpu_temp"].text(), "50")
        self.assertEqual(self.page.metrics["gpu_fan"].text(), "3,100")
        self.assertFalse(self.page.fan_controls[1]["apply"].isEnabled())

    def test_apply_profile_is_explicit_and_not_optimistic(self):
        self.page.profile_buttons["custom"].click()
        self.page.writer.submit.assert_called_once_with({"action": "profile", "name": "custom"})
        self.assertEqual(self.page.profile_status.text(), "Active: Performance")
        self.assertTrue(self.page.busy)
        self.assertFalse(self.page.profile_buttons["balanced"].isEnabled())

    def test_slider_edits_survive_poll_and_only_apply_on_click(self):
        self.data["profile"] = "custom"
        self.page._received(self.data)
        control = self.page.fan_controls[2]
        control["slider"].setValue(140)
        self.page._received(self.data)
        self.assertEqual(control["slider"].value(), 140)
        self.page.writer.submit.assert_not_called()
        control["apply"].click()
        self.page.writer.submit.assert_called_once_with({"action": "boost", "fan": 2, "value": 140})

    def test_service_failure_reports_error_and_refreshes_actual_state(self):
        self.page.busy = True
        self.page._finished(False, "Thermal service unavailable")
        self.assertFalse(self.page.busy)
        self.assertIn("unavailable", self.page.message.text())

    def test_missing_service_keeps_profiles_clickable_for_setup(self):
        self.data["service_ready"] = False
        self.page._received(self.data)
        self.assertTrue(self.page.profile_buttons["custom"].isEnabled())
        self.assertFalse(self.page.fan_controls[1]["apply"].isEnabled())
        self.assertIn("install-thermals.sh", self.page.setup.text())
        with patch.object(self.page, "_setup_service") as setup:
            self.page.profile_buttons["custom"].click()
            setup.assert_called_once_with("profile", ("custom",))
        self.page.writer.submit.assert_not_called()

    def test_profile_setup_success_applies_requested_profile(self):
        self.data["service_ready"] = False
        self.page._received(self.data)
        process = Mock()
        with patch("awcfree_lib.gui.thermals.shutil.which", return_value="/usr/bin/pkexec"), \
             patch("awcfree_lib.gui.thermals.QProcess", return_value=process):
            self.page.profile_buttons["custom"].click()
            self.assertTrue(self.page.busy)
            self.assertFalse(self.page.profile_buttons["custom"].isEnabled())
            self.assertEqual(process.start.call_args.args[0], "/usr/bin/pkexec")
            self.assertIn("--user", process.start.call_args.args[1])
            self.page._complete_setup(True, "")
        process.deleteLater.assert_called_once()
        self.page.writer.submit.assert_called_once_with({"action": "profile", "name": "custom"})

    def test_cancelled_setup_reenables_profiles_without_writing(self):
        self.data["service_ready"] = False
        self.page._received(self.data)
        process = Mock()
        with patch("awcfree_lib.gui.thermals.shutil.which", return_value="/usr/bin/pkexec"), \
             patch("awcfree_lib.gui.thermals.QProcess", return_value=process):
            self.page.profile_buttons["custom"].click()
            self.page._complete_setup(False, "Cancelled")
        self.assertFalse(self.page.busy)
        self.assertTrue(self.page.profile_buttons["custom"].isEnabled())
        self.assertFalse(self.page.data["service_ready"])
        self.assertEqual(self.page.message.text(), "Cancelled")
        self.page.writer.submit.assert_not_called()

    def test_missing_device_clears_stale_readings_and_controls(self):
        self.page._received({"available": False, "fans": [], "temperatures": [], "choices": []})
        self.assertEqual(self.page.metrics["cpu_temp"].text(), "—")
        self.assertEqual(self.page.fan_controls, {})
        self.assertEqual(self.page.profile_buttons, {})
        self.assertFalse(self.page.automatic.isEnabled())


if __name__ == "__main__":
    unittest.main()


def test_rotor_pauses_for_hidden_missing_stopped_and_reduced_motion():
    from awcfree_lib.gui.thermals import FanRotor
    from PyQt6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    rotor = FanRotor()
    rotor.set_rpm(3200)
    assert not rotor.timer.isActive()
    rotor.show()
    QTest.qWait(80)
    assert rotor.angle > 0 and rotor.timer.isActive()
    rotor.set_rpm(None)
    assert not rotor.timer.isActive()
    rotor.set_rpm(0)
    assert not rotor.timer.isActive()
    rotor.set_rpm(3200)
    rotor.motion = False
    rotor._sync()
    assert not rotor.timer.isActive()
    rotor.motion = True
    rotor._sync()
    assert rotor.timer.isActive()
    rotor.hide()
    assert not rotor.timer.isActive()
    rotor.close()
