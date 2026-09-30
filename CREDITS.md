# Credits

This file distinguishes protocol references from source code and assets. The
packet encoders, measured key layout, and UI artwork in `FreeAlien` are implemented
here; the projects below were consulted for published protocol details or
independent corroboration. AWCC is cited as an upstream technical reference and
is not included in this repository.

## Direct protocol sources

### [T-Troll/alienfx-tools](https://github.com/T-Troll/alienfx-tools) — MIT
Windows. Its `AlienFX-SDK/AlienFX_SDK/alienfx-controls.h` is a protocol reference
for command names, field layouts, and effect numbers used by these generations:

- **v4** (chassis, AW-ELC): the `0x20` request / `0x21` animation / `0x23` zone
  select / `0x24` add action / `0x26` dim structure.
- **v5** (per-key keyboard): `COMMV5_reset` `0x94`, `COMMV5_status` `0x93`,
  `COMMV5_colorSet` `0x8c 0x02`, `COMMV5_loop` `0x8c 0x13`, `COMMV5_update`
  `0x8b 0x01 0xff`, `COMMV5_turnOnSet` `0x83 0x38 0x9c`, and the
  `COMMV5_setEffect` `0x80 0x02 0x07` byte layout with its effect-type numbering.

The Python encoders here are independent implementations; no alienfx-tools source
files are included. If source is copied into a future release, retain its MIT
copyright and license notice.

It also documents v6 (monitors) and v7 (mice), which this laptop has no use for;
`protocol/` is laid out so they could be added as sibling modules.

### [cryptoconspiracy/alien-thunder](https://github.com/cryptoconspiracy/alien-thunder)
Linux, Python, KDE. Its work on the same m16 R2 independently confirmed the
user-space hidraw approach and the colour-record LED offset. It informed these
implementation choices:

- **The hidraw transport.** Its `hw.py` proves the controllers can be driven from
  user space with no root and no kernel-driver detach: `HIDIOCSFEATURE` for the
  keyboard's `0xcc` reports, a plain write for the chassis controller's report-0
  output reports. Driving these over libusb instead means claiming the interface
  and detaching the HID driver, which stops typing for as long as the lighting is
  held. Our `transport/hidraw.py` follows the same approach, including the
  `\x85\xcc` report-descriptor probe used to pick the right interface. The local
  udev rule grants access to these two device IDs only.
- **The `led + 1` offset** in its colour records. Arrived at independently here
  from decoding the enable mask, and agreeing with it is what confirmed the
  controller's internal ids are 0-based. See below.

### [tr1xem/AWCC](https://github.com/tr1xem/AWCC) — GPL-3.0
C++, Linux. Its `Hacking.md` and implementation were read as references for the
ACPI/WMI controls. This project uses the Linux `alienware-wmi` driver for thermal
profiles, fan readings, and fan boost; it does not copy AWCC's ACPI-call backend.
Its `include/LightFX.h` independently corroborates the v4 command set, and
`EffectController.cpp` was consulted for animation id `0x0061` and the spectrum
palette. AWCC is a separate project under GPL-3.0; its source and assets are not
included here. This project references its protocol documentation and captures,
not its implementation.

