#!/usr/bin/env python3
"""Offline import of downloaded recordings; ffmpeg is an import-only tool.

Usage: python3 dev/tools/import_sound_packs.py /path/to/downloads
Expected files: farts.wav, gaming.zip, firearms.7z (sources listed below).
No oscillators, pitch shifting or procedural sound generation are used.
"""
from array import array
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave
import zipfile

RATE = 24000
SOURCES = {
    "farts": {"title": "Gastric Distress", "author": "LFA",
              "url": "https://opengameart.org/content/gastric-distress",
              "download": "https://opengameart.org/sites/default/files/gastricdistress_bylfa_0.wav"},
    "gaming": {"title": "Keyboard Soundpack #1", "author": "unicaegames",
               "url": "https://opengameart.org/content/keyboard-soundpack-1-typing-and-single-keystrokes",
               "download": "https://opengameart.org/sites/default/files/unicae_games_keyboard_soundpack_1_0.zip"},
    "guns": {"title": "The Free Firearm Sound Library",
             "author": "Ben Jaszczak, Brian Nelson, Kevin Heras, Matthew Nanney", "uploader": "bart",
             "url": "https://opengameart.org/node/21826",
             "download": "https://opengameart.org/sites/default/files/Prepared%20SFX%20Library.7z"},
}
FIREARMS = {
    "1911/A_42P.wav": ("1911 pistol", "single"),
    "AR-15/D_32P.wav": ("AR-15 rifle", "single"),
    "AK-47/C_28P.wav": ("AK-47 rifle", "single"),
    "Mossberg/N_30P.wav": ("Mossberg shotgun", "shotgun"),
    "Walther PPQ/X_39P.wav": ("Walther PPQ pistol", "single"),
    "AK-47/C_29P.wav": ("AK-47 short burst", "burst"),
    "AK-47/C_27P.wav": ("AK-47 long burst", "burst"),
}


def decode(data, filters=None):
    command = ["ffmpeg", "-v", "error", "-i", "pipe:0"]
    if filters: command.extend(["-af", filters])
    pcm = subprocess.run(command + ["-f", "s16le",
                          "-ac", "1", "-ar", str(RATE), "pipe:1"],
                         input=data, capture_output=True, check=True).stdout
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little": samples.byteswap()
    return samples


def regions(samples, threshold, gap=0.16):
    """Separate recorded performances at quiet gaps, retaining short tails."""
    step = RATE // 100
    active = [max(map(abs, samples[i:i + step]), default=0) >= threshold
              for i in range(0, len(samples), step)]
    spans = []
    start = last = None
    for block, audible in enumerate(active):
        if audible:
            if start is None: start = block
            last = block
        elif start is not None and (block - last) * step >= gap * RATE:
            spans.append((max(0, start * step - 240), min(len(samples), (last + 1) * step + 720)))
            start = last = None
    if start is not None:
        spans.append((max(0, start * step - 240), min(len(samples), (last + 1) * step + 720)))
    return [(a, b) for a, b in spans if b - a >= RATE * .045]


def import_packs(downloads, dest):
    manifest = {"rate": RATE, "packs": {}}
    for pack, source in SOURCES.items():
        filename = {"farts": "farts.wav", "gaming": "gaming.zip", "guns": "firearms.7z"}[pack]
        raw = (downloads / filename).read_bytes()
        source = dict(source, license="CC0-1.0",
                      original_sha256=hashlib.sha256(raw).hexdigest())
        clips = []
        if pack == "farts":
            originals = [("gastricdistress_bylfa_0.wav", raw)]
        elif pack == "guns":
            with tempfile.TemporaryDirectory(prefix="awcfree-firearms-") as extracted:
                members = ["Prepared SFX Library/" + name for name in FIREARMS]
                members.append("Prepared SFX Library/Prepared Master Sheet.csv")
                subprocess.run(["7z", "x", "-y", "-o" + extracted, str(downloads / filename)] + members,
                               check=True, stdout=subprocess.DEVNULL)
                base = Path(extracted) / "Prepared SFX Library"
                originals = [(name, (base / name).read_bytes()) for name in FIREARMS]
                (dest / "guns").mkdir(parents=True, exist_ok=True)
                (dest / "guns/upstream-master-sheet.csv").write_bytes((base / "Prepared Master Sheet.csv").read_bytes())
        else:
            archive = zipfile.ZipFile(downloads / filename)
            originals = [(name, archive.read(name)) for name in sorted(archive.namelist())
                         if name.endswith(".wav") and (pack == "guns" or name.startswith("Single Keys/"))]
            for name in archive.namelist():
                if name.endswith(".txt"):
                    notice = dest / pack / ("upstream-" + Path(name).name)
                    notice.parent.mkdir(parents=True, exist_ok=True)
                    notice.write_bytes(archive.read(name))
        for original, data in originals:
            samples = decode(data, "highpass=f=65" if pack == "guns" else None)
            # Individual keystrokes are already separate assets. Gun/fart files
            # contain multiple performances, separated by recording silence.
            spans = regions(samples, max(map(abs, samples)) * .035 if pack == "guns" else 500 if pack == "farts" else 350,
                            gap=.10 if pack == "farts" else .18)
            if pack == "guns":
                peak = max(map(abs, samples))
                spans = [(a, min(len(samples), b + RATE // 10)) for a, b in spans
                         if max(map(abs, samples[a:b])) > peak * .55]
            if pack == "gaming":
                spans = [(spans[0][0], spans[-1][1])] if spans else []
            for start, end in spans:
                clip = samples[start:end]
                peak = max(map(abs, clip))
                if not peak: continue
                clip = array("h", (round(value / peak * 24000) for value in clip))
                # Fade only the first/last 2ms to avoid trim clicks.
                for i in range(min(48, len(clip) // 2)):
                    clip[i] = round(clip[i] * i / 48)
                    clip[-i - 1] = round(clip[-i - 1] * i / 48)
                path = dest / pack / f"{len(clips):03}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                if sys.byteorder != "little": clip.byteswap()
                with wave.open(str(path), "wb") as output:
                    output.setparams((1, 2, RATE, len(clip), "NONE", "not compressed"))
                    output.writeframes(clip.tobytes())
                clips.append({"file": f"{pack}/{path.name}", "original": original,
                              "start": round(start / RATE, 4), "end": round(end / RATE, 4)})
                if pack == "guns":
                    clips[-1]["weapon"], clips[-1]["kind"] = FIREARMS[original]
        if len(clips) < 2:
            raise ValueError(f"Only {len(clips)} recordings found for {pack}")
        expected = {Path(clip["file"]).name for clip in clips}
        for stale in (dest / pack).glob("*.wav"):
            if stale.name not in expected: stale.unlink()
        source["clips"] = clips
        manifest["packs"][pack] = source
        print(pack, len(clips), "recorded samples")
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    import_packs(Path(sys.argv[1]), Path(__file__).resolve().parents[2] / "awcfree_lib/sounds/assets")
