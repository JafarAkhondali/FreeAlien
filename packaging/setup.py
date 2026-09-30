#!/usr/bin/env python3
"""Interactive, per-user installation. System device setup uses sudo."""
import argparse
import curses
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import pwd
import tempfile

SOURCE = Path(__file__).resolve().parent.parent


def matching_options(options, query):
    """Keep original indices so filtered selections remain stable."""
    words = query.casefold().split()
    return [i for i, label in enumerate(options)
            if all(word in label.casefold() for word in words)]


def menu(screen, title, options, selected=None):
    selected = set(selected or ())
    cursor = 0
    query = ""
    searching = False
    curses.curs_set(0)
    screen.keypad(True)
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        def line(y, text, style=0):
            if y < height-1 and width > 4:
                screen.addnstr(y, 2, text, width-4, style)
        matches = matching_options(options, query)
        cursor = min(cursor, max(0, len(matches)-1))
        line(1, 'FreeAlien / ' + title, curses.A_BOLD)
        line(3, '/ Search  Arrows: move  Space: toggle  Enter: review  Esc: back')
        line(4, ('Search > ' if searching else 'Filter: ') + (query or 'all options'))
        line(5, f'{len(matches)} matching / {len(options)} total · {len(selected)} selected')
        if height < 12 or width < 64:
            line(7, 'Enlarge terminal to at least 64 columns and 12 rows.')
        else:
            rows = height-10
            start = max(0, cursor-rows+1)
            if not matches: line(7, 'No matches. Press / to edit or Esc to clear.')
            for row, index in enumerate(matches[start:start+rows]):
                line(7+row, ('[x] ' if index in selected else '[ ] ') + options[index],
                     curses.A_REVERSE if start+row == cursor else 0)
            line(height-2, 'Enter: finish search · Esc: clear search' if searching else
                 'Selections outside this filter are kept and shown at review.')
        screen.refresh()
        key = screen.get_wch()
        if key == curses.KEY_RESIZE: continue
        if searching:
            if key in ('\n', '\r'): searching = False
            elif key == '\x1b': query = ''; searching = False; cursor = 0
            elif key in (curses.KEY_BACKSPACE, '\x7f', '\b'): query = query[:-1]; cursor = 0
            elif isinstance(key, str) and key.isprintable(): query += key; cursor = 0
            continue
        if key == '/': searching = True; continue
        if key == '\x1b':
            if query: query = ''; cursor = 0; continue
            raise KeyboardInterrupt
        if key == curses.KEY_UP and matches: cursor = (cursor-1) % len(matches)
        if key == curses.KEY_DOWN and matches: cursor = (cursor+1) % len(matches)
        if key == ' ' and matches:
            index = matches[cursor]
            if index in selected: selected.remove(index)
            else: selected.add(index)
        if key in ('\n', '\r') and height >= 12 and width >= 64: return selected


def confirm(message):
    return input(message + ' [y/N] ').strip().lower() in ('y', 'yes')


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def paths(name="freealien"):
    home = Path.home()
    return {
        'app': home / f'.local/share/{name}',
        'launcher': home / f'.local/bin/{name}',
        'desktop': home / f'.local/share/applications/{name}.desktop',
        'icon': home / f'.local/share/icons/hicolor/scalable/apps/{name}.svg',
        'service': home / f'.config/systemd/user/{name}.service',
        'config': Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'awcfree',
    }


def write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def remove_legacy_user_install():
    legacy = paths("awcfree")
    if legacy['app'].is_symlink() or not (legacy['app'] / '.awcfree-install').is_file():
        return
    if legacy['service'].exists():
        run('systemctl', '--user', 'disable', '--now', 'awcfree.service')
        legacy['service'].unlink()
        run('systemctl', '--user', 'daemon-reload')
    for key in ('launcher', 'desktop', 'icon'):
        legacy[key].unlink(missing_ok=True)
    shutil.rmtree(legacy['app'])


