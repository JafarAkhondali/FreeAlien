#!/usr/bin/python3 -I
"""One-time admin installation; subsequent GUI thermal requests need no prompts."""
import argparse
import os
from pathlib import Path
import pwd
import subprocess
import tempfile


def atomic_install(path, content, mode):
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".awcfree-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, 0)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description="Install the FreeAlien thermal service")
    parser.add_argument("--user", help="Local user allowed to control cooling")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run the installer as root")
    try:
        user = pwd.getpwnam(args.user) if args.user else pwd.getpwuid(
            int(os.environ.get("SUDO_UID") or os.environ.get("PKEXEC_UID") or "0"))
    except (KeyError, ValueError):
        parser.error("Cannot determine the requesting user; specify --user")
    if user.pw_uid == 0:
        parser.error("Specify a non-root user with --user")
    source = Path(__file__).resolve().parent
    # Resolve stable WMI device ancestors, excluding dynamically numbered class nodes.
    devices = set()
    for directory, driver in ((Path('/sys/class/platform-profile'), 'alienware-wmi'),
                              (Path('/sys/class/hwmon'), 'alienware_wmi')):
        for node in directory.glob('*'):
            try:
                if (node / 'name').read_text().strip() == driver:
                    device = node.resolve().parent.parent
                    if not device.is_relative_to('/sys/devices') or any(c.isspace() for c in str(device)):
                        parser.error("Unexpected thermal device path")
                    devices.add(str(device))
            except OSError:
                continue
    if not devices:
        parser.error("No Alienware thermal driver found; load the driver before installation")
    service = (source / 'awcfree-thermals.service').read_text().replace('@UID@', str(user.pw_uid))
    service = service.replace('@WRITE_PATHS@', '\n'.join('ReadWritePaths=' + p for p in sorted(devices)))
    socket = (source / 'awcfree-thermals.socket').read_text().replace('@UID@', str(user.pw_uid))
    # Validate both generated units before replacing anything on the system.
    with tempfile.TemporaryDirectory(prefix='awcfree-units-') as tmp:
        for name, text in [('awcfree-thermals.service', service), ('awcfree-thermals.socket', socket)]:
            (Path(tmp) / name).write_text(text)
        subprocess.run(['/usr/bin/systemd-analyze', 'verify',
                        str(Path(tmp) / 'awcfree-thermals.service'),
                        str(Path(tmp) / 'awcfree-thermals.socket')], check=True)
    atomic_install(Path('/usr/local/libexec/awcfree-thermals'),
                   (source.parent / 'awcfree_lib/thermals.py').read_bytes(), 0o755)
    for name, text in [('awcfree-thermals.service', service), ('awcfree-thermals.socket', socket)]:
        atomic_install(Path('/etc/systemd/system') / name, text.encode(), 0o644)
    subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True)
    # Stop accepted connections before replacing the socket during an upgrade.
    subprocess.run(['/usr/bin/systemctl', 'stop', 'awcfree-thermals.service', 'awcfree-thermals.socket'], check=True)
    subprocess.run(['/usr/bin/systemctl', 'enable', '--now', 'awcfree-thermals.socket'], check=True)
    print(f'Thermal service installed for {user.pw_name}. No logout or per-change authentication required.')


if __name__ == '__main__':
    main()
