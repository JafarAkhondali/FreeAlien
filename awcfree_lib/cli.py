"""Command line front end, used to exercise the library before there is a GUI.

Every subcommand honours `--dry-run`, which prints the packets that would go out
instead of sending them.  That makes it possible to diff our output against the
captures in `tests/fixtures/v3/` without touching the hardware.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Sequence

from . import layout
from .canvas import Canvas
from .devices import Chassis, Keyboard
from .errors import AwcfreeError
from .protocol import v4, v5
from .transport import find_hidraw

Rgb = tuple[int, int, int]

NAMED_COLOURS: dict[str, Rgb] = {
    "off": (0, 0, 0), "black": (0, 0, 0), "white": (255, 255, 255),
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255), "magenta": (255, 0, 255),
    "purple": (128, 0, 128), "orange": (255, 165, 0), "pink": (255, 105, 180),
    "teal": (0, 191, 255), "lime": (128, 255, 0),
}

UDEV_RULE_PATH = "/etc/udev/rules.d/70-awcfree.rules"


def parse_colour(text: str) -> Rgb:
    """Accept a name, `#rrggbb`, `rrggbb`, or `r,g,b`."""
    s = text.strip().lower()
    if s in NAMED_COLOURS:
        return NAMED_COLOURS[s]
    if "," in s:
        parts = [int(p) for p in s.split(",")]
        if len(parts) != 3:
            raise argparse.ArgumentTypeError(f"need three components: {text!r}")
        return (parts[0], parts[1], parts[2])
    h = s.lstrip("#")
    if len(h) == 6:
        try:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"cannot read {text!r} as a colour; try red, #ff8800 or 255,136,0"
    )


def parse_led(text: str) -> int:
    """Accept a hex id (`0x15`) or a key label (`F1`, `ESC`).

    Labels are tried before bare hex, because key names like `F1` and `BE` are also
    valid hex and the label is what the user meant.  Use the `0x` form to force an id.
    """
    s = text.strip()
    if not s.lower().startswith("0x"):
        try:
            return layout.by_name(s)
        except KeyError:
            pass
    try:
        led = int(s, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"no LED called {text!r}; try `freealien keys` for the list"
        ) from None
    if led not in layout.ALL_LEDS:
        raise argparse.ArgumentTypeError(f"0x{led:02x} is not one of the 92 LEDs")
    return led


# --- dry run ----------------------------------------------------------------
class _Recorder:
    """Stands in for a device and prints packets instead of sending them."""

    def __init__(self, label: str, report_len: int) -> None:
        self.label = label
        self.report_len = report_len
        self.count = 0

    def _show(self, packet: bytes) -> None:
        self.count += 1
        trimmed = bytes(packet).rstrip(b"\x00") or b"\x00"
        print(f"  {self.label} {trimmed.hex(' ')}")

    def open(self) -> None: ...
    def close(self) -> None: ...
    def send_feature(self, packet: bytes) -> None: self._show(packet)
    def send_output(self, packet: bytes, report_id: int = 0) -> None: self._show(packet)
    def get_feature(self, report_id: int) -> bytes: return b"\x00" * self.report_len
    def get_input(self) -> bytes: return b"\x00" * self.report_len


def _keyboard(args) -> Keyboard:
    kb = Keyboard.__new__(Keyboard)
    if args.dry_run:
        kb.dev = _Recorder("kb ", v5.LEN)
        kb.send_mask = False
        kb._staged, kb._onwire, kb._handshaken = {}, {}, False
        return kb
    return Keyboard()


def _chassis(args) -> Chassis:
    if args.dry_run:
        ch = Chassis.__new__(Chassis)
        ch.dev = _Recorder("elc", v4.LEN)
        return ch
    return Chassis()


# --- commands ---------------------------------------------------------------
def cmd_status(args) -> int:
    kb_path = find_hidraw(0x0D62, 0xD2B1, descriptor_contains=b"\x85\xcc")
    elc_path = find_hidraw(0x187C, 0x0551)
    rows = [("keyboard", "0d62:d2b1", kb_path), ("chassis", "187c:0551", elc_path)]
    ok = True
    for name, ident, path in rows:
        if path is None:
            print(f"{name:9} {ident}  NOT FOUND")
            ok = False
            continue
        writable = os.access(path, os.W_OK)
        state = "ready" if writable else "no write permission"
        if not writable:
            ok = False
        print(f"{name:9} {ident}  {path}  {state}")
    print()
    print(f"LEDs known: {len(layout.ALL_LEDS)} "
          f"({len(layout.PLACED_LEDS)} wired, {len(layout.DEAD_LEDS)} light nothing here)")
    if not ok:
        print()
        print("Not everything is reachable. Run `freealien install-udev` for non-root "
              "access, or use sudo.")
    return 0 if ok else 1


def cmd_install_udev(args) -> int:
    rule = (
        "# FreeAlien: let the logged-in user drive the Alienware lighting controllers.\n"
        "# The keyboard's LED controller takes commands on interface 00; typing goes\n"
        "# through the built-in i8042 keyboard, not through this device.\n"
        'SUBSYSTEM=="hidraw", KERNEL=="hidraw*", ATTRS{idVendor}=="0d62", '
        'ATTRS{idProduct}=="d2b1", ENV{ID_USB_INTERFACE_NUM}=="00", TAG+="uaccess"\n'
        'SUBSYSTEM=="hidraw", KERNEL=="hidraw*", ATTRS{idVendor}=="187c", '
        'ATTRS{idProduct}=="0551", TAG+="uaccess"\n'
    )
    print(rule)
    print(f"Write the above to {UDEV_RULE_PATH}, then:")
    print("  sudo udevadm control --reload-rules && sudo udevadm trigger")
    print()
    print("This command only prints the rule; it does not install it, so nothing")
    print("touches /etc without you running the commands yourself.")
    return 0


def cmd_keys(args) -> int:
    for led in layout.ALL_LEDS:
        cell = layout.CELLS.get(led)
        name = layout.NAMES.get(led, "")
        where = ("lights nothing on this unit" if cell is None
                 else f"col={cell[0]:<3d} row={cell[1]}")
        print(f"0x{led:02x}  {name:<24} {where}")
    return 0


def cmd_grid(args) -> int:
    canvas = Canvas()
    for col in range(canvas.cols):
        for row in range(canvas.rows):
            if canvas.leds_at(col, row):
                canvas[col, row] = (255, 0, 0)
    print(f"{canvas.cols}x{canvas.rows} grid, {len(canvas.lit_cells)} cells have keys:")
    for i, line in enumerate(canvas.rows_as_text()):
        print(f"  row{i} |{line}|")
    clashes = [
        (col, row, canvas.leds_at(col, row))
        for row in range(canvas.rows) for col in range(canvas.cols)
        if len(canvas.leds_at(col, row)) > 1
    ]
    if clashes:
        print()
        print("Cells holding more than one LED. Some are genuine (wide keys); the")
        print("rest are positions inherited from guesswork. `freealien identify` settles them.")
        for col, row, leds in clashes:
            names = ", ".join(layout.NAMES.get(x, f"0x{x:02x}") for x in leds)
            print(f"  ({col:2d},{row}) {names}")
    return 0


def cmd_static(args) -> int:
    with _keyboard(args) as kb:
        if not args.no_take_control:
            kb.take_control()
        kb.fill(args.colour)
        n = kb.flush(force=True)
    print(f"keyboard: {n} reports")
    return 0


def cmd_key(args) -> int:
    kb = _keyboard(args)
    kb.open()
    try:
        if not args.no_take_control:
            kb.take_control()
        if not args.keep:
            kb.fill((0, 0, 0))
        for led in args.leds:
            kb.set(led, args.colour)
        n = kb.flush(force=True)
    finally:
        kb.close()
    print(f"keyboard: {n} reports, {len(args.leds)} LEDs set")
    return 0


def cmd_effect(args) -> int:
    kb = _keyboard(args)
    kb.open()
    try:
        if args.name == "off":
            kb.effect_off()
        else:
            kb.effect(args.name, tempo=args.tempo, colour_mode=args.colour_mode,
                      primary=args.colour, secondary=args.secondary or args.colour)
    finally:
        kb.close()
    print(f"keyboard effect: {args.name}")
    return 0


def cmd_touchpad(args) -> int:
    ch = _chassis(args)
    ch.open()
    try:
        n = ch.set_touchpad(args.colour, persist=args.persist)
    finally:
        ch.close()
    print(f"touchpad: {n} reports")
    return 0


def cmd_logo(args) -> int:
    ch = _chassis(args)
    ch.open()
    try:
        n = ch.set_logo(args.colour, persist=args.persist)
    finally:
        ch.close()
    print(f"lid logo: {n} reports")
    return 0


def cmd_spectrum(args) -> int:
    zone = v4.ZONE_NAMES.get(args.zone, None)
    if zone is None:
        zone = int(args.zone, 0)
    ch = _chassis(args)
    ch.open()
    try:
        n = ch.spectrum(zone, persist=args.persist)
    finally:
        ch.close()
    print(f"spectrum on zone 0x{zone:02x}: {n} reports")
    return 0


def cmd_morph(args) -> int:
    zone = v4.ZONE_NAMES.get(args.zone) or int(args.zone, 0)
    ch = _chassis(args)
    ch.open()
    try:
        n = ch.morph(zone, args.colours, persist=args.persist)
    finally:
        ch.close()
    print(f"morph on zone 0x{zone:02x} through {len(args.colours)} colours: {n} reports")
    return 0


def cmd_brightness(args) -> int:
    ch = _chassis(args)
    ch.open()
    try:
        n = ch.brightness(args.level)
    finally:
        ch.close()
    print(f"brightness {args.level}: {n} reports")
    return 0


def cmd_power(args) -> int:
    ch = _chassis(args)
    ch.open()
    try:
        if args.profile:
            n = ch.set_power_profile(args.profile, [args.colour])
            print(f"power profile {args.profile}: {n} reports")
        else:
            n = ch.set_power_all(args.colour, args.battery or args.colour)
            print(f"all six power profiles: {n} reports")
    finally:
        ch.close()
    print()
    print("Profile names within each trio are inferred, not confirmed. If the")
    print("colours land on the wrong states, the mapping in protocol/v4.py needs a swap.")
    return 0


def cmd_zone(args) -> int:
    """Set one chassis zone by raw id, so each surface can be identified alone."""
    zone = v4.ZONE_NAMES.get(args.zone) if not args.zone.lower().startswith("0x") else None
    if zone is None:
        try:
            zone = int(args.zone, 0)
        except ValueError:
            print(f"error: cannot read {args.zone!r} as a zone", file=sys.stderr)
            return 1
    ch = _chassis(args)
    ch.open()
    try:
        if args.only:
            ch.static({z: (0, 0, 0) for z in range(8)})
        n = ch.static({zone: args.colour}, persist=args.persist)
    finally:
        ch.close()
    print(f"zone 0x{zone:02x} -> {args.colour}: {n} reports")
    return 0


def cmd_probe(args) -> int:
    if args.dry_run:
        print("nothing to probe in dry-run mode")
        return 0
    try:
        with Keyboard() as kb:
            print("keyboard cc 94 reply:")
            print("  " + kb.probe().hex(" "))
    except AwcfreeError as exc:
        print(f"keyboard: {exc}")
    try:
        with Chassis() as ch:
            print("chassis firmware (03 20 00):")
            print("  " + ch.firmware().hex(" "))
            print("chassis ELC config (03 20 02):")
            print("  " + ch.elc_config().hex(" "))
    except AwcfreeError as exc:
        print(f"chassis: {exc}")
    print()
    print("These replies are not decoded. The ELC config one should describe the")
    print("controller's zones; dumping it is the way to settle the zone map.")
    return 0


def cmd_zones(args) -> int:
    """Walk candidate zone ids so the unmapped chassis surfaces can be identified."""
    ch = _chassis(args)
    ch.open()
    try:
        for zone in args.zones:
            ch.static({z: (0, 0, 0) for z in range(0, 8)})
            ch.static({zone: args.colour})
            print(f"zone 0x{zone:02x} -> {args.colour}. What lit up? "
                  f"(enter to continue)", end="")
            sys.stdout.flush()
            if not args.dry_run:
                input()
            else:
                print()
    finally:
        ch.close()
    return 0


def cmd_identify(args) -> int:
    """Light one LED at a time so its physical key can be recorded.

    This is how the two unplaced ids and the inherited-guess positions get settled.
    Answers go to stdout as a Python dict fragment, ready to paste into layout.py.
    """
    leds = args.leds or list(layout.UNPLACED_LEDS)
    if not leds:
        print("nothing to identify; pass ids explicitly to re-check them")
        return 0
    kb = _keyboard(args)
    kb.open()
    kb.take_control()
    found: dict[int, str] = {}
    try:
        for led in leds:
            kb.fill((0, 0, 0))
            kb.set(led, args.colour)
            kb.flush(force=True)
            label = "" if args.dry_run else input(f"0x{led:02x} is lit. Which key? ")
            if label.strip():
                found[led] = label.strip()
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        kb.fill((0, 0, 0))
        kb.flush(force=True)
        kb.close()
    if found:
        print()
        print("Paste into layout.NAMES:")
        for led, label in found.items():
            print(f"    0x{led:02x}: {label!r},")
    return 0


def cmd_demo(args) -> int:
    """A scrolling bar across the canvas -- proves the games path end to end."""
    canvas = Canvas()
    kb = _keyboard(args)
    kb.open()
    kb.take_control()
    frames = 0
    started = time.monotonic()
    try:
        deadline = started + args.seconds
        col = 0
        while time.monotonic() < deadline:
            canvas.clear()
            canvas.vline(col % canvas.cols, args.colour)
            canvas.vline((col + 1) % canvas.cols, tuple(c // 3 for c in args.colour))
            canvas.present(kb)
            frames += 1
            col += 1
            if args.dry_run:
                break
            time.sleep(1.0 / args.fps)
    except KeyboardInterrupt:
        pass
    finally:
        kb.fill((0, 0, 0))
        kb.flush(force=True)
        kb.close()
    elapsed = time.monotonic() - started
    if frames and elapsed > 0:
        print(f"{frames} frames in {elapsed:.1f}s -> {frames / elapsed:.1f} fps")
    return 0


def cmd_gui(args) -> int:
    try:
        from .gui import run
    except ImportError as exc:
        print("The GUI needs PyQt6, which is the project's only dependency and is")
        print("required for this command alone:")
        print("  sudo apt install python3-pyqt6      # or: pip install PyQt6")
        print(f"({exc})", file=sys.stderr)
        return 1
    return run([])


def cmd_snake(args) -> int:
    from .games.runner import run_snake

    best = run_snake(field=args.field, wrap=not args.walls, fps=args.fps,
                     start_tps=args.speed, max_tps=args.max_speed, seed=args.seed)
    print(f"best score this session: {best}")
    return 0


def cmd_off(args) -> int:
    rc = 0
    try:
        kb = _keyboard(args)
        with kb:
            kb.take_control()
            kb.fill((0, 0, 0))
            kb.flush(force=True)
        print("keyboard off")
    except AwcfreeError as exc:
        print(f"keyboard: {exc}")
        rc = 1
    try:
        ch = _chassis(args)
        ch.open()
        try:
            ch.off()
        finally:
            ch.close()
        print("chassis off")
    except AwcfreeError as exc:
        print(f"chassis: {exc}")
        rc = 1
    return rc


# --- argument wiring --------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="freealien",
        description="Alienware lighting control for Linux (m16 R2 and relatives).",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="print the packets instead of sending them")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="which controllers are present and reachable").set_defaults(func=cmd_status)
    sub.add_parser("install-udev", help="print the udev rule for non-root access").set_defaults(func=cmd_install_udev)
    sub.add_parser("keys", help="list the 92 LEDs").set_defaults(func=cmd_keys)
    sub.add_parser("grid", help="show the canvas grid and any ambiguous cells").set_defaults(func=cmd_grid)
    sub.add_parser("probe", help="dump the controllers' raw replies").set_defaults(func=cmd_probe)
    sub.add_parser("off", help="everything black").set_defaults(func=cmd_off)

    sp = sub.add_parser("static", help="one colour on every key")
    sp.add_argument("colour", type=parse_colour)
    sp.add_argument("--no-take-control", action="store_true",
                    help="do not cancel a running hardware effect first")
    sp.set_defaults(func=cmd_static)

    sp = sub.add_parser("key", help="colour specific keys")
    sp.add_argument("colour", type=parse_colour)
    sp.add_argument("leds", nargs="+", type=parse_led, metavar="LED")
    sp.add_argument("--keep", action="store_true",
                    help="leave the other keys as they are instead of blacking them")
    sp.add_argument("--no-take-control", action="store_true",
                    help="do not cancel a running hardware effect first")
    sp.set_defaults(func=cmd_key)

    sp = sub.add_parser("effect", help="run a controller-side keyboard effect")
    sp.add_argument("name", choices=sorted(v5.EFFECTS) + ["off"])
    sp.add_argument("colour", nargs="?", type=parse_colour, default=(255, 0, 0))
    sp.add_argument("--secondary", type=parse_colour)
    sp.add_argument("--tempo", type=lambda s: int(s, 0), default=0x64)
    sp.add_argument("--colour-mode", type=int, choices=(1, 2, 3), default=1)
    sp.set_defaults(func=cmd_effect)

    sp = sub.add_parser("touchpad", help="colour the touchpad ring")
    sp.add_argument("colour", type=parse_colour)
    sp.add_argument("--persist", action="store_true", help="survive a reboot")
    sp.set_defaults(func=cmd_touchpad)

    sp = sub.add_parser("logo", help="colour the illuminated lid emblem")
    sp.add_argument("colour", type=parse_colour)
    sp.add_argument("--persist", action="store_true")
    sp.set_defaults(func=cmd_logo)

    sp = sub.add_parser("spectrum", help="rainbow cycle on a chassis zone")
    sp.add_argument("zone", nargs="?", default="touchpad")
    sp.add_argument("--persist", action="store_true")
    sp.set_defaults(func=cmd_spectrum)

    sp = sub.add_parser("morph", help="fade a chassis zone through colours")
    sp.add_argument("zone")
    sp.add_argument("colours", nargs="+", type=parse_colour)
    sp.add_argument("--persist", action="store_true")
    sp.set_defaults(func=cmd_morph)

    sp = sub.add_parser("brightness", help="chassis brightness, 0-255")
    sp.add_argument("level", type=int)
    sp.set_defaults(func=cmd_brightness)

    sp = sub.add_parser("power", help="power-button colours per power state")
    sp.add_argument("colour", type=parse_colour, help="colour for the AC states")
    sp.add_argument("battery", nargs="?", type=parse_colour,
                    help="colour for the battery states (defaults to the same)")
    sp.add_argument("--profile", choices=sorted(v4.POWER_PROFILES),
                    help="write just this one profile")
    sp.set_defaults(func=cmd_power)

    sp = sub.add_parser("zone", help="set one chassis zone by raw id")
    sp.add_argument("zone", help="a name (touchpad, logo, power) or an id like 0x03")
    sp.add_argument("colour", type=parse_colour)
    sp.add_argument("--only", action="store_true",
                    help="black every other zone first, so only this one is lit")
    sp.add_argument("--persist", action="store_true")
    sp.set_defaults(func=cmd_zone)

    sp = sub.add_parser("probe-zones", help="walk chassis zone ids to see what each drives")
    sp.add_argument("zones", nargs="*", type=lambda s: int(s, 0),
                    default=[0, 1, 2, 3, 4, 5, 6, 7])
    sp.add_argument("--colour", type=parse_colour, default=(255, 255, 255))
    sp.set_defaults(func=cmd_zones)

    sp = sub.add_parser("identify", help="light LEDs one by one to place them")
    sp.add_argument("leds", nargs="*", type=parse_led)
    sp.add_argument("--colour", type=parse_colour, default=(255, 255, 255))
    sp.set_defaults(func=cmd_identify)

    sub.add_parser("gui", help="open the control panel").set_defaults(func=cmd_gui)

    sp = sub.add_parser("snake", help="play snake on the keys")
    sp.add_argument("--field", choices=("solid", "wide", "full"), default="solid",
                    help="solid (default) uses only cells that have an LED; the "
                         "others are bigger but contain holes that cannot be drawn")
    sp.add_argument("--walls", action="store_true",
                    help="make the four edges lethal; they wrap by default, so the "
                         "only way to lose is to hit yourself")
    sp.add_argument("--speed", type=float, default=5.0, help="starting moves/second")
    sp.add_argument("--max-speed", type=float, default=14.0, help="fastest moves/second")
    sp.add_argument("--fps", type=float, default=30.0)
    sp.add_argument("--seed", type=int, help="fix the food sequence")
    sp.set_defaults(func=cmd_snake)

    sp = sub.add_parser("demo", help="scrolling bar; measures achievable frame rate")
    sp.add_argument("--seconds", type=float, default=5.0)
    sp.add_argument("--fps", type=float, default=30.0)
    sp.add_argument("--colour", type=parse_colour, default=(0, 120, 255))
    sp.set_defaults(func=cmd_demo)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AwcfreeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
