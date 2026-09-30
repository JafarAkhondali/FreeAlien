"""Sound pack, polyphony and raw-input regression checks without an audio device."""
from array import array
import hashlib
import os
import random
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from awcfree_lib.sounds.packs import (ASSETS, MANIFEST, PACKS, ROLES, VariantPicker,
                                    sound_for_key, variant_count, sample_bank, recording)
from awcfree_lib.sounds.playback import Mixer, SoundEngine
from awcfree_lib.sounds.input import (EvdevDecoder, GlobalKeyboard, INPUT_EVENT, KeyboardDevice,
                                     XInputDecoder, keyboard_devices)


def test_packs_use_distinct_bundled_recordings():
    all_digests = set()
    for pack in PACKS:
        count = variant_count(pack, "normal")
        samples = [sound_for_key(pack, "A", variant) for variant in range(count)]
        digests = {hashlib.sha256(sound.tobytes()).digest() for sound in samples}
        assert len(digests) == count
        assert not all_digests & digests
        all_digests |= digests
        assert all(max(abs(value) for value in sample) <= 0.901 for sample in samples)
        # The played sound is the bundled recording at playback gain, without
        # procedural replacement of its waveform.
        original = recording(pack, sample_bank(pack, "normal")[0])
        assert samples[0] == array("f", (value * .82 for value in original))
        source = MANIFEST["packs"][pack]
        assert source["author"] and source["url"] and source["original_sha256"]
        assert (ASSETS / (source["license"] + ".txt")).is_file()
        for clip in source["clips"]:
            assert (ASSETS / clip["file"]).is_file()
        for role in ROLES:
            assert variant_count(pack, role) >= 2


def test_enter_has_a_longer_accent_in_each_pack():
    for pack in PACKS:
        regular = sound_for_key(pack, "ENTER", 0, accented=False)
        special = sound_for_key(pack, "ENTER", 0, accented=True)
        assert len(special) > len(regular) * 1.5
        assert max(abs(value) for value in special) > max(abs(value) for value in regular)


def test_freedom_mode_uses_recorded_bursts_shotguns_and_pistols_for_special_keys():
    assert PACKS["guns"][0] == "Freedom mode"
    clips = MANIFEST["packs"]["guns"]["clips"]
    assert MANIFEST["packs"]["guns"]["license"] == "CC0-1.0"
    assert {clips[i]["kind"] for i in sample_bank("guns", "enter")} == {"burst"}
    assert {clips[i]["kind"] for i in sample_bank("guns", "space")} == {"shotgun"}
    assert all("pistol" in clips[i]["weapon"] for i in sample_bank("guns", "backspace"))
    assert all(clips[i]["kind"] != "burst" for i in sample_bank("guns", "normal"))


def test_automatic_keyboard_detection_excludes_mice_and_tokens_but_keeps_scroll_keyboards(tmp_path):
    bits = (1 << 30) | (1 << 28) | (1 << 57)
    for event, name, relative in (("event1", "Dell keyboard", "1040"),
                                  ("event2", "Mouse", "3"),
                                  ("event3", "Yubico YubiKey OTP", "0")):
        device = tmp_path / event / "device"
        (device / "capabilities").mkdir(parents=True)
        (device / "name").write_text(name)
        (device / "capabilities/key").write_text(f"{bits:x}")
        (device / "capabilities/rel").write_text(relative)
    assert keyboard_devices(tmp_path) == [KeyboardDevice("/dev/input/event1", "Dell keyboard")]


def test_variations_exhaust_bag_without_adjacent_repeats():
    picker = VariantPicker(random.Random(2))
    count = variant_count("farts", "normal")
    variants = [picker.next("farts", "normal") for _ in range(count * 20)]
    assert all(a != b for a, b in zip(variants, variants[1:]))
    for offset in range(0, len(variants), count):
        assert len(set(variants[offset:offset + count])) == count


