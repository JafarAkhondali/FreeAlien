# Installation and lifecycle

From the repository root, run `./install.sh` as your desktop user. The standard
library curses UI offers a review before changes, and defaults to GUI + desktop
shortcut + thermal control service. Thermal setup requires administrator
authentication once; later mode changes need no sudo or password prompts.
You can deselect the service. Press `/` to search, Enter to finish editing the filter, Space to
toggle a result, then Enter to review all selections. Esc clears the filter before
cancelling. `./uninstall.sh` opens the removal UI. Neither command starts
background listening. Background key sounds are unchecked by default; selecting the option lets you
choose keyboards, or you can enable it later in the GUI. Recommended options are
marked in the menu. Lighting-device udev rules are installed and reloaded
automatically on every install or update, with administrator authentication;
there is no separate lighting-permission option.

The installer uses its invoking Python for the installed launcher. Use an
interpreter with PyQt6 for GUI installation; keep that interpreter available.
CLI-only installation needs no third-party Python packages. Sound input setup
also requires PyQt6. System helpers explicitly use `/usr/bin/python3`.
The installed copy includes the MIT license, credits and bundled asset notices.

## Installed files

| Path | Owner / purpose |
| --- | --- |
| `~/.local/share/freealien/` | User application copy, bundled audio and packaging tools |
| `~/.local/bin/freealien` | User launcher |
| `~/.local/share/applications/freealien.desktop` | Optional application-menu entry |
| `~/.local/share/icons/hicolor/scalable/apps/freealien.svg` | Application icon |
| `~/.config/systemd/user/freealien.service` | Optional graphical-session startup |
| `$XDG_CONFIG_HOME/awcfree/preferences.json` | Motion preference; defaults to `~/.config` |
| `/etc/udev/rules.d/70-awcfree.rules` | Automatically installed lighting-controller access |
| `/etc/udev/rules.d/70-awcfree-keyboard-sounds.rules` | Optional selected-keyboard access |
| `/usr/local/libexec/awcfree-thermals` | Root-owned thermal writer |
| `/etc/systemd/system/awcfree-thermals.service` | Sandboxed thermal service |
| `/etc/systemd/system/awcfree-thermals.socket` | User-restricted activation socket |

The runtime socket is `/run/awcfree-thermals.sock`, mode 0600, owned by the
configured user. Only one user is configured at a time. Reinstalling the thermal
service for another user replaces that authorization.

## Manual thermal setup

```bash
sudo sh packaging/install-thermals.sh --user "$USER"
systemctl status awcfree-thermals.socket
journalctl -u awcfree-thermals.service -b
```

Load the supported Alienware WMI driver first. Monitoring requires no service.
Installation discovers device paths, validates generated systemd units, installs
root-owned files, and enables the socket. Runtime changes use the socket without
sudo or pkexec. Closing the GUI or stopping the service does not reset firmware
settings. Reinstall after source updates or changes to discovered device paths.

## Sound input

Sounds start muted and scoped to the app. Choose Everywhere and click
**Enable key sounds** to start background playback. That same button requests
one-time administrator setup if needed, then starts the listener automatically.
Cancelling or failing setup leaves sounds off. GUI setup uses `pkexec`; the TUI
uses `sudo`. X11 uses `xinput`; native input uses read-only evdev. No separate
sound daemon is installed. Only sound categories reach background playback;
letter names are neither displayed nor passed to audio.
Rules match selected typing keyboards by name and grant active-session `uaccess`;
other processes in the session can also read those devices. Typed text is not
stored. Closing FreeAlien stops playback and listening; minimizing preserves an
explicitly enabled background session.

Ship all of `awcfree_lib/sounds/assets/`, including manifest, licenses and
attribution. Playback uses `libpulse-simple`; ffmpeg is only for the offline
importer. See [CREDITS.md](../CREDITS.md).

## Removal and recovery

Close the GUI, then run `./uninstall.sh` or
`python3 ~/.local/share/freealien/packaging/setup.py --uninstall`. Presets and system
components are retained unless selected for removal. System removal disables and
stops the thermal units, removes the helper and both FreeAlien rules, reloads
systemd/udev, and triggers devices. Log out or reboot to clear keyboard ACLs and
open handles. System removal is machine-wide.

If the user copy has already been removed, the system-only cleanup is:

```bash
sudo /usr/bin/python3 -I packaging/system_setup.py remove
```

An interrupted install can be rerun. Completed optional steps remain in place if
a later step fails; setup prints the failure rather than claiming full success.
No installer command changes thermal profiles or writes lighting settings.

FreeAlien retains `awcfree_lib`, the awcfree configuration directory, and system
thermal/udev identifiers for compatibility. The installer removes managed legacy
awcfree user launchers/services after a successful upgrade; presets are retained.
