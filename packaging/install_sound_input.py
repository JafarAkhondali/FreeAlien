#!/usr/bin/python3 -I
"""One-time keyboard-scoped uaccess setup; input and audio stay unprivileged."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RULE_PATH = Path("/etc/udev/rules.d/70-awcfree-keyboard-sounds.rules")


def keyboard_rule(event, sys_root=Path("/sys/class/input")):
    if not re.fullmatch(r"event[0-9]+", event):
        raise ValueError("Select an event device, such as event3")
    device = sys_root / event / "device"
    bits = int((device / "capabilities/key").read_text().split()[-1], 16)
    if not all(bits & (1 << key) for key in (30, 28, 57)):
        raise ValueError("Selected device is not a typing keyboard")
    name = (device / "name").read_text().strip()
    if not name or any(ch in name for ch in '\\"\n\r*?[]'):
        raise ValueError("Keyboard name cannot safely be used in a udev match")
    return (f'SUBSYSTEM=="input", KERNEL=="event*", ENV{{ID_INPUT_KEYBOARD}}=="1", '
            f'ATTRS{{name}}=="{name}", TAG+="uaccess"\n')


def install(events):
    if os.geteuid() != 0:
        raise PermissionError("Administrator authorization is required for one-time setup")
    events = [events] if isinstance(events, str) else list(dict.fromkeys(events))
    if not events: raise ValueError("Select at least one keyboard")
    rules = []
    for event in events:
        rules.append(keyboard_rule(event))
        info = subprocess.run(["/usr/bin/udevadm", "info", "--query=property", "--name", "/dev/input/" + event],
                              capture_output=True, text=True, check=True)
        if "ID_INPUT_KEYBOARD=1" not in info.stdout.splitlines():
            raise ValueError("udev does not identify this device as a keyboard")
    rule = "".join(dict.fromkeys(rules))
    RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".awcfree-", dir=RULE_PATH.parent)
    try:
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o644)
            os.fchown(output.fileno(), 0, 0)
            output.write(rule)
        os.replace(temp, RULE_PATH)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    subprocess.run(["/usr/bin/udevadm", "control", "--reload-rules"], check=True)
    for event in events:
        subprocess.run(["/usr/bin/udevadm", "trigger", "--action=change",
                        "--subsystem-match=input", "--sysname-match=" + event], check=True)
    subprocess.run(["/usr/bin/udevadm", "settle", "--timeout=10"], check=True)
    print("Keyboard access configured for the active local session.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, action="append", help="Selected keyboard event name (repeatable)")
    args = parser.parse_args()
    try:
        install(args.device)
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Keyboard access setup failed: {exc}\n")