def install(chosen):
    dest = paths()
    # Check dependencies before making changes. No pip/network execution is hidden here.
    if 0 in chosen or 4 in chosen:
        run(sys.executable, '-c', 'import PyQt6.QtWidgets')
    marker = dest['app'] / '.freealien-install'
    if dest['app'].is_symlink() or (dest['app'].exists() and not marker.is_file()):
        raise RuntimeError(f"Refusing to replace unrecognised directory: {dest['app']}")
    for key in ('launcher', 'desktop', 'service', 'icon'):
        path = dest[key]
        if (path.exists() or path.is_symlink()) and not marker.is_file():
            raise RuntimeError(f'Refusing to replace an unmanaged file: {path}')
        if path.is_symlink():
            raise RuntimeError(f'Refusing to replace a symlink: {path}')
    if 2 in chosen:
        run('systemctl', '--user', 'show-environment')
    dest['app'].parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.freealien-stage-', dir=dest['app'].parent) as tmp:
        stage = Path(tmp) / 'app'
        stage.mkdir()
        for name in ('awcfree_lib', 'packaging'):
            shutil.copytree(SOURCE / name, stage / name,
                            ignore=shutil.ignore_patterns('__pycache__', *(['screenshot*.png'] if name == 'packaging' else [])))
        for name in ('freealien', 'awcfree', 'README.md', 'CREDITS.md', 'LICENSE'):
            shutil.copy2(SOURCE / name, stage / name)
        (stage / '.freealien-install').write_text('1\n')
        backup = Path(tmp) / 'previous'
        if dest['app'].exists(): dest['app'].rename(backup)
        try:
            stage.rename(dest['app'])
        except OSError:
            if backup.exists(): backup.rename(dest['app'])
            raise
    write(dest['launcher'], '#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' +
          shlex.quote(str(dest['app'] / 'freealien')) + ' "$@"\n', 0o755)
    if 1 in chosen:
        # Desktop Exec uses double-quoted arguments, not shell quoting.
        executable = str(dest['launcher']).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
        write(dest['desktop'], '[Desktop Entry]\nType=Application\nName=FreeAlien\n'
              'Comment=Alienware lighting, cooling and keyboard sounds\n'
              f'Exec="{executable}" gui\nIcon=freealien\nTerminal=false\nCategories=Settings;HardwareSettings;\n')
        dest['icon'].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / 'packaging/freealien.svg', dest['icon'])
    else:
        dest['desktop'].unlink(missing_ok=True)
        dest['icon'].unlink(missing_ok=True)
    if 2 in chosen:
        write(dest['service'], (SOURCE / 'packaging/freealien.service').read_text())
        run('systemctl', '--user', 'daemon-reload')
        run('systemctl', '--user', 'enable', 'freealien.service')
    elif dest['service'].exists():
        run('systemctl', '--user', 'disable', '--now', 'freealien.service')
        dest['service'].unlink()
        run('systemctl', '--user', 'daemon-reload')
    write(dest['config'] / 'preferences.json', json.dumps({'reduced_motion': 5 in chosen}, indent=2)+'\n')
    helper = dest['app'] / 'packaging/system_setup.py'
    run('sudo', '/usr/bin/python3', '-I', helper, 'lighting')
    if 3 in chosen:
        run('sudo', '/usr/bin/python3', '-I', dest['app'] / 'packaging/install_thermals.py', '--user', pwd.getpwuid(os.getuid()).pw_name)
    if 4 in chosen:
        print('\nBackground sounds react to key presses across apps. No typed text is saved.\n'
              'Keyboard access applies to your desktop session. You can also set this up later in Sounds.')
        sys.path.insert(0, str(SOURCE))
        from awcfree_lib.sounds.input import keyboard_devices
        devices = keyboard_devices()
        if not devices: print('No typing keyboards found. Configure access later in Sounds.')
        else:
            for i, device in enumerate(devices, 1): print(f'{i}. {device.name} ({device.path})')
            answer = input('Keyboard numbers separated by spaces (blank cancels): ').split()
            numbers = sorted(set(int(n) for n in answer))
            if any(n < 1 or n > len(devices) for n in numbers): raise ValueError('Invalid keyboard selection')
            if numbers:
                args = [item for n in numbers for item in ('--device', Path(devices[n-1].path).name)]
                run('sudo', '/usr/bin/python3', '-I', dest['app'] / 'packaging/install_sound_input.py', *args)
    remove_legacy_user_install()
    print(f"\nInstalled: {dest['launcher']}\nRun ~/.local/bin/freealien gui (or add ~/.local/bin to PATH).")
    print('Optional components not selected are not installed; existing system permissions/services remain until removed with the uninstaller.')


def uninstall(chosen):
    dest = paths()
    marker = dest['app'] / '.freealien-install'
    managed = marker.is_file() and not dest['app'].is_symlink()
    if dest['app'].exists() and not managed:
        raise RuntimeError('Unrecognised installation; refusing to remove its files')
    if 0 in chosen:
        run('sudo', '/usr/bin/python3', '-I', SOURCE / 'packaging/system_setup.py', 'remove')
    if managed:
        if dest['service'].exists():
            run('systemctl', '--user', 'disable', '--now', 'freealien.service')
            dest['service'].unlink()
            run('systemctl', '--user', 'daemon-reload')
        for key in ('launcher', 'desktop', 'icon'): dest[key].unlink(missing_ok=True)
        shutil.rmtree(dest['app'])
    remove_legacy_user_install()
    if 1 in chosen and dest['config'].exists(): shutil.rmtree(dest['config'])
    print('Removed the user installation. Presets retained unless explicitly selected for removal.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0: parser.error('Run as your normal desktop user, without sudo.')
    if not sys.stdin.isatty() or not sys.stdout.isatty(): parser.error('Open a terminal to use the TUI installer.')
    options = (['Remove system thermal service and FreeAlien access rules (sudo)', 'Delete presets and preferences']
               if args.uninstall else [
                   'Desktop GUI [Recommended]', 'Application menu shortcut [Recommended]',
                   'Launch GUI at graphical login (sounds always start OFF)',
                   'Thermal control service [Recommended; one-time sudo setup]',
                   'Background key sounds [Optional; also available in GUI]', 'Reduced motion'])
    try:
        chosen = curses.wrapper(menu, 'UNINSTALL' if args.uninstall else 'INSTALL', options,
                                set() if args.uninstall else {0, 1, 3})
        if not args.uninstall and (1 in chosen or 2 in chosen): chosen.add(0)
        print('\n' + ('Remove user installation' if args.uninstall else 'Install/update user application'))
        if not args.uninstall:
            print('  • Lighting device permissions (automatic; administrator authentication required)')
        for i in sorted(chosen): print('  • ' + options[i])
        if confirm('Apply these choices?'):
            (uninstall if args.uninstall else install)(chosen)
    except (KeyboardInterrupt, EOFError): print('\nCancelled.')
    except (OSError, ValueError, RuntimeError, ImportError, curses.error, subprocess.CalledProcessError) as exc:
        print(f'\nSetup stopped: {exc}\nCompleted steps remain installed; rerun setup or use --uninstall.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
