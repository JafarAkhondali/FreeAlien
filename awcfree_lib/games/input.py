"""Non-blocking keyboard input for the games.

The keyboard is the display here, but typing and lighting go through different
devices -- the keys are an ordinary i8042 input device, the LEDs are the USB
controller -- so reading keystrokes while driving the lights needs nothing special.
This just puts the terminal in cbreak mode and drains stdin without blocking.
"""
from __future__ import annotations

import os
import select
import sys
import termios
import tty

UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
QUIT, PAUSE, RESTART = "quit", "pause", "restart"

#: Letter keys, so the game is playable without arrow keys.
_LETTERS = {
    "w": UP, "s": DOWN, "a": LEFT, "d": RIGHT,
    "k": UP, "j": DOWN, "h": LEFT, "l": RIGHT,
    "q": QUIT, "\x03": QUIT, "\x1b\x1b": QUIT,
    "p": PAUSE, " ": PAUSE, "r": RESTART,
}

#: Final byte of the CSI sequence each arrow key sends: ESC [ A/B/C/D.
_ARROWS = {"A": UP, "B": DOWN, "C": RIGHT, "D": LEFT}


class KeyReader:
    """Reads single keypresses without waiting for a newline.

    Used as a context manager so the terminal is always restored, including when
    the game raises.  On a terminal that cannot be put into cbreak mode -- a pipe,
    or no tty at all -- `available` is False and `poll` simply returns None, which
    lets a game run in a demo mode rather than crash.
    """

    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stdin
        self.fd = self.stream.fileno() if hasattr(self.stream, "fileno") else -1
        self.available = False
        self._saved = None

    def __enter__(self) -> KeyReader:
        try:
            if os.isatty(self.fd):
                self._saved = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
                self.available = True
        except (termios.error, OSError, ValueError):
            self.available = False
        return self

    def __exit__(self, *exc: object) -> None:
        if self._saved is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            except (termios.error, OSError):
                pass
            self._saved = None
        self.available = False

    def _read_ready(self) -> str:
        if not self.available:
            return ""
        chunks = []
        while select.select([self.fd], [], [], 0)[0]:
            data = os.read(self.fd, 64)
            if not data:
                break
            chunks.append(data.decode("utf-8", "replace"))
        return "".join(chunks)

    def poll(self) -> str | None:
        """Most recent meaningful key since the last call, or None.

        Only the last direction in the buffer is returned: holding a key repeats it,
        and acting on every repeat would make the snake lurch several cells at once.
        """
        buf = self._read_ready()
        if not buf:
            return None
        action = None
        i = 0
        while i < len(buf):
            ch = buf[i]
            if ch == "\x1b" and buf[i + 1 : i + 2] == "[":
                key = buf[i + 2 : i + 3]
                if key in _ARROWS:
                    action = _ARROWS[key]
                    i += 3
                    continue
                i += 2
                continue
            got = _LETTERS.get(ch.lower())
            if got is not None:
                # quit wins outright, so a stray direction cannot swallow it
                if got == QUIT:
                    return QUIT
                action = got
            i += 1
        return action

    def drain(self) -> None:
        """Throw away anything buffered, so a held key does not leak between rounds."""
        self._read_ready()
