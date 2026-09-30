"""Installer lifecycle in a temporary home; system commands are intercepted."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest

spec = importlib.util.spec_from_file_location('awcfree_setup', Path(__file__).resolve().parents[1] / 'packaging/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / '.config'))
    with patch.object(setup, 'run') as run:
        yield setup.paths(), run


def test_install_upgrade_remove_preserves_presets(isolated):
    paths, run = isolated
    setup.install({0, 1, 2, 5})
    assert (paths['app'] / 'awcfree_lib/sounds/assets/manifest.json').is_file()
    assert (paths['app'] / 'LICENSE').read_bytes() == (setup.SOURCE / 'LICENSE').read_bytes()
    assert (paths['app'] / 'awcfree_lib/gui/assets/logo.png').read_bytes() == (setup.SOURCE / 'awcfree_lib/gui/assets/logo.png').read_bytes()
    assert paths['launcher'].stat().st_mode & 0o111
    assert 'Exec=' in paths['desktop'].read_text()
    assert '"reduced_motion": true' in (paths['config'] / 'preferences.json').read_text()
    preset = paths['config'] / 'presets.json'
    preset.write_text('{"keep": true}')
    setup.install({0})
    assert not paths['service'].exists()
    assert not paths['desktop'].exists()
    setup.uninstall(set())
    assert not paths['app'].exists()
    assert not paths['launcher'].exists()
    assert preset.exists()
    privileged = [call.args for call in run.call_args_list if call.args[0] == 'sudo']
    assert len(privileged) == 2
    assert all(args[-1] == 'lighting' for args in privileged)


def test_unmanaged_files_are_never_removed_or_replaced(isolated):
    paths, run = isolated
    paths['launcher'].parent.mkdir(parents=True)
    paths['launcher'].write_text('my old awcfree launcher')
    with pytest.raises(RuntimeError, match='unmanaged'):
        setup.install(set())
    setup.uninstall(set())
    assert paths['launcher'].read_text() == 'my old awcfree launcher'


def test_lighting_setup_is_automatic_without_sound_input_setup(isolated):
    paths, run = isolated
    setup.install({0, 1})
    privileged = [call.args for call in run.call_args_list if call.args[0] == 'sudo']
    assert privileged == [('sudo', '/usr/bin/python3', '-I', paths['app'] / 'packaging/system_setup.py', 'lighting')]


def test_cli_only_install_also_installs_lighting_rules(isolated):
    paths, run = isolated
    setup.install(set())
    run.assert_any_call('sudo', '/usr/bin/python3', '-I', paths['app'] / 'packaging/system_setup.py', 'lighting')


def test_thermal_option_uses_new_index(isolated):
    paths, run = isolated
    setup.install({3})
    assert any(call.args[0] == 'sudo' and call.args[3] == paths['app'] / 'packaging/install_thermals.py'
               for call in run.call_args_list)


def test_removal_stops_service_before_deleting_files(isolated):
    paths, run = isolated
    setup.install({0, 2})
    run.reset_mock()
    setup.uninstall({0, 1})
    assert run.call_args_list[0].args[-1] == 'remove'
    assert run.call_args_list[1].args == ('systemctl', '--user', 'disable', '--now', 'freealien.service')
    assert not paths['service'].exists()
    assert not paths['config'].exists()


def test_failed_system_cleanup_retains_user_uninstaller(isolated):
    paths, run = isolated
    setup.install(set())
    run.side_effect = OSError('sudo unavailable')
    with pytest.raises(OSError): setup.uninstall({0})
    assert (paths['app'] / 'packaging/setup.py').exists()


def test_dependency_failure_does_not_create_installation(isolated):
    paths, run = isolated
    run.side_effect = OSError('Python dependency missing')
    with pytest.raises(OSError): setup.install({0, 1})
    assert not paths['app'].exists()
    assert not paths['launcher'].exists()


def test_system_removal_is_scoped_and_stops_before_unlink(tmp_path):
    spec = importlib.util.spec_from_file_location('awcfree_system_setup', setup.SOURCE / 'packaging/system_setup.py')
    system = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(system)
    units = tmp_path / 'units'
    rules = tmp_path / 'rules'
    units.mkdir(); rules.mkdir()
    for name in ('awcfree-thermals.socket', 'awcfree-thermals.service', 'other.service'):
        (units / name).write_text('test')
    for name in ('70-awcfree.rules', '70-awcfree-keyboard-sounds.rules', 'other.rules'):
        (rules / name).write_text('test')
    helper = tmp_path / 'helper'
    helper.write_text('test')
    calls = []
    def command(*args):
        if args[1] in ('disable', 'stop'):
            assert (units / 'awcfree-thermals.service').exists()
        calls.append(args)
    with patch.object(system, 'UNIT_DIR', units), patch.object(system, 'RULE_DIR', rules), \
         patch.object(system, 'THERMAL_HELPER', helper), patch.object(system.os, 'geteuid', return_value=0), \
         patch.object(system, 'run', side_effect=command), patch('sys.argv', ['setup', 'remove']):
        system.main()
    assert calls[0][1:] == ('disable', '--now', 'awcfree-thermals.socket')
    assert calls[1][1:] == ('stop', 'awcfree-thermals.service')
    assert [p.name for p in units.iterdir()] == ['other.service']
    assert [p.name for p in rules.iterdir()] == ['other.rules']
    assert not helper.exists()


def test_rebrand_removes_managed_legacy_entry_points_keeps_presets(isolated):
    paths, run = isolated
    legacy = setup.paths('awcfree')
    legacy['app'].mkdir(parents=True)
    (legacy['app'] / '.awcfree-install').write_text('1\n')
    for key in ('launcher', 'desktop', 'icon', 'service'):
        setup.write(legacy[key], 'old installer-owned file')
    setup.write(paths['config'] / 'presets.json', '{"kept": true}')
    setup.install({0, 1})
    assert paths['launcher'].name == 'freealien'
    assert 'Name=FreeAlien' in paths['desktop'].read_text()
    assert 'Icon=freealien' in paths['desktop'].read_text()
    assert (paths['config'] / 'presets.json').read_text() == '{"kept": true}'
    assert not legacy['app'].exists()
    assert all(not legacy[key].exists() for key in ('launcher', 'desktop', 'icon', 'service'))
    assert any(call.args == ('systemctl', '--user', 'disable', '--now', 'awcfree.service')
               for call in run.call_args_list)


def test_search_preserves_hidden_selections_and_handles_no_matches():
    class Screen:
        def __init__(self):
            self.keys = iter(['/', *'thermal', '\n', ' ', '/', *'missing', '\n',
                              ' ', '\x1b', '\n'])
        def getmaxyx(self): return (24, 100)
        def get_wch(self): return next(self.keys)
        def erase(self): pass
        def keypad(self, value): pass
        def addnstr(self, *args): pass
        def refresh(self): pass
    with patch.object(setup.curses, 'curs_set'):
        chosen = setup.menu(Screen(), 'INSTALL', ['Desktop', 'Thermal service', 'Sounds'], {0})
    assert chosen == {0, 1}
    assert setup.matching_options(['Thermal SERVICE', 'Sound service'], 'SERVICE thermal') == [0]
