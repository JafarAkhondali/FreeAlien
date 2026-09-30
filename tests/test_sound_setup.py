"""Scoped privileged setup validation, without changing system permissions."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

spec = importlib.util.spec_from_file_location("sound_setup", Path(__file__).resolve().parents[1] /
                                              "packaging/install_sound_input.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def keyboard(tmp_path, name="AT Translated Set 2 keyboard", typing=True):
    device = tmp_path / "event3/device"
    (device / "capabilities").mkdir(parents=True)
    bits = (1 << 30) | (1 << 28) | (1 << 57) if typing else 1
    (device / "capabilities/key").write_text(f"{bits:x}")
    (device / "name").write_text(name)
    return setup.keyboard_rule("event3", tmp_path)


def test_rule_scopes_access_to_keyboard_and_rejects_untrusted_matches(tmp_path):
    rule = keyboard(tmp_path)
    assert 'ATTRS{name}=="AT Translated Set 2 keyboard"' in rule
    assert 'TAG+="uaccess"' in rule and "MODE=" not in rule and "GROUP=" not in rule
    for value in ("../../etc/passwd", "event3;id", "event*", "/dev/input/event3"):
        with pytest.raises(ValueError): setup.keyboard_rule(value, tmp_path)
    (tmp_path / "event3/device/name").write_text('keyboard"*')
    with pytest.raises(ValueError): setup.keyboard_rule("event3", tmp_path)
    (tmp_path / "event3/device/capabilities/key").write_text("1")
    with pytest.raises(ValueError): setup.keyboard_rule("event3", tmp_path)


def test_install_requires_admin_before_reading_or_writing():
    with patch.object(setup.os, "geteuid", return_value=1000), patch.object(setup, "keyboard_rule") as rule:
        with pytest.raises(PermissionError): setup.install("event3")
        rule.assert_not_called()


def test_install_uses_selected_event_and_atomic_root_owned_rule(tmp_path):
    rule = keyboard(tmp_path / "sys")
    destination = tmp_path / "rules/70-awcfree-keyboard-sounds.rules"
    with patch.object(setup.os, "geteuid", return_value=0), \
         patch.object(setup, "keyboard_rule", return_value=rule), \
         patch.object(setup, "RULE_PATH", destination), \
         patch.object(setup.os, "fchown") as owner, \
         patch.object(setup.subprocess, "run", return_value=Mock(stdout="ID_INPUT_KEYBOARD=1\n")) as run:
        setup.install("event3")
        owner.assert_called_once()
        assert owner.call_args.args[1:] == (0, 0)
        assert destination.read_text() == rule
        assert destination.stat().st_mode & 0o777 == 0o644
        assert run.call_args_list[2].args[0] == ["/usr/bin/udevadm", "trigger", "--action=change",
                                               "--subsystem-match=input", "--sysname-match=event3"]
        assert not list(destination.parent.glob(".awcfree-*"))


def test_udev_validation_failure_never_installs_rule(tmp_path):
    destination = tmp_path / "rules/file"
    with patch.object(setup.os, "geteuid", return_value=0), \
         patch.object(setup, "keyboard_rule", return_value="unused"), \
         patch.object(setup, "RULE_PATH", destination), \
         patch.object(setup.subprocess, "run", return_value=Mock(stdout="ID_INPUT_MOUSE=1\n")):
        with pytest.raises(ValueError): setup.install("event3")
        assert not destination.exists()


def test_multi_keyboard_setup_validates_every_device_before_installing(tmp_path):
    destination = tmp_path / "rules/file"
    with patch.object(setup.os, "geteuid", return_value=0), \
         patch.object(setup, "keyboard_rule", side_effect=["first\n", "second\n"]), \
         patch.object(setup, "RULE_PATH", destination), \
         patch.object(setup.subprocess, "run", side_effect=[Mock(stdout="ID_INPUT_KEYBOARD=1\n"),
                                                          Mock(stdout="ID_INPUT_MOUSE=1\n")]):
        with pytest.raises(ValueError): setup.install(["event3", "event7"])
        assert not destination.exists()
