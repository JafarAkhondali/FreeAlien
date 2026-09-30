# Recorded keyboard sound packs

These assets are recordings imported from existing libraries, not synthesized
sounds. See `manifest.json` for authors, source/download URLs, original file
names, SHA-256 download hashes, licenses, and trim start/end times.

- `farts/`: Gastric Distress by LFA, CC0 1.0, recorded mouth/hand fart foley.
- `gaming/`: Keyboard Soundpack #1 by unicaegames, CC0 1.0, Cherry KC 1000.
- `guns/` (Freedom mode): The Free Firearm Sound Library by Ben Jaszczak,
  Brian Nelson, Kevin Heras, and Matthew Nanney, CC0 1.0, submitted by bart.
  17 near-distance 1911, AR-15, AK-47, Mossberg, and Walther PPQ recordings,
  including real automatic bursts. The upstream master sheet is preserved.
  Source: https://opengameart.org/node/21826

Edits: split recorded performances at quiet gaps, trim silence, normalize gain,
resample to 24 kHz mono PCM, and apply 2 ms fades at clip boundaries. Gun clips
also use a 65 Hz high-pass filter to reduce low rumble and retain short natural
tails. The GUI
uses longer performances for Enter; its keyboard Enter accent combines two
recorded strikes. No pitch-shifted or procedurally synthesized replacements.

Full license: `CC0-1.0.txt`. Authors' upstream notices and recording metadata are
inside their pack directories. Additional attribution is in `CREDITS.md`.

To reproduce: download the three original files from the URLs in the manifest,
save them as `farts.wav`, `gaming.zip`, `firearms.7z` in a temporary directory, then
run `python3 dev/tools/import_sound_packs.py /path/to/directory` with ffmpeg and 7z installed.
