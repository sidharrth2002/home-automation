# CLAUDE.md

Working notes for Claude on this repo. Keep this file current: when a change adds or alters a service, command,
convention, entity or gotcha, update it in the same commit as the change (and README.md for anything user-facing).

## What this is

One room in London run by Home Assistant (Docker, on a Mac) plus a few native macOS Python services: three WiZ
bulbs (two by the TV, one adaptive desk lamp), a TCL Google TV, music-reactive lighting, a custom dashboard (the
Hub), an iPhone widget, an Android TV app, investments (Hargreaves Lansdown, Trading 212) and a speaking "Welcome
home". README.md is the human-facing overview; this file is how to work on it safely.

## The rules that matter most

- **The GitHub repo is public.** Never commit `.env`, `data/`, `homeassistant/config/`, logs, APKs, `.shortcut`
  files, screenshots showing personal data, or anything with money amounts, holdings, fund codes, calendar entries,
  addresses, MACs or secret keys/webhook ids. Stage files by path, read `git status` and the diff before every commit.
  `bin/check-commit` is the pre-commit hook (`ln -sf ../../bin/check-commit .git/hooks/pre-commit`); it blocks the
  obvious cases. Never bypass it with `--no-verify`, and never put real figures in tests, even as "secrets".
- **Commit and push after every change** (the user wants GitHub current). Never rewrite history or force-push
  without the user explicitly asking.
- **Services don't reload themselves.** After editing a service's Python, run `./home reload` and check its live
  output (the sensor it publishes, the widget feed...) before saying it works. Tests run on hand-written fixtures and
  can't see a stale process; this once left the widget's bulb taps silently dead.
- **Hargreaves Lansdown locks the account after a few failed logins.** Never loop or retry logins, never delete
  `data/investments/HALTED` yourself, and leave `python -m investments login` for the user to run. To inspect HL
  pages, reuse the saved session and stop if `HL().logged_in()` is false. `tests/test_investments.py` encodes the rules.
  One exception, because nothing has been sent yet: a stage-1 login page that won't load or has no `hl_vt` token
  raises `NotSent` and is tried next round; MAX_NOT_SENT (6) in a row halts. (A bad page right after boot on
  2026-11-14 halted HL for a week.) Anything after stage 1 is posted still halts at once.
  That page was HL's Queue-it waiting room (queue.hl.co.uk): `_get` follows its one JavaScript redirect like a
  browser, which lands back on the real page with a queueittoken unless there's a real queue.
- **Things here are physical.** Lights, the TV and speech happen in the user's room. Test with harmless paths first
  (the `ping` webhook, a neutral phrase), put lamps back exactly as they were after a toggle test, and don't interrupt
  what's playing on the TV unless the user has said it's fine. When the user asks to control the home from chat, just
  do it with `bin/ha`.
- **No Home Assistant token on the phone.** The widget reads a secret-named feed and acts through LAN-only webhooks.

## Layout

```
home                  ./home up | down | restart | reload | status | logs <service>
stack/                supervisor run by ./home: starts, restarts and stops the Mac-side services; publishes sensor.system_health
music_sync/           audio capture -> beat/tempo analysis -> light show; Spotify now-playing and album palettes
announce/             speaks `home_say` events with macOS `say`, on the Mac or cast to the TV
core/                 central state service: SQLite (data/core/core.db) + FastAPI on 127.0.0.1:8790; publishes sensor.investments
skills/home-state/    Claude Code skill (+ stdlib client) other sessions use to read/write core; bin/install-skill
investments/          Hargreaves Lansdown client (hl.py, lockout-safe), FT price history (prices.py), Trading 212 (t212.py)
backlight/            the Bluetooth LED strip behind the cabinet (MELK/ELK-BLEDOM), as light.tv_backlight
photos/               OneDrive photos via Microsoft Graph: picks a few good ones (faces, people, you) for the Hub
widget/               iPhone Scriptable widget (home.js) + its feed, webhook actions and signed Shortcuts (__main__.py)
presence/             phone-on-Wi-Fi home/away (needs PRESENCE_PHONE_MAC; not currently running)
homeassistant/        HA config as code (helpers, templates, scripts, automations, dashboards, voice.json) + apply.py
frontend/hub/         the Hub: plain HTML/CSS/JS on HA's websocket API, no build step; TV mode for the TV app
tv-app/               Android TV app (a full-screen WebView of the Hub); tv-app/deploy builds and installs it
bin/                  ha (REST CLI), check-commit (pre-commit guard), ha-mcp-headers, audiotee
tests/                python -m tests.<name>; node tests/widget_smoke.js
```

