# Developing FreeAlien

Run commands from the repository root unless noted otherwise.

## Repository map

| Location | Purpose |
| --- | --- |
| `freealien` | Current CLI/GUI launcher |
| `awcfree` | Compatibility launcher |
| `awcfree_lib/` | Runtime library, GUI, protocols, games, audio and shipped assets |
| `packaging/` | TUI setup, privileged helpers, service templates and desktop integration |
| `tests/` | Automated tests using mocks, temporary files and local sockets |
| `tests/fixtures/v3/` | Curated USB captures replayed by protocol tests |
| `dev/tools/` | Maintained measurement tools and offline sound importer |
| `dev/captures/` | Earlier raw captures and reverse-engineering notes |
| `dev/local/` | Ignored local archives/scratch files; not distributed |
| `docs/` | Contributor documentation and demo media |

The runtime package keeps its `awcfree_lib` name for compatibility. The installer
copies only the runtime package, packaging files, launchers, README, credits and license.
Development tools, tests, archives and captures are not part of the installation.

## Environment and checks

Use Python 3.10+ with PyQt6 and pytest for the automated suite. The CLI and protocol
library use the standard library. A virtual environment is optional; if PyQt6 is
provided by your distribution, use its Python or a virtual environment configured
to access system packages.

```bash
./freealien --help
./freealien --dry-run static red
python3 -m pytest
python3 -m pytest tests/test_against_captures.py -q
python3 dev/tools/verify_grid.py --numeric
```

`pytest.ini` restricts discovery to `tests/`, excludes fixtures/development trees,
and supplies the repository import path. `tests/conftest.py` defaults Qt to its
offscreen backend. Tests mock hardware and privileged setup; they do not install
services, capture keyboard input from real devices, or change cooling/lighting.
The thermal-service tests require local sockets. A sandbox that blocks sockets must
permit those tests or they will fail with permission errors.

For a manual GUI check, run `./freealien gui` as your normal desktop user. That
opens real device connections; use the mocked automated tests for hardware-free
validation.

## Hardware development

See [measurement tools](../dev/tools/README.md) for camera mapping and layout
regeneration. Numerical checking needs no hardware; mapping and visual pattern
checks do write lighting settings. The measurement tools need NumPy and OpenCV.
`gen_layout2.py` rewrites `awcfree_lib/layout.py`; review the result and replay the
capture tests before accepting it. Paths are relative to the checkout rather than
a developer-specific home directory.

The sound importer needs ffmpeg and 7z only
when rebuilding recordings; they are not runtime requirements.

## Local files

The original backup archive is retained locally at `dev/local/backup.zip` and is
ignored by Git. Editor settings, Python bytecode, virtual environments, agent
configuration, credentials and test caches are also ignored. Curated measurement
JSON, protocol fixtures, documentation images and bundled sound assets remain
version-controlled. Review `git status` before staging; ignored files already
present in old commits are not removed from history by `.gitignore`.
