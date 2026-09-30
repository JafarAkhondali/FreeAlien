"""Unsupported keyboard effects must not disturb the active hardware pattern."""
from unittest.mock import Mock

import pytest

from awcfree_lib.cli import build_parser
from awcfree_lib.devices.keyboard import Keyboard
from awcfree_lib.protocol import v5


@pytest.mark.parametrize('name', ['pulse', 'laser'])
def test_removed_effect_rejected_before_hardware_writes(name):
    keyboard = Keyboard('/dev/fake-keyboard')
    keyboard.dev = Mock()
    with pytest.raises(ValueError, match='unknown effect'):
        keyboard.effect(name)
    keyboard.dev.send_feature.assert_not_called()
    with pytest.raises(SystemExit):
        build_parser().parse_args(['effect', name])


def test_keyboard_effect_menu_matches_supported_protocol():
    from awcfree_lib.gui.parts import KEYBOARD
    assert set(KEYBOARD.effects) == set(v5.EFFECTS) == set(v5.EFFECT_COLOURS)
    assert not {'pulse', 'laser'} & set(KEYBOARD.effects)
