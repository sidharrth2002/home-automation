# home-automation

Home Assistant (Docker) + a native macOS service that syncs WiZ bulbs to system audio.

- `docker-compose.yml` runs Home Assistant on :8123; config lives in `homeassistant/config/` (git-ignored).
- `music_sync/` captures macOS system audio (via the bundled MIT-licensed [audiotee](https://github.com/makeusabrew/audiotee) binary, macOS 14.2+), detects beats, and drives the bulbs over UDP. Beat detection is ported from `wiz_spotify`'s local-audio mode.
- `discover.py` / `lights.py` are small standalone helpers for finding and poking bulbs.

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in TOKEN
docker compose up -d
```
Enable "Allow local communication" in the WiZ app first.

## Music sync
`.venv/bin/python -m music_sync` connects to Home Assistant and creates its controls, which appear on the
default dashboard:

| Entity | What it does |
| --- | --- |
| `input_boolean.music_sync` | On/off. Bulbs are restored when it goes off, after 30s of silence, or on the next run after a crash. |
| `input_select.music_sync_mode` | `auto`, `calm`, `party` (chase + strobe on drops), `classic` (the original wiz_spotify algorithm). |
| `input_number.music_sync_sensitivity` | Onset threshold. Raise if lights trigger on noise, lower if they miss beats. |
| `input_number.music_sync_latency` | Fires beats this many ms early to cancel bulb lag. Go negative for Bluetooth speakers. |
| `sensor.music_sync_tempo` | Detected BPM (and whether the beat grid is locked). |

How it works (`music_sync/analysis.py`, `music_sync/show.py`): 23 ms STFT hops; spectral-flux onsets in
bass/mid/high bands with adaptive thresholds; autocorrelation tempo + comb-filter beat phase + kick PLL, so
locked beats are *predicted* and sent early; hue from a chroma vector on the circle of fifths (it follows
the key); per-band AGC; breakdown→drop detection. Bulbs alternate roles (beat vs. snare/hat sparkle) and
get different hues; updates are rate-limited per bulb and skip no-op changes.

`.venv/bin/python -m tests.test_analysis` checks the pipeline against a synthetic 128 BPM track.
First run triggers a macOS system-audio permission prompt for your terminal.
