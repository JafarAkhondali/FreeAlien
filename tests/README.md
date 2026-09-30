# Automated tests

From the repository root:

```bash
python3 -m pytest
python3 -m pytest tests/test_against_captures.py -q
```

Tests cover protocol capture replay, game rules, Qt interactions, sound playback
and event decoding, thermal authorization, and installer lifecycle. Hardware and
administrator operations are mocked. Qt is headless by default. Local socket
permission is required for thermal checks.

`fixtures/v3/` contains the USB captures used for byte-for-byte regression checks.
Keep them in Git. New automated tests should be named `test_*.py`.
See [development.md](../docs/development.md) for dependencies and manual workflows.
