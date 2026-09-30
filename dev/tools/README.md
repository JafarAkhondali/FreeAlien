# Measurement tools

How `awcfree_lib/layout.py` was produced. Needs a webcam pointed at the keyboard,
plus `numpy`, `opencv-python` and write access to the lighting controllers.

```bash
python3 dev/tools/map_keys.py --trial    # sanity-check the rig on a few keys
python3 dev/tools/map_keys.py            # light all 92 one at a time -> positions.json
python3 dev/tools/fit_grid.py            # cluster into rows/columns -> grid.json
python3 dev/tools/gen_layout2.py         # write awcfree_lib/layout.py
python3 dev/tools/verify_grid.py         # check the result against the hardware
```

`map_keys.py` assumes `/dev/video4`; change `DEVICE` if the camera differs. Re-run
the whole chain after moving the camera -- `PIXELS` in `layout.py` is tied to one
viewpoint, though `CELLS` (what the canvas uses) is not.

`parse_cap.py` is unrelated to the camera: it reads the USB captures in `tests/fixtures/v3/` and is
a standalone inspection helper. `tests/test_against_captures.py` independently
replays those fixtures.

Run these commands from the repository root. `positions.json`, `grid.json`, and
`wire_order.json` beside the scripts are curated inputs; `gen_layout2.py` rewrites
the runtime layout module. Review generated changes before committing.

`import_sound_packs.py /path/to/downloads` rebuilds bundled recordings using
ffmpeg and 7z. See `CREDITS.md` for sources.