def test_mixer_overlaps_saturates_and_removes_finished_voices():
    mixer = Mixer(maximum=3)
    for _ in range(8): mixer.add(array("f", [0.9] * 8), pan=-1)
    assert len(mixer.voices) == 3
    pcm = array("h")
    pcm.frombytes(mixer.block(frames=8, volume=1.0))
    assert pcm[0] == 32767
    assert all(value == 0 for value in pcm[1::2])
    assert not mixer.voices
    assert not any(mixer.block(frames=8))


def test_evdev_fragmented_press_release_repeat_and_drop():
    def event(kind, code, value): return INPUT_EVENT.pack(0, 0, kind, code, value)
    decoder = EvdevDecoder()
    data = event(1, 30, 1) + event(1, 30, 2) + event(1, 30, 0) + event(1, 28, 1)
    assert decoder.feed(data[:5]) == []
    assert decoder.feed(data[5:]) == ["A", "ENTER"]
    assert decoder.feed(event(0, 3, 0) + event(1, 30, 1)) == []
    assert decoder.feed(event(0, 0, 0) + event(1, 57, 1)) == ["SPACE"]


def test_xinput_only_plays_raw_presses_once_until_release():
    decoder = XInputDecoder()
    def event(kind, code=38): return f"EVENT type {kind}\n    detail: {code}\n"
    assert decoder.feed(event("2 (KeyPress)")) == []
    first = event("13 (RawKeyPress)")
    assert decoder.feed(first[:8]) == []
    assert decoder.feed(first[8:]) == ["A"]
    assert decoder.feed(first) == []
    assert decoder.feed(event("14 (RawKeyRelease)")) == []
    assert decoder.feed(first) == ["A"]


def test_keyboard_detection_and_scoped_access_rule():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for event, bits in (("event1", (1 << 30) | (1 << 28) | (1 << 57)), ("event2", 1 << 1)):
            device = root / event / "device"
            (device / "capabilities").mkdir(parents=True)
            (device / "capabilities/key").write_text(f"{bits:x}\n")
            (device / "name").write_text("My keyboard\n")
        devices = keyboard_devices(root, "/dev/input")
        assert devices == [KeyboardDevice("/dev/input/event1", "My keyboard")]
        rule = devices[0].access_rule()
        assert 'ATTRS{name}=="My keyboard"' in rule
        assert 'TAG+="uaccess"' in rule
        assert "MODE" not in rule and "GROUP" not in rule
        try: KeyboardDevice("/dev/input/event1", 'name"*').access_rule()
        except ValueError: pass
        else: raise AssertionError("unsafe rule match accepted")


def test_native_input_notifier_reads_keys_and_releases_device():
    app = QApplication.instance() or QApplication([])
    read_fd, write_fd = os.pipe()
    listener = GlobalKeyboard()
    presses = []
    listener.pressed.connect(presses.append)
    try:
        with patch.object(listener, "uses_x11", return_value=False), \
             patch("awcfree_lib.sounds.input.os.open", return_value=read_fd) as opening:
            listener.start(KeyboardDevice("/dev/input/event3", "Test keyboard"))
            flags = opening.call_args.args[1]
            assert flags & os.O_NONBLOCK
            assert not flags & (os.O_WRONLY | os.O_RDWR)
        os.write(write_fd, INPUT_EVENT.pack(0, 0, 1, 28, 1))
        QTest.qWait(20)
        assert presses == ["ENTER"]
        listener.stop()
        assert listener.fd is None and listener.notifier is None
        app.processEvents()
    finally:
        listener.stop()
        os.close(write_fd)


