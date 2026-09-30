"""Pure packet encoders, one module per AlienFX protocol generation.

Nothing in here performs I/O, which is deliberate: the wire format can be checked
against the captures in `tests/fixtures/v3/` with no hardware attached.

  v4 -- AW-ELC chassis controller (187c:0551): touchpad, lid logo, power button.
  v5 -- Darfon per-key keyboard (0d62:d2b1).

alienfx-tools also documents v6 (monitors) and v7 (mice).  Neither applies to this
laptop, so neither is implemented; the package is laid out so they can be added as
sibling modules without touching anything else.
"""
from . import v4, v5

__all__ = ["v4", "v5"]