## Commands

```sh
./home up | down | reload | status            # everything / just the Mac-side services
.venv/bin/python -m homeassistant.apply       # push helpers, templates, scripts, automations, dashboards, the Hub
bin/ha states <filter>                        # look at entities
bin/ha call light.turn_on light.desk_lamp brightness_pct=30
.venv/bin/python -m tests.test_analysis       # also: test_investments, test_t212, test_widget, test_announce,
                                              #   test_photos, test_backlight
node tests/widget_smoke.js                    # widget script against a strict Scriptable stand-in
HARNESS_FEED=<feed.json> WIDGET_JS=data/widget/Home.js node tests/widget_smoke.js   # which taps a fresh draw gets
.venv/bin/python -m widget install --copy     # widget script with the private addresses filled in, to the clipboard
.venv/bin/python -m widget shortcuts          # signed Shortcuts for the lamps (into data/widget/shortcuts/)
.venv/bin/python -m photos status | once | learn-me <photo>   # the photo frame (runs as a service, every 4h)
tv-app/deploy                                 # build the TV app and install it over adb (TV_HOST in .env)
.venv/bin/python frontend/screenshot.py <out> [selector]   # headless screenshots; HUB_REDACT=1 blurs calendar
```

Edit the JSON under `homeassistant/` and re-run apply rather than changing things in the HA UI; the repo is the
source of truth. The Hub is redeployed by apply (content-hashed, so no stale cache).

TV app buttons (`TV_APPS` in app.js): this TV rejects HA's default `market://launch?id=<package>` app link (HA logs
"Received an error from the device"), so apps open through a link the TV routes to the app. Tested 2026-11-21:
Netflix `https://www.netflix.com/title`, YouTube `https://www.youtube.com`, Prime `https://app.primevideo.com` work;
`spotify://`, `https://www.disneyplus.com`, `https://www.bbc.co.uk/iplayer`, `https://tv.apple.com` don't (still to
find). Testing takes over the TV screen, so ask first.

## Entities and events worth knowing

- Lights: `light.wiz_rgbw_tunable_624d4e` (TV lamp 1), `light.wiz_rgbw_tunable_4b472c` (TV lamp 2), `light.desk_lamp`,
  `light.tv_backlight` ("Cabinet light", the strip behind the cabinet; ids say tv_ because it started behind the TV; a template light over the `tv_backlight` helpers, driven by the backlight service).
  WiZ can't do transitions; fades are steps. Music sync never touches the desk lamp (`WIZ_EXCLUDE_MACS`).
- TV: `media_player.smart_tv_pro` (Android TV Remote: power, keys, apps, volume steps only) and
  `media_player.sid_london_room_tv` (Google Cast: playing media, e.g. speech).
