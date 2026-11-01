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

## Hub (custom frontend)
`frontend/hub/` is a hand-built dashboard over Home Assistant's websocket API (vendored
`home-assistant-js-websocket`, no build step): light orbs in each bulb's live colour, an ambient background
that takes its colours from the lights and the album art, a now-playing card with a beat ring at the
detected tempo, the desk lamp's sun arc and colour-temperature scale, the TV and the Netflix queue.
`homeassistant.apply` copies it into HA's `www` (cache-busted) and registers it as the **Hub** sidebar
dashboard (`/hub-live`); it also works full-screen at `/local/hub/index.html`, e.g. on a wall tablet.
It reuses the HA frontend's login, so there's no separate sign-in.
`.venv/bin/python frontend/screenshot.py /tmp/hub` renders desktop and phone screenshots for review.

## Dashboard, scripts and automations
Home Assistant config that matters is kept here as JSON and pushed with
`.venv/bin/python -m homeassistant.apply`:

- `homeassistant/dashboards/home.json` — the **Home** dashboard (`/home-hub`): a sections view with scene
  buttons, light tiles (brightness + colour temperature), music-sync controls and the TV.
- `homeassistant/scripts/` — Party, Chill, Movie and All off.
- `homeassistant/automations/` — TV bias lighting.

Edit the JSON and re-run apply rather than editing in the UI, so the repo stays the source of truth.

## Adaptive desk lamp
`light.desk_lamp` (the third WiZ bulb) follows the time of day and the light outside, entirely inside Home
Assistant (`homeassistant/templates/`, `homeassistant/automations/desk_lamp_*.json`):

- `sensor.outdoor_daylight` estimates light through the window from sun elevation (0 at -4°, full at 30°),
  cloud cover from `weather.forecast_home` (up to -70%) and rain/fog/snow (a further -20%).
- `sensor.desk_lamp_target_colour`: 4000–5200K in daylight, cooler under overcast skies to match diffuse
  light; ramps to 2700K through sunset, then to 2200K for the 21:00–22:30 wind-down until 05:00.
- `sensor.desk_lamp_target_brightness`: the lamps are the room's only light, so everything is scaled to
  `input_number.desk_lamp_max_brightness` (default 55%): full ceiling in the dark, about a third less on an
  overcast day and ~45% of it on a sunny midday, down to 45% of it for the night wind-down, and capped at
  35% of it whenever the TV is on.
- The automation only adjusts the lamp while it's on (never switches it), and a manual change that's
  clearly off-target starts `timer.desk_lamp_manual`, pausing it for 2 hours. `input_boolean.desk_lamp_adaptive`
  turns the whole thing off.

Music sync never touches it: its MAC is in `WIZ_EXCLUDE_MACS` in `.env`.

## Music sync
`.venv/bin/python -m music_sync` connects to Home Assistant and creates its controls, which appear on the
default dashboard:

| Entity | What it does |
| --- | --- |
| `input_boolean.music_sync` | On/off. Bulbs are restored when it goes off, after 30s of silence, or on the next run after a crash. |
| `input_select.music_sync_mode` | `auto`, `calm`, `party` (chase + strobe on drops), `tv` (see below), `classic` (the original wiz_spotify algorithm). |
| `input_select.music_sync_colours` | `Album art` (palette from the cover of what's playing in the Mac's Spotify) or `Music key` (hue from harmony). Falls back to `Music key` when Spotify isn't playing or the cover has no colour. |
| `input_number.music_sync_sensitivity` | Onset threshold. Raise if lights trigger on noise, lower if they miss beats. |
| `input_number.music_sync_latency` | Fires beats this many ms early to cancel bulb lag. Go negative for Bluetooth speakers. |
| `sensor.music_sync_tempo` | Detected BPM (and whether the beat grid is locked). |
| `sensor.music_sync_now_playing` | Current Spotify track, with the cover as its picture and the extracted palette. |

How it works (`music_sync/analysis.py`, `music_sync/show.py`): 23 ms STFT hops; spectral-flux onsets in
bass/mid/high bands with adaptive thresholds; autocorrelation tempo + comb-filter beat phase + kick PLL, so
locked beats are *predicted* and sent early; hue from a chroma vector on the circle of fifths (it follows
the key); per-band AGC; breakdown→drop detection. Bulbs alternate roles (beat vs. snare/hat sparkle) and
get different hues; updates are rate-limited per bulb and skip no-op changes.

### Album-art colours
`music_sync/nowplaying.py` asks the Spotify app over AppleScript what's playing (no Spotify developer
account needed; it never launches Spotify), and `music_sync/palette.py` runs k-means on the cover, merges
near-identical hues, drops black/grey/white, and keeps up to four colours ranked by coverage × vividness.
Bulbs take different swatches and rotate through them every bar (auto), two bars (calm) or beat (party);
drops advance the palette. The first run asks macOS for permission to control Spotify.

### TV mode
`tv` is bias lighting rather than a show: warm white (2200–2700K, warmer on bass-heavy scenes), 15% brightness,
swelling by at most 8 points over ~3s in loud scenes and settling over ~8s. No RGB colour, beats or flashes.
It listens to the room through the Mac's microphone, so it follows whatever the TV plays from any app
(Netflix, the TV's Spotify, YouTube…). Audio stays in memory; nothing is recorded. It never times out on
silence, since quiet scenes are normal.

The TCL TV is paired through HA's Android TV Remote integration (`media_player.smart_tv_pro`). The
`TV bias lighting` automation (`homeassistant/automations/tv_bias_lighting.json`, pushed by `homeassistant.apply`) switches to `tv` mode when the TV turns on, if music sync
isn't already running, and turns it off (restoring the bulbs) when the TV turns off.

`.venv/bin/python -m tests.test_analysis` checks the pipeline against a synthetic 128 BPM track.
First run triggers macOS system-audio (and, for TV mode, microphone) permission prompts.

## Netflix history
Netflix has no public API, so this reads its official exports:

- **Viewing activity** (netflix.com → Account → profile → Viewing activity → *Download all*): titles and
  dates, instantly. Gives recently watched and the last episode per show.
- **Full data export** (Account → *Download your personal information*, takes days): adds session length and
  the playback position, so the dashboard can show "stopped at 41:20".

`.venv/bin/python -m netflix --watch` picks up the newest export from `~/Downloads` (or `data/netflix/`),
re-checks every 5 minutes, and publishes `sensor.netflix_last_watched`, `sensor.netflix_continue_watching`
and `sensor.netflix_episodes_this_week` for the dashboard's Netflix section. Exports are git-ignored.
Set `NETFLIX_PROFILE` in `.env` to pick a profile from a multi-profile full export.
`.venv/bin/python -m tests.test_netflix` covers both formats and US/UK date order.

## Presence
`.venv/bin/python -m presence` publishes `binary_sensor.someone_home`. You count as home if your phone was
seen on the Wi-Fi in the last 15 min (ping, or the iPhone sync port answering or refusing; its IP is
looked up from `PRESENCE_PHONE_MAC` each cycle) or the Mac was used in the last 10 min. When it turns off,
`Away: everything off` stops music sync and turns off every light, and the TV and desk-lamp automations do
nothing while you're away. If the presence service isn't running the sensor is missing (not `off`), so
nothing is switched off by mistake.
