"""Tiny original arcade tones, played through the system audio player if present."""
from __future__ import annotations

import atexit
import math
import shutil
import struct
import tempfile
import wave
from pathlib import Path

from PyQt6.QtCore import QProcess


class ArcadeAudio:
    def __init__(self):
        self.player = shutil.which("paplay") or shutil.which("pw-play") or shutil.which("aplay")
        self.root = Path(tempfile.mkdtemp(prefix="awcfree-arcade-"))
        atexit.register(shutil.rmtree, self.root, True)
        self.files = {name: self._tone(name, spec) for name, spec in {
            "shot": ((740, 0.055),),
            "hit": ((390, 0.09),),
            "kill": ((660, 0.075), (990, 0.12)),
        }.items()}

    def _tone(self, name, notes):
        rate = 22050
        samples = bytearray()
        for frequency, duration in notes:
            count = int(rate * duration)
            for i in range(count):
                envelope = min(1.0, i / 160, (count - i) / 420)
                value = int(9500 * envelope * math.sin(2 * math.pi * frequency * i / rate))
                samples.extend(struct.pack("<h", value))
        path = self.root / f"{name}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(samples)
        return str(path)

    def play(self, name: str) -> None:
        if self.player:
            QProcess.startDetached(self.player, [self.files[name]])