The thermal backend uses the Linux kernel's
[alienware-wmi driver interface](https://docs.kernel.org/6.16/wmi/devices/alienware-wmi.html).

## Keyboard sounds

[zevv/bucklespring](https://github.com/zevv/bucklespring) and
[orhun/daktilo](https://github.com/orhun/daktilo) inspired keyboard-triggered sound
packs, key-specific accents, and variation. Their source code and recordings are
not included. The bundled sound packs use these existing libraries:

- **Fart Lab:** [Gastric Distress](https://opengameart.org/content/gastric-distress),
  by **LFA**, **CC0 1.0**. Recorded mouth/hand fart foley; 13 clips trimmed from the
  original performance recording.
- **Gaming Keyboard:** [Keyboard Soundpack #1](https://opengameart.org/content/keyboard-soundpack-1-typing-and-single-keystrokes),
  by **unicaegames**, **CC0 1.0**. 32 recorded Cherry KC 1000 key strikes. The
  author's readme is retained; the archive's generated typing loops are not used.
- **Freedom mode:** [The Free Firearm Sound Library](https://opengameart.org/node/21826),
  by **Ben Jaszczak, Brian Nelson, Kevin Heras, and Matthew Nanney**, submitted by
  **bart**, **CC0 1.0**. 17 clips selected from the prepared near-distance 1911,
  AR-15, AK-47, Mossberg, and Walther PPQ recordings, including real short/long
  automatic bursts. The original master sheet describing the recordings is
  retained as `guns/upstream-master-sheet.csv`.

Import processing: silence trimming, conversion to mono 24 kHz PCM, volume
normalization, and short fades at trim boundaries. The firearm recordings also
use a 65 Hz high-pass filter to reduce low rumble and retain short natural tails.
Enter in the keyboard pack
combines two recorded strikes. Original asset names, trim positions, source URLs,
download hashes, license texts, and upstream notices are retained in
`awcfree_lib/sounds/assets/`. The reproducible offline importer is
`dev/tools/import_sound_packs.py`; it uses the system's ffmpeg and 7z, which are not bundled
or required for playback. Recordings retain their own licenses independently of
the application's MIT source-code license.

Playback uses the system's PulseAudio `libpulse-simple` client API through
Python's `ctypes`; global input uses the system's `xinput` command on X11 or the
Linux input event interface. These runtime components are not vendored here.

## Release licensing

FreeAlien's original source code is licensed under the [MIT License](LICENSE),
copyright (c) 2026 Jafar Akhondali. Bundled recordings retain their CC0 licenses
and notices. Referenced projects and external dependencies retain their own
licenses; FreeAlien's MIT license does not relicense third-party material.

## Findings from this repository's own captures

The captures under `tests/fixtures/v3/` are traffic from the stock Alienware Command Center on
Windows, recorded on this machine. Five findings in this library come from them
rather than from any project above, and each is pinned by a test in
`tests/test_against_captures.py` that replays the capture byte for byte.

1. **The `0x22` power-button surface.** Six standing profiles, ids `0x5b`–`0x60`,
   on zone `0x04`, driven with the same `01`/`02`/`04` verbs as `0x21` animations.
   `statusled/full-flow-*` shows AWCC writing all six in one pass. alienfx-tools
   does not name this command; alien-thunder sends a single hardcoded packet for it
   and notes the control number without decoding the set. The split into an AC trio
   and a battery trio is confirmed by the capture; the state names *within* each
   trio are inferred from the action kind AWCC pairs with each id and are flagged as
   provisional in `protocol/v4.py`.

2. **The `cc 8c 05/06/07` enable mask, decoded.** alienfx-controls.h calls the
   analogous command a "Mask command (purpose unknown)"; alien-thunder omits it.
   It is three reports of 60 payload bytes — 180 slots — of which exactly 92 are
   set, matching the LED count, with slot *i* enabling wire id *i*+1. So the
   controller numbers LEDs from zero and colour records carry that id plus one,
   which is the same offset alien-thunder applies from the other direction.
   `v5.mask_for()` rebuilds AWCC's three reports from a list of ids alone.

3. **Multiple keyframes per `0x24` report.** A keyframe is 8 bytes and the first
   starts at offset 2, so three fit in a 33-byte report. AWCC uses this — its
   two-colour morphs arrive as one 18-byte packet. tr1xem/AWCC and alienfx-tools
   both send one keyframe per report, so a seven-hue spectrum costs them seven
   reports against our three.

4. **Breathing is a morph to black.** AWCC's one-colour breathing profiles morph
   the colour against `000000` rather than against itself.

5. **A two-colour morph is not two morph keyframes.** On a zone animation AWCC
   sends one `0x02` morph frame carrying the first colour, the duration and the
   tempo, then an *action `0x00`* frame with a duration of `0x0001` naming the
   second colour. Sending two morph frames is accepted by the controller but
   animates as two separate fades and looks ragged. A chain of three or more --
   the spectrum -- really is all morph frames, so the pair is the special case.
   The power-button profiles are different again: two morph frames at duration
   `0x03E8`. All three shapes are in `tests/fixtures/v3/` and each has a test.

## Key geometry

`layout.py` has no counterpart in any project above. alien-thunder maps ids to key
*names* for an ABNT2 layout, which is enough to colour a named key but not to
address a column; nothing published gives the physical arrangement.

The first version here was hand-built by eye in this repository. It has since been
replaced by measurement: each LED lit on its own and located with a webcam, then fit
to a grid. The fit is checked numerically (columns strictly increasing with x,
residuals well under a key width) and by eye against patterns defined in grid terms;
an automated pixel read-back cannot check it, because it would light and read the
same assignment. That dropped 24 ids that never appear on
the wire, corrected labels the hand-built map had wrong (the id it called "ESC"
measures two rows below the function row), and established that only 85 of the 92
addressable ids drive a physical LED on an ANSI unit. The tooling lives in the
`dev/tools/` directory (`map_keys.py`, `fit_grid.py`, `verify_grid.py`) and the method
is written up in `layout.py`'s own docstring.