- Music sync: `input_boolean.music_sync`, `input_select.music_sync_mode`, `sensor.music_sync_now_playing`.
- Scripts: party/chill/movie/all_off, `music_command` (play/pause/skip), `welcome_home`, `sleep_mode` (music, TV and
  desk lamp off, then the TV lamps and strip step from a warm glow to dark over ~12 min; mode restart; every other
  scene starts with `script.turn_off script.sleep_mode` so it can't dim them later).
- Events: `home_say` {text, target: mac|tv, voice?, rate?}; `music_sync_command` {command}; `widget_ping`.
- Feeds published by services (REST states, gone after an HA restart until republished): `sensor.investments`,
  `sensor.investment_<sedol>`, `sensor.trading212`, `sensor.system_health`, `sensor.photo_frame` (photos: src, bg, label,
  portrait, people; shown in the Hub's Memories card and the screensaver).

## The core state service

- Design and schema: docs/core.md. Keep it, the README diagram and this section current with every change to core.
- Shared state goes through core, not straight into HA: services write with `core.client` (CORE_TOKEN in .env),
  core publishes to HA. `sensor.investments` is now built by core from every `portfolio/<source>`; the investments
  service sends `portfolio/hl` and `portfolio/t212` snapshots and pauses `hl` on a halt.
- Portfolio writes are snapshots of a source's full state (never edits); manual holdings with units + an ISIN are
  revalued at read time from `fin_prices` (the investments service records FT prices hourly via
  `GET /v1/portfolio/priceable` -> `PUT /v1/prices/<isin>`).
- Schema changes are new entries in `db.MIGRATIONS`, never edits to an applied one. The audit log stores counts, never
  amounts; logs too. The database and its backups are under data/ (git-ignored) and hold real figures: never commit,
  print or paste them. Tests use made-up numbers only.
- Tokens: the admin token is only for this repo's services; anything else gets `python -m core token add <name>
  <scopes>` (scopes are globs over `doc/<collection>/<key>`, `portfolio/<source>`, `price/<instrument>`,
  `live/<entity>`).
- `tests.test_core` covers the API, scopes, snapshots, revaluation, publishing, maintenance, tasks, the agent runner
  and live state (incl. publish retry while HA is down).
- Background work: when the user asks for something to be done in the background ("go investigate…", "process these
  files", "find restaurants…"), queue it with `bin/task run "<prompt>" [--dir <folder>] [--tool …]` and tell them
  the task number; check with `bin/task show <id>`. Agent tasks are headless `claude -p` runs in data/tasks/<id>/
  with read access to their folder and named dirs, web search/fetch, and writes only in their folder; only add
  tools (e.g. Bash) the task really needs. Results (result.md) can be personal: they stay under data/.
- Telemetry: every service calls `telemetry.setup("<name>")` after logging.basicConfig (logs, metrics, traces over
  OTLP to the `telemetry` container; Grafana at localhost:3000, dashboard "Home" from telemetry/grafana/home.json,
  provisioned read-only: edit the JSON, then `docker restart telemetry`). A new service must call it too. Metrics:
  `telemetry.gauge(...)` / `telemetry.meter()`; names start `home.`. Never log amounts or secrets: logs now leave
  the process. Off when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
- Direction: everything goes through core (the FastAPI service); Home Assistant is the device layer and carries
  state to the screens. A service's sensors are reported with `core.client.report(entity, state, attrs)` (table
  `live`, `PUT /v1/live/<entity>`), never POSTed to HA's /api/states: core mirrors them, retries, and re-sends after
  an HA restart. Exceptions: music sync's light frames stay direct UDP (timing); the supervisor posts
  `sensor.system_health` directly (it must work with core down). `core.client.CoreError` is an OSError.
- Premium Bonds (`investments/premium_bonds.py`, the worker's daily `premium-bonds` task): the holder number is
  `PREMIUM_BOND_HOLDER` in .env and goes only to NS&I's public "have I won" endpoint: never into logs, core, the
  sensor, task results or the repo. Never sign in to NS&I or scrape the account. One request per due check (this
  month's draw 3 days after the first working day; unclaimed every 30 days); failures are recorded, not retried,
  and the next daily run tries again. The holding itself is the finance session's `portfolio/nsandi`, read only.

## Gotchas

- HA serves `/local/` with month-long caching: cache-bust with a query string or a new file name.
- The Mac's Spotify app says "playing" while it's only remote-controlling the TV; decide by audio, not that state.
- iOS redraws widgets when it likes; a Scriptable tap always opens Scriptable. Shortcuts (from `widget shortcuts`)
  are the way to act without opening an app.
- Timestamps compared in a browser must carry a timezone (UTC or `astimezone()`).
- Casting to the TV takes over whatever is playing; `welcome_home` only speaks on the TV if it was off.
- The compact `say` voices sound robotic; announce picks Premium/Enhanced voices automatically once downloaded.
- Docker Desktop: don't force-kill it; HA sees LAN clients through Docker's NAT, so per-device trust can't work.
- The TV app: Google TV uses *wireless debugging* (random port, announced over Bonjour), not port 5555. Pairing is a
  one-off (`adb pair <tv>:<pairing port> <code>`; the pairing port can be found with `dns-sd -B _adb-tls-pairing._tcp`
  or a port scan of the TV while the pairing screen is open); after that `tv-app/deploy` finds the connect port itself.
  Debug builds allow WebView inspection: `adb forward tcp:9229 localabstract:webview_devtools_remote_<pid>`, then
  CDP on localhost:9229. `adb exec-out screencap -p` screenshots the TV. A screenshot right after launch can show the
  Hub before its scripts run; wait before concluding it's broken.
- TV GPUs mis-draw heavy effects: `backdrop-filter` and large blurred layers left a card's contents drawn shifted
  after scrolling. TV mode turns them off and paints each card with `contain: paint`; keep new effects out of TV mode
  or test them there (scroll down and back up, then `screencap`).
- Pauses: a locked tempo makes the show fire *predicted* beats, so `Show` stops beating after 0.5 s below
  SILENT_RMS (otherwise a paused song keeps the lights pulsing). On the mic (Spotify on the TV) room noise never goes
  silent and the mic gain rides up to 40×, so while the TV's Cast device (`TV_CAST` in .env) says paused, music sync
  feeds the show zeros and `mic_hops(hold=...)` freezes the gain. `tests.test_analysis` covers the pause.
- TV mode follows daylight: `show.daylight(elevation, clouds)` (sun.sun, `weather.forecast_home` cloud_coverage;
  0 below -6°, 1 from 10° up, halved by full cloud) moves the base from TV_BASE_DIM (15%, night) to TV_DAY_DIM (40%),
  eased over TV_DAY_TAU_S. Nights must stay as subtle as before; unknown sun = night.
- WiZ sockets: every `wizlight(ip)` opens its own UDP socket until `async_close()`, so go through `lights._ask`; and
  `find_wizlights` cancelled mid-wait never closes its socket on port 38899, so it runs under `asyncio.shield`. Both
  leaked until 2026-11-21 (~600 sockets; discovery then failed with "Address already in use" and no mode would start).
- The screensaver (`HubDream`, the Hub with `?ambient=1`) is set with `settings put secure screensaver_components`;
  `tv-app/screensaver on|off|test|status|delay <min>` (the idle delay is `system screen_off_timeout`; the user
  chose 1 minute). The original value is saved once in `data/tv/original-screensaver.txt`
  (Google's `dreamx/.service.Backdrop`). `cmd dreams start-dreaming` needs root and the Somnambulator launcher is
  ignored, so `test` idles into it by briefly shortening `system screen_off_timeout`, always restoring it. A dream can
  start a little after the timeout; check `dumpsys dreams` for `mCurrentDream`. FLAG_KEEP_SCREEN_ON in an app blocks
  the screensaver, which is why the Hub app doesn't use it. The ambient screen must never show finances.
- The cabinet strip (`light.tv_backlight`; apply doesn't rename existing helpers, so they're still "TV backlight …") is Bluetooth only (MELK-OC21, an ELK-BLEDOM-style controller: 9-byte commands to FFF3,
  no replies, one colour for the whole strip). HA in Docker can't reach the Mac's Bluetooth, so `backlight/` holds the
  connection and mirrors the helpers; the controller takes one connection at a time, so its phone app can't connect
  while the service runs. Music sync gives it its own frame in the show (`Lights.outputs`) over UDP 127.0.0.1:38998;
  live frames win, and after 2 s without one it goes back to the helpers. The template light only gets `brightness`
  in set_hs when colour and brightness come together, so set_hs saves the level too. Runs when BACKLIGHT_NAME is set. The Hub's Room card has a calm colour row (six muted presets; hue and white-to-colour sliders under "Custom")
  under the orbs, sending hs_color; brightness is the orb's slider. After a drop, macOS can keep a stale link to the
  strip inside the process (it then stops advertising, so rescans never see it; seen 2026-11-21, 2 h unreachable,
  doing its own effects): after 3 missed scans the service exits and the supervisor restarts it, which clears it.
- Guest photos (`input_boolean.guest_photos`, Hub "Guest" button, voice "guest mode"): the frame shows 30 Wikimedia
  Commons featured landscapes (`photos/guest.py`, face-checked, credited, cached in www/photos-guest) instead of mine,
  on the Hub and the TV screensaver. `sync_frame` runs every 2 s on its own thread (`keep_in_sync`, own Faces), so a
  click shows within seconds even mid-refresh; FRAME_LOCK keeps it and `publish` from posting at once. A refresh while
  it's on saves my new set but doesn't post it. The sensor has a `guest` attribute, and the Hub's slideshow restarts
  when the set changes (guest flag + first src) instead of waiting for its next tick.
- Photos and DNS: originals download from my.microsoftpersonalcontent.com, which macOS's resolver sometimes refuses
  for hours on this DNS64/NAT64 network while the router answers fine, so `graph.py` falls back to `dig`. A failed
  set keeps the old one on screen and logs a warning. `sensor.photo_frame` is set over REST, which HA forgets on
  restart; the watcher re-posts `data/photos/published.json` within a minute when it's gone.
- Photos: OneDrive sign-in is the rclone remote `onedrive` (read-only scopes; `rclone config reconnect onedrive:` if it
  lapses), so no Azure app is needed and it runs on a Pi. Only metadata is listed (Graph delta, cached in
  `data/photos/index.json`). Judging uses ~800px thumbnails (150 new photos per run). Showing uses the originals
  at full resolution (the user asked for that), but only for the 40 in each set (`Graph.original`, via the
  pre-signed downloadUrl, which rejects a bearer token); never clone the library. HEIC is decoded with pillow-heif
  and saved as JPEG (browsers can't show HEIC). The TV gets its own ~2080px copy (`tv` in each entry, used in TV mode):
  decoding 24 MP images every few seconds made Spotify (cast to the TV) stall. Each set avoids the previous one (`index["shown"]`). Judging is local (OpenCV YuNet + SFace; models and the user's face embedding
  `me.npy` live in git-ignored `data/photos/`). The user wants photos of them *with people*: solo selfies (front
  camera, focal length < 3.5mm, one face) and single-face close-ups score 0, and so does anything portrait (the user wants landscape only). Shown copies are re-encoded without
  metadata under random names in `homeassistant/config/www/photos/`. Never commit or screenshot personal photos into
  the repo; for README images use HUB_REDACT or hide `#photos`.
- Hub music card: only shown while there's music (Spotify playing, or sync on in a non-TV mode); otherwise `#music` is
  hidden and `html.no-music` gives the room and scenes the full row (each grid template has a no-music twin). Scene
  tiles never wrap: names ellipsise and narrow tiles drop the subtitle (a container query).
- The screensaver shows a random quote (a curated list in app.js, `QUOTES`; keep attributions accurate), changed
  every ten minutes.
- Hub sections rebuild their HTML whenever an entity they depend on changes. Don't list fast-changing entities (e.g.
  `sensor.music_sync_tempo`, every ~2s during sync) as dependencies of a card with animated parts; update those bits
  in place (as `ambient()` does for the BPM), or animations restart (the progress bar used to redraw from zero).
- TV-mode arrow navigation scrolls just enough to show the focused control, except when the control would fit on
  screen with the page at the very top or bottom, where it scrolls all the way (the header has nothing focusable, so
  it was left cut off).
- README images are public. Take them with `HUB_REDACT=1` (blurs calendar text, including the calendar's "Next"
  line), keep money blurred (the default), never use the user's photo, and look at every image before committing.
- The TV app adds `?app=<timestamp>` when it loads the Hub, because HA caches `/local/` pages for a long time.
- `tv-app/app/src/debug/res/` is a git-ignored overlay for personal resources (the launcher banner with the user's
  photo). The committed banner in `src/main` must stay generic. Personal photos (`*.heic`) are git-ignored and blocked
  by the commit guard.
