"""Native control panel, built with PyQt6.

PyQt rather than a browser page because this is a hardware panel on a KDE desktop
and it should look like it belongs there; PyQt rather than GTK because Qt is what
Plasma itself is built on. Everything visual is custom-painted, so the window does
not inherit whatever widget theme happens to be installed.

PyQt6 is the only dependency the project has, and it is needed for the GUI alone --
the library, the CLI and the games run on the standard library.
"""
from .app import run

__all__ = ["run"]
