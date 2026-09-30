#!/usr/bin/python3 -I
"""Fixed system operations used by the interactive installer/uninstaller."""
import argparse
import os
from pathlib import Path
import subprocess
import importlib.util
_spec = importlib.util.spec_from_file_location('thermal_installer', Path(__file__).with_name('install_thermals.py'))
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
atomic_install = _module.atomic_install


RULE_DIR = Path('/etc/udev/rules.d')
UNIT_DIR = Path('/etc/systemd/system')
THERMAL_HELPER = Path('/usr/local/libexec/awcfree-thermals')


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['lighting', 'remove'])
    args = parser.parse_args()
    if os.geteuid() != 0: parser.error('Administrator authentication required')
    rules = RULE_DIR
    if args.action == 'lighting':
        atomic_install(rules / '70-awcfree.rules',
                       (Path(__file__).resolve().parent.parent / 'awcfree_lib/data/70-awcfree.rules').read_bytes(), 0o644)
    else:
        units = UNIT_DIR
        if (units / 'awcfree-thermals.socket').exists():
            run('/usr/bin/systemctl', 'disable', '--now', 'awcfree-thermals.socket')
        if (units / 'awcfree-thermals.service').exists():
            run('/usr/bin/systemctl', 'stop', 'awcfree-thermals.service')
        for name in ('awcfree-thermals.service', 'awcfree-thermals.socket'):
            (units / name).unlink(missing_ok=True)
        THERMAL_HELPER.unlink(missing_ok=True)
        for name in ('70-awcfree.rules', '70-awcfree-keyboard-sounds.rules'):
            (rules / name).unlink(missing_ok=True)
        run('/usr/bin/systemctl', 'daemon-reload')
    run('/usr/bin/udevadm', 'control', '--reload-rules')
    run('/usr/bin/udevadm', 'trigger', '--action=change', '--subsystem-match=hidraw')
    if args.action == 'remove':
        run('/usr/bin/udevadm', 'trigger', '--action=change', '--subsystem-match=input')
        print('Close FreeAlien. Log out or reboot to clear existing keyboard ACLs and open input handles.')
    run('/usr/bin/udevadm', 'settle', '--timeout=10')


if __name__ == '__main__':
    main()
