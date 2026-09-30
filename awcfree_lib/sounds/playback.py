"""Bounded polyphonic mixer with one persistent PulseAudio/PipeWire stream."""
from __future__ import annotations

from array import array
from collections import deque
import ctypes as c
import ctypes.util
import queue
import sys
import threading
import time

from .packs import RATE, sound_for_key


class SampleSpec(c.Structure):
    _fields_ = [("format", c.c_int), ("rate", c.c_uint32), ("channels", c.c_uint8)]


class BufferAttr(c.Structure):
    _fields_ = [(name, c.c_uint32) for name in ("maxlength", "tlength", "prebuf", "minreq", "fragsize")]


class PulseOutput:
    """Small binding to libpulse-simple's documented client API; owned by one thread."""
    def __init__(self):
        library = ctypes.util.find_library("pulse-simple")
        if not library:
            raise RuntimeError("Audio needs libpulse-simple (PulseAudio or PipeWire's PulseAudio compatibility).")
        self.lib = c.CDLL(library)
        self.lib.pa_simple_new.argtypes = [c.c_char_p, c.c_char_p, c.c_int, c.c_char_p,
            c.c_char_p, c.POINTER(SampleSpec), c.c_void_p, c.POINTER(BufferAttr), c.POINTER(c.c_int)]
        self.lib.pa_simple_new.restype = c.c_void_p
        self.lib.pa_simple_write.argtypes = [c.c_void_p, c.c_char_p, c.c_size_t, c.POINTER(c.c_int)]
        self.lib.pa_simple_write.restype = c.c_int
        self.lib.pa_simple_free.argtypes = [c.c_void_p]
        self.lib.pa_simple_free.restype = None
        spec = SampleSpec(3 if sys.byteorder == "little" else 4, RATE, 2)
        attr = BufferAttr(0xffffffff, RATE * 4 // 20, 0, RATE * 4 // 100, 0xffffffff)
        error = c.c_int()
        self.stream = self.lib.pa_simple_new(None, b"FreeAlien", 1, None,
                                            b"Keyboard sounds", c.byref(spec), None,
                                            c.byref(attr), c.byref(error))
        if not self.stream:
            raise RuntimeError(f"Could not open your audio output (PulseAudio error {error.value}).")

    def write(self, data):
        error = c.c_int()
        if self.lib.pa_simple_write(self.stream, data, len(data), c.byref(error)) < 0:
            raise RuntimeError(f"Audio output disconnected (PulseAudio error {error.value}).")

    def close(self):
        if self.stream:
            self.lib.pa_simple_free(self.stream)
            self.stream = None


class Mixer:
    def __init__(self, maximum=16):
        self.voices = deque(maxlen=maximum)

    def add(self, samples, pan=0.0):
        # Equal-power panning, bounded even when many keys are played together.
        import math
        angle = (min(1.0, max(-1.0, pan)) + 1) * math.pi / 4
        self.voices.append([samples, 0, math.cos(angle), math.sin(angle)])

    def block(self, frames=240, volume=0.5):
        left, right = [0.0] * frames, [0.0] * frames
        surviving = deque(maxlen=self.voices.maxlen)
        for voice in self.voices:
            samples, start, gain_l, gain_r = voice
            size = min(frames, len(samples) - start)
            for i in range(size):
                value = samples[start + i]
                left[i] += value * gain_l
                right[i] += value * gain_r
            voice[1] += size
            if voice[1] < len(samples): surviving.append(voice)
        self.voices = surviving
        pcm = array("h")
        for l, r in zip(left, right):
            pcm.extend((int(max(-1, min(1, l * volume)) * 32767),
                        int(max(-1, min(1, r * volume)) * 32767)))
        return pcm.tobytes()


class SoundEngine:
    """Sample loading and playback stay off the GUI thread; late events are dropped."""
    def __init__(self, failed=lambda message: None, output_factory=PulseOutput):
        self.failed = failed
        self.output_factory = output_factory
        self.volume = 0.45
        self.requests = queue.Queue(maxsize=24)
        self.stop_event = threading.Event()
        self.clear_event = threading.Event()
        self.thread = None
        self.generation = 0

    def play(self, pack, name, variant, accented=True, pan=0.0):
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        try:
            self.requests.put_nowait((pack, name, variant, accented, pan, self.generation, time.monotonic()))
        except queue.Full:
            pass

    def silence(self):
        self.generation += 1
        while True:
            try: self.requests.get_nowait()
            except queue.Empty: break
        self.clear_event.set()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1)

    def _run(self):
        output = None
        mixer = Mixer()
        prepared = queue.Queue(maxsize=24)
        prepare_stop = threading.Event()

        def prepare():
            while not self.stop_event.is_set() and not prepare_stop.is_set():
                try: pack, name, variant, accented, pan, generation, stamp = self.requests.get(timeout=0.05)
                except queue.Empty: continue
                if generation != self.generation or time.monotonic() - stamp > 0.25:
                    continue
                try:
                    samples = sound_for_key(pack, name, variant, accented)
                except Exception as exc:
                    self.stop_event.set()
                    self.silence()
                    self.failed(f"Could not load keyboard sound: {exc}")
                    return
                if generation == self.generation:
                    try: prepared.put_nowait((samples, pan, generation, stamp))
                    except queue.Full: pass

        preparer = threading.Thread(target=prepare, daemon=True)
        try:
            output = self.output_factory()
            preparer.start()
            while not self.stop_event.is_set():
                if self.clear_event.is_set():
                    mixer.voices.clear()
                    self.clear_event.clear()
                for _ in range(4):
                    try: samples, pan, generation, stamp = prepared.get_nowait()
                    except queue.Empty: break
                    if generation == self.generation and time.monotonic() - stamp <= 0.25:
                        mixer.add(samples, pan)
                output.write(mixer.block(volume=self.volume))
        except Exception as exc:
            self.silence()
            self.failed(str(exc))
        finally:
            prepare_stop.set()
            if preparer.is_alive(): preparer.join(timeout=0.5)
            if output is not None: output.close()
