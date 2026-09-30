<p align="center">
  <img src="awcfree_lib/gui/assets/logo.png" alt="FreeAlien penguin-alien icon" width="144">
</p>

<h1 align="center">FreeAlien</h1>

<p align="center">
  <strong>Your Alienware. Your colours. Your Linux desktop.</strong><br>
  Lighting, cooling, keyboard sounds and games — in one desktop studio.
</p>

<p align="center">
  <a href="#get-started">Get started</a> ·
  <a href="#the-studio">Explore</a> ·
  <a href="docs/usage.md">User guide</a> ·
  <a href="#compatibility">Compatibility</a> ·
  <a href="#credits">Credits</a> ·
  <a href="LICENSE">MIT license</a>
</p>

<p align="center">
  <img src="docs/freealien-demo.gif" alt="FreeAlien controlling Alienware keyboard and touchpad lighting" width="640">
  <br><sub>You can actually play games on the keyboard itself!</sub>
</p>

## The studio

| Make it yours | What you can do |
| --- | --- |
| 🌈 **Lighting** | Colour individual keys, run hardware effects, and light the touchpad ring, lid emblem and power button. Save your favourite presets. |
| 🌡️ **Thermals** | Watch CPU/GPU temperatures and fan RPM, switch firmware profiles, and adjust fan boost in Custom mode. |
| 🔊 **Sounds** | Try Fart Lab, Gaming Keyboard or Freedom mode. Play inside FreeAlien or opt into background keyboard sounds. |
| 🎮 **Games** | Play Snake, Minesweeper, Zombie Defense and T-Rex with keyboard lighting. Snake also runs from the CLI. |
| 🛠️ **Automation** | Control lighting from the command line or build on the Python library. |

<p align="center">
  <img src="packaging/screenshot.png" alt="FreeAlien desktop lighting studio" width="900">
</p>

FreeAlien uses Linux **hidraw** for lighting, so the keyboard's HID driver stays
attached while you type. The desktop uses PyQt6; the lighting CLI and library use
Python's standard library.

## Get started

Clone the project and launch setup as your normal desktop user:

```bash
git clone https://github.com/JafarAkhondali/FreeAlien.git
cd FreeAlien
./install.sh
```

Have **Python 3.10+ with curses** and **PyQt6** installed first. Setup uses
`sudo` and `udevadm`; thermal controls also need systemd and a supported
`alienware-wmi` driver. Setup does not download dependencies.

- **Ready by default:** desktop GUI, application-menu shortcut and thermal service.
- **Automatic:** lighting udev rules are installed and reloaded; no permission checkbox.
- **Optional:** launch at login, background keyboard access and reduced motion.
- **One-time administrator setup:** everyday lighting and thermal mode changes run
  from your normal account without sudo or password prompts.