def test_automatic_native_listener_reads_external_keys_and_keeps_other_keyboards_after_unplug():
    app = QApplication.instance() or QApplication([])
    devices = [KeyboardDevice("/dev/input/event3", "Laptop keyboard"),
               KeyboardDevice("/dev/input/event7", "External keyboard")]
    pipes = [os.pipe(), os.pipe()]
    listener = GlobalKeyboard()
    presses = []
    listener.pressed.connect(presses.append)
    try:
        with patch.object(listener, "uses_x11", return_value=False), \
             patch("awcfree_lib.sounds.input.keyboard_devices", return_value=devices), \
             patch("awcfree_lib.sounds.input.os.open", side_effect=[p[0] for p in pipes]):
            listener.start()
        assert listener.poll.isActive() and len(listener.streams) == 2
        os.write(pipes[1][1], INPUT_EVENT.pack(0, 0, 1, 28, 1))
        QTest.qWait(20)
        assert presses == ["ENTER"]
        os.close(pipes[1][1])
        pipes[1] = (pipes[1][0], None)
        QTest.qWait(20)
        assert len(listener.streams) == 1 and listener.poll.isActive()
        os.write(pipes[0][1], INPUT_EVENT.pack(0, 0, 1, 57, 1))
        QTest.qWait(20)
        assert presses == ["ENTER", "SPACE"]
    finally:
        listener.stop()
        for _, writer in pipes:
            if writer is not None: os.close(writer)
        app.processEvents()


def test_auto_capture_reports_denied_keyboard_and_retries_on_hotplug():
    app = QApplication.instance() or QApplication([])
    devices = [KeyboardDevice("/dev/input/event3", "Laptop"), KeyboardDevice("/dev/input/event7", "External")]
    first, second = os.pipe(), os.pipe()
    listener = GlobalKeyboard()
    try:
        with patch.object(listener, "uses_x11", return_value=False), \
             patch("awcfree_lib.sounds.input.keyboard_devices", return_value=devices), \
             patch("awcfree_lib.sounds.input.os.open", side_effect=[first[0], PermissionError()]):
            listener.start()
        assert len(listener.streams) == 1 and "Access needed: External" in listener.description()
        with patch("awcfree_lib.sounds.input.keyboard_devices", return_value=devices), \
             patch("awcfree_lib.sounds.input.os.open", return_value=second[0]):
            listener._refresh()
        assert len(listener.streams) == 2 and not listener.denied
    finally:
        listener.stop()
        os.close(first[1])
        os.close(second[1])
        app.processEvents()


def test_audio_worker_writes_polyphonic_pcm_and_closes():
    played = threading.Event()
    output = Mock()
    def write(data):
        if any(data): played.set()
        time.sleep(0.003)
    output.write.side_effect = write
    failed = Mock()
    engine = SoundEngine(failed, output_factory=lambda: output)
    try:
        engine.play("gaming", "A", 1)
        engine.play("gaming", "ENTER", 2)
        assert played.wait(2)
        engine.silence()
    finally:
        engine.close()
    failed.assert_not_called()
    output.close.assert_called_once()
    assert not engine.thread.is_alive()


def test_audio_unavailable_reports_error_without_leaving_worker_running():
    failed = threading.Event()
    messages = []
    def unavailable(): raise RuntimeError("No audio server")
    def on_error(message):
        messages.append(message)
        failed.set()
    engine = SoundEngine(on_error, output_factory=unavailable)
    engine.play("guns", "ENTER", 1)
    assert failed.wait(1)
    engine.close()
    assert messages == ["No audio server"]
    assert not engine.thread.is_alive()


def test_missing_recording_reports_error_and_stops_audio_worker():
    failed = threading.Event()
    messages = []
    output = Mock()
    output.write.side_effect = lambda _: time.sleep(.002)
    def on_error(message):
        messages.append(message)
        failed.set()
    engine = SoundEngine(on_error, output_factory=lambda: output)
    with patch("awcfree_lib.sounds.playback.sound_for_key", side_effect=FileNotFoundError("Missing WAV")):
        engine.play("farts", "A", 0)
        assert failed.wait(1)
        engine.close()
    assert messages == ["Could not load keyboard sound: Missing WAV"]
    assert not engine.thread.is_alive()
    output.close.assert_called_once()