Use **↑/↓** to move, **Space** to toggle, **/** to search and **Enter** to review.
Nothing is installed until you confirm. Deselect the thermal service if your
machine does not expose the supported driver.

Open **FreeAlien** from your application menu, or run:

```bash
~/.local/bin/freealien gui
```

Add `~/.local/bin` to `PATH` to use `freealien` directly. From a checkout,
`./freealien gui` runs the app without copying it.

<details>
<summary><strong>Sound dependencies, updates and removal</strong></summary>

Keyboard sound playback uses `libpulse-simple` with PulseAudio or PipeWire's
PulseAudio support. Background input on X11 uses `xinput`; native keyboard-access
setup in the GUI uses polkit (`pkexec`). Game audio optionally uses `paplay`,
`pw-play` or `aplay`.

Rerun `./install.sh` from an updated checkout to update the installed copy.
Keep the thermal service selected to update its privileged helper too.

Close FreeAlien and run `./uninstall.sh` to remove it. Presets and system
permissions/services are retained unless you select their removal. Uninstalling
does not reset firmware lighting or cooling settings.

See the [installation guide](packaging/README.md) for paths, services,
permissions and recovery.

</details>

## Compatibility

Developed and tested on the **Alienware m16 R2**. Other models may work if they
share these controllers; matching the brand alone does not establish support.

| Hardware | Supported surface |
| --- | --- |
| Darfon `0d62:d2b1` | Per-key RGB and keyboard hardware effects |
| AW-ELC `187c:0551` | Touchpad ring, lid emblem and power-button lighting |
| Linux `alienware-wmi` | Firmware thermal profiles, temperatures, fan RPM and fan boost where exposed |

The keyboard protocol addresses 92 LEDs; **85 correspond to physical keys on the
measured ANSI keyboard**. Thermal availability depends on the model, firmware and
kernel driver.

G-Mode, automatic fan curves and CPU tuning are not implemented. Keyboard Pulse
and Laser effects are disabled because of unreliable behaviour. Some power-state
names and unobserved chassis zones remain unverified. See
[known gaps](docs/usage.md#known-gaps).

## A few commands

Run these from the checkout, or replace `./freealien` with your installed launcher:

```bash
./freealien status                     # check controller access
./freealien static purple              # colour the keyboard
./freealien key blue F1 F2 ESC          # colour selected keys
./freealien effect breathing purple    # hardware animation
./freealien touchpad green
./freealien logo white --persist       # retain the lid colour after reboot
./freealien power white purple         # AC / battery colours
./freealien snake
./freealien --dry-run static red       # inspect packets without sending them
```

The [user guide](docs/usage.md) covers effects, thermal controls, game shortcuts,
sounds, Python examples and the measured key layout. Use `./freealien --help`
for the full command list.

## Before using hardware controls

> **Independent project — not affiliated with Dell or Alienware.**
> Dell and Alienware were not involved in developing FreeAlien and have not
> endorsed, sponsored or approved it. Their names and trademarks belong to their
> respective owners and identify the hardware this project targets.
>
> **Use entirely at your own risk. You accept 100% responsibility and liability
> for damage caused by this software.** FreeAlien interacts directly with hardware,
> including lighting and cooling controls. Incorrect settings, defects or
> unsupported hardware can cause overheating, instability, data loss or permanent
> damage. The software is provided without warranty; the authors and contributors
> accept no liability to the extent permitted by applicable law.

Thermal settings remain active after closing the GUI. Choose **Balanced** to
return to that firmware profile. Fan boost is a raw **0–255** value, not an RPM or
percentage; zero removes added boost and does not stop the fan.

Sounds start **off** and **inside FreeAlien**. Everywhere mode also detects
password-field presses; it cannot identify sensitive fields. FreeAlien does not
save typed text or show pressed-key names. Native keyboard permissions persist
after muting or quitting and allow other applications in your session to access
those keyboards. See [keyboard sounds](docs/usage.md#keyboard-sounds) for removal.

## Support the project

If FreeAlien is useful to you, **consider giving the repository a ⭐**.

Worked on your laptop? [Open an issue](https://github.com/JafarAkhondali/FreeAlien/issues)
and tell us your **exact laptop model/version**, Linux distribution and kernel,
and which features worked. Reports from other machines help improve the
compatibility information.

## Credits

Thanks to the projects and creators who made this work easier:

- [T-Troll/alienfx-tools](https://github.com/T-Troll/alienfx-tools) — AlienFX protocol references.
- [cryptoconspiracy/alien-thunder](https://github.com/cryptoconspiracy/alien-thunder) — m16 R2 hidraw and LED-offset research.
- [tr1xem/AWCC](https://github.com/tr1xem/AWCC) — ACPI/WMI and lighting protocol references.
- Linux's `alienware-wmi` driver — the thermal interface used by FreeAlien.
- [bucklespring](https://github.com/zevv/bucklespring) and [daktilo](https://github.com/orhun/daktilo) — inspiration for keyboard sounds.
- **LFA**, **unicaegames**, and **Ben Jaszczak, Brian Nelson, Kevin Heras and Matthew Nanney**
  (submitted by **bart**) — the CC0 recordings behind the three sound packs.

See [CREDITS.md](CREDITS.md) for source links, asset licenses, retained notices
and the distinction between protocol references and bundled material.

## Development and license

```bash
python3 -m pytest
python3 dev/tools/verify_grid.py --numeric
```

Tests mock hardware and privileged setup; Qt runs offscreen. Thermal-service
tests use local sockets. Start with the [development guide](docs/development.md)
and [test guide](tests/README.md).

FreeAlien's original source code is licensed under the **[MIT License](LICENSE)**,
copyright © 2026 Jafar Akhondali. Bundled third-party recordings retain their
CC0 licenses and attribution. External projects and dependencies retain their
own licenses.
