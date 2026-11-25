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
  Second exception (the user asked, 2026-11-25, after a timeout halted HL for three days): a login the network cut
  off (`refresh`'s catch-all: timeout, dropped connection) halts with `retry_once`, and the service makes ONE
  automatic login RETRY_AFTER_S (30 min) later (`hl.take_retry`, which uses the allowance up before going). If that
  fails too it stays halted for the user; HL rejecting the details never retries; the allowance comes back only
  after a refresh succeeds (`hl.recovered`). The code does this, not you: the rules above still bind you.
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
home_mcp/             the same for Claude Desktop's chat: a stdlib MCP server (stdio) over core with the skill's token
                      (`claude`: doc/portfolio/price/live/media/task/schedule; api_schema + api_request reach any endpoint);
                      bin/install-mcp adds it to claude_desktop_config.json. No MCP SDK: its deps break FastAPI's pins
investments/          Hargreaves Lansdown client (hl.py, lockout-safe), FT price history (prices.py), Trading 212 (t212.py)
backlight/            the Bluetooth LED strip behind the cabinet (MELK/ELK-BLEDOM), as light.tv_backlight
photos/               OneDrive photos via Microsoft Graph: picks a few good ones (faces, people, you) for the Hub
widget/               iPhone Scriptable widget (home.js) + its feed, webhook actions and signed Shortcuts (__main__.py)
presence/             phone-on-Wi-Fi home/away (needs PRESENCE_PHONE_MAC; not currently running)
homeassistant/        HA config as code (helpers, templates, scripts, automations, dashboards, voice.json) + apply.py
frontend/hub/         the Hub: plain HTML/CSS/JS on HA's websocket API, no build step; TV mode for the TV app
tv-app/               Android TV app, native (Kotlin + Compose for TV): the Hub's cards as pages; tv-app/deploy builds and installs it
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
.venv/bin/python -m photos status | once | look | learn-me <photo>   # the photo frame (service every 4h; look = one batch)
tv-app/deploy                                 # build the TV app (release) and install it over adb (TV_HOST in .env)
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
- Music sync: `input_boolean.music_sync`, `input_select.music_sync_mode`, `sensor.music_sync_now_playing`,
  `input_select.music_sync_colours` (default `Music key`: colours follow the music in every mode; `Album art` is
  opt-in, and only then do the Hub's and TV app's ambient glows take the album palette; otherwise they follow the lamps).
- Scripts: party/chill/movie/all_off, `music_command` (play/pause/skip), `welcome_home`, `sleep_mode` (music, TV and
  desk lamp off, then the TV lamps and strip step from a warm glow to dark over ~12 min; mode restart; every other
  scene starts with `script.turn_off script.sleep_mode` so it can't dim them later).
- Events: `home_say` {text, target: mac|tv, voice?, rate?}; `music_sync_command` {command}; `widget_ping`.
- Feeds published by services (REST states, gone after an HA restart until republished): `sensor.investments`,
  `sensor.investment_<sedol>`, `sensor.trading212`, `sensor.system_health`, `sensor.photo_library` (% of the library looked at), `sensor.premium_bonds` (Hub: NS&I group + health tile),
  `sensor.photo_frame` (photos: src, bg, label,
  portrait, people; shown in the Hub's Memories card and the screensaver).

## The core state service

- Design and schema: docs/core.md. Keep it, the README diagram and this section current with every change to core.
- Shared state goes through core, not straight into HA: services write with `core.client` (CORE_TOKEN in .env),
  core publishes to HA. `sensor.investments` is now built by core from every `portfolio/<source>`; the investments
  service sends `portfolio/hl` and `portfolio/t212` snapshots and pauses `hl` on a halt.
- Portfolio writes are snapshots of a source's full state (never edits); manual holdings with units + an ISIN are
  revalued at read time from `fin_prices` (the investments service records FT prices hourly via
  `GET /v1/portfolio/priceable` -> `PUT /v1/prices/<isin>`) and publishes each one's history as
  `sensor.investment_<isin>` (in pence, like HL's) for the Hub's charts. A holding without an ISIN and units (e.g. a
  purchase still settling) has no history until the finance session adds them.
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
  Nothing may call `logging.config.dictConfig` after setup (it flushes the OTel handler under the logging lock:
  a 30 s deadlock); that's why core runs uvicorn with `log_config=None`.
- Exposure: the worker's daily `exposure` task (investments/exposure.py) fetches each held fund's asset allocation,
  regional weightings and sectors from the FT's public holdings page (fund symbols only; refetched after 7 days) into
  core docs `fund_exposure/<holding id>`; core/exposure.py weights them by value (+ savings/Premium Bonds/cash as
  Cash; regions cover shares only) into `sensor.investments` attribute `exposure`. Hub: ranked neutral bars
  (asset class; shares by region) under the chart. FT resolve takes a SEDOL, an ISIN, or searches by name (slugs).
- Hub Investments card: overview + chart (+ exposure) | "Where it is" (allocation bar by account type, then one group per portfolio
  source with its accounts; rate/maturity/"not in total"; Trading 212's interest and the Premium Bonds checks as notes
  under their groups) | holdings (All/per-source tabs, source tag, "Settling" badge). No separate Cash card. Account
  type colours are fixed palette slots (ACCOUNT_TYPES/ALLOC in app.js), consecutive in bar order: re-run the dataviz
  validator if you change them. The merge passes `provider`, `label`, `interest_pct`, `matures` on each account.
- The TV app is native (tv-app/app/src/main/java/com/sid/home): HomeActivity + ui/ (Theme = the Hub's tokens and
  fonts; Home = rail + pages: Home (apps row with All apps / Screensaver / Google TV / Settings tiles, a calm Now panel,
  music, quiet scene tiles), Music (ui/Music.kt; pressing the cover on Home's music card opens it: an additive aurora
  that the bass swells, five ribbons of sound shaped by the mids, dust that glints with the highs; bands come from
  Android's Visualizer FFT on the output mix, session 0, with per-band auto gain; this TCL does share its sound
  (verified 2026-11-22); RECORD_AUDIO, granted by deploy, never the mic; without it a swell on each beat of the Mac's
  tempo drives it. The user called plain rings "shit": keep it rich but calm, nothing strobes), Lights (lamps,
  cabinet colours, Music colours: Music key / Album art), Today, Money, Allocation, Desk & health. The Screensaver
  tile shows ui/Screensaver.kt in the app (photos full screen, clock drifting against burn-in, any key closes):
  SystemUI's Somnambulator exists here but declines to dream when an app asks. `am start -n
  com.sid.home/.HomeActivity --es page MUSIC` opens a page (only when the TV isn't in use). (Keep Home calm: the user found saturated tiles and the lamp controls overstimulating; app
  banners rest dimmed and light up on focus, focus zoom is gentle). The Now panel shows what's next, or with nothing
  left today the photo frame (20 s cross-fade), or with no photos a gentle quote (ui/Comfort.kt, not the Stoic QUOTES); Cards,
  Cards2, Money) over ha/Ha.kt (HA websocket + REST calendars, the same feed as the Hub; Demo for --ez demo true).
  One screen per page, no scrolling; the remote's left arrow opens the rail. Icons and quotes are generated from
  app.js (tv-app/hub_sync.py), the demo household from demo.js (tv-app/demo-data): rerun them after changing those.
  Its own HA token is made once by deploy (tv-app/make_token.py -> data/tv/token, git-ignored). Release builds only
  on the TV (R8, baseline profiles incl. the app's own in src/main/baseline-prof.txt; debug Compose is slow). Test on the TV in demo mode (`am start -n
  com.sid.home/.HomeActivity --ez demo true`): presses in real mode change real things (one moved a real slider).
  `./gradlew :app:recordPaparazziDebug` renders screens with demo data (snapshots are git-ignored). The Home button:
  Google TV ignores the home role and guards its launcher (disabling it left Home dead; never do that), so the app
  has HomeButtonService (accessibility, packageNames = launcherx only): it catches the Home key and opens the Hub
  whenever Google TV's home comes up uninvited (power-on, waking, backing out of an app); the Google TV tile allows it
  (HomeRedirect) until the Hub is back. `tv-app/home on|off|status`. Never `am start -S` (force-stop): Android then
  drops the app's accessibility service from the enabled list (deploy re-enables it if an update drops it).
  The service runs in its own process (`:home_button`): when it shared the Hub's, a Hub crash (a one-colour song
  palette in a gradient, 2026-11-22) killed it too and Android postponed its restart by up to an hour. So HomeRedirect's
  state is files in filesDir, read by both processes; after a Hub crash (HubCrash handler) the service leaves Google
  TV up for 10 min instead of reopening a Hub that crashes on launch. Brushes need 2+ colours: pad data-driven lists.
  Even in its own process the TV's low-memory killer takes it (it kills down to the foreground app when starved); two
  kills close together and Android files it under "Crashed services" and never rebinds it (process alive, `Bound
  services:{}`, accessibility_enabled 0) until it's toggled. So the Mac runs `home_button` (supervised, with TV_HOST
  set): every 30 s over adb, if it's enabled but crashed/unbound, it takes it out of enabled_accessibility_services
  and puts it back. dumpsys lists a bound service by android:label ("Hub Home button"), not class: keep them in step.
- The remote sends a burst of DPAD repeats for all but the shortest press: one press flew past three app tiles. Rows
  of small tiles use `Modifier.oneStepAtATime()` (Components.kt: one left/right move per 180 ms). Not on sliders.
- Open the TV's settings only through `HomeRedirect.openSettings(context[, action])`: Google TV draws them as a side
  panel of its launcher, and without its 10-min hold the Home button service put the Hub straight back over it.
- TV app performance (a weak TCL: 4 slow cores, ~2.4 GB RAM, already swapping; 48% janky frames before 2026-11-22):
  one long-lived `Ctx` over `LiveEntities` (ui/Live.kt: a snapshot state per entity, fed at most 5×/s), so a card
  recomposes only for entities it reads; never build a new Ctx/map per update, and read entities inside the composable
  that shows them. HaClient batches events every 100 ms (one map copy, not one per event). Nothing animates forever at
  60 fps: the ambient glow steps its drift twice a second into one offscreen layer, the Music light draws at 30 fps
  with brushes made once per palette and reads the Visualizer in its frame loop (not composition); both stop under the
  screensaver (`LocalCovered`), which also stops drawing the page under it. Clocks that show minutes update per minute
  (`rememberMinute`). Package manager, disk and decoding stay off the main thread (Banners cache, installed apps,
  the offline photo check, the next photo decoded ahead at the frame's size). The rail is a light custom one (no
  ModalNavigationDrawer: its width animation relaid it out every frame): fixed layout, names/backdrop fade as layers,
  the page follows after 300 ms of rest; 40 dp items fit all eight pages (snapshot `railOpen`). deploy runs `cmd package
  compile -m speed` (an adb install is left at "verify", i.e. interpreted); `dumpsys package com.sid.home | grep -A3
  Dexopt` should say speed. compose-stability.conf marks the JSON/time types stable. Measure with `dumpsys gfxinfo
  com.sid.home reset` / `dumpsys gfxinfo com.sid.home` in demo mode.
- Offline first: ha/Offline.kt. Snapshot keeps the last state on the TV (files/home-state.json, saved every 10 s while
  things change and on onStop; not "after quiet": HA is never quiet) and loads it at start; OfflineQueue applies
  presses at once and sends them on reconnect (before get_states): latest wish per entity, toggles stored as
  turn_on/off, older than 15 min dropped, scripts/remote/media not queued (a toast says so). PhotoCache keeps the
  frame's photos in Coil's disk cache; offline the frame only uses cached ones, else the comfort quote. The header
  chip says "Offline · last update HH:MM · N changes waiting". Calendars keep the last week if unreachable. Settings
  page (ui/Settings.kt): guest mode, music sync, TV glow, desk lamp follows the sky, away automation, hide amounts,
  Home button status, connection. Unit tests: OfflineQueueTest (./gradlew :app:testDebugUnitTest). The ambient glow layers are drawn past the screen
  edges because they drift (a screen-sized layer showed its edge sliding in).
  Switching it on needs the user (Android's restricted settings for sideloaded apps), and this TCL TV's firmware also
  refuses to start it ("[TclAppBoot]: forbid bind service" in logcat) until the app is allowed to auto-start in TCL's
  guard app (com.tcl.guard), which only the user can change. Android string resources need apostrophes escaped (\'):
  an unescaped one fails the resource merge, and a filter on "^e:" hides that error; check the APK's timestamp. No WebView
  is left in the app (MainActivity and Hub.java removed 2026-11-22): don't bring one back, Chromium in-process costs
  hundreds of MB on this TV.
- Calm by default, in every UI: the user is easily overstimulated. Low saturation (dark surfaces; colour only as small
  accents, like a tinted icon or a soft outline on the active item), little motion (slow and subtle at most; no
  pulsing, flashing or big focus zooms), few things per screen (secondary controls on their own page). Prefer removing
  to adding; check new UI against this before showing it.
- Keep every UI in sync, in the same PR: the Hub (desktop + phone), the TV app's TV layout (`?tv=1`, 1280 canvas;
  every new control must be reachable with the remote's arrows: they're buttons, so FOCUSABLE picks them up, but
  check) and screensaver (`?ambient=1`), the iPhone widget where it applies, and the README pictures (demo mode,
  `frontend/readme_images.py`). Deploy with `homeassistant.apply` (the TV app loads the Hub fresh each launch);
  rebuild the app with `tv-app/deploy` when tv-app/ changes, or `tv-app/deploy --no-open` when the TV is off or in
  use (never launch it over something playing). Check demo screenshots of each.
- Direction: everything goes through core (the FastAPI service); Home Assistant is the device layer and carries
  state to the screens. A service's sensors are reported with `core.client.report(entity, state, attrs)` (table
  `live`, `PUT /v1/live/<entity>`), never POSTed to HA's /api/states: core mirrors them, retries, and re-sends after
  an HA restart. Exceptions: music sync's light frames stay direct UDP (timing); the supervisor posts
  `sensor.system_health` directly (it must work with core down). `core.client.CoreError` is an OSError.
- Premium Bonds (`investments/premium_bonds.py`, the worker's daily `premium-bonds` task): the holder number is
  in the core only (doc `finance/premium_bonds_holder` `{"holder"}`, set by the finance session via the MCP tool
  `set_premium_bonds_holder` or the skill; writing it queues a check at once via core REACTIONS). It's sent only to
  NS&I's public "have I won" endpoint: never into logs, the sensor, task results or the repo. Never sign in to NS&I or scrape the account. One request per due check (this
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
  `adb exec-out screencap -p` screenshots the TV.
- TV app memory (2.4 GB TV, 192 MB heap limit): measure with `dumpsys meminfo com.sid.home` while it's in front (in
  the background the TV has already squeezed it), or the history in `logcat -b events | grep am_pss`; `killinfo`
  lines are lmkd kills (pid, uid, oom_adj, …, rss KB). Normal foreground is ~85-130 MB PSS. The WebView screensaver
  took it to 515-562 MB RSS within minutes, and lmkd killed down to adj 0. Coil's memory cache is capped at 24 MB
  (HomeApp.start); prefetches that only want the disk cache decode at 16×16.
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
- The screensaver (`HubDream`: a DreamService hosting the native `Screensaver` composable in a ComposeView, acting
  as its own LifecycleOwner/SavedStateRegistryOwner) is set with `settings put secure screensaver_components`;
  `tv-app/screensaver on|off|test|status|delay <min>` (the idle delay is `system screen_off_timeout`; the user
  chose 1 minute). The original value is saved once in `data/tv/original-screensaver.txt`
  (Google's `dreamx/.service.Backdrop`). `cmd dreams start-dreaming` needs root and the Somnambulator launcher is
  ignored, so `test` idles into it by briefly shortening `system screen_off_timeout`, always restoring it. A dream can
  start a little after the timeout; check `dumpsys dreams` for `mCurrentDream`. FLAG_KEEP_SCREEN_ON in an app blocks
  the screensaver, which is why the Hub app doesn't use it. The ambient screen must never show finances.
- The cabinet strip (`light.tv_backlight`; apply doesn't rename existing helpers, so they're still "TV backlight …") is Bluetooth only (MELK-OC21, an ELK-BLEDOM-style controller: 9-byte commands to FFF3,
  no replies, one colour for the whole strip). HA in Docker can't reach the Mac's Bluetooth, so `backlight/` holds the
  connection and mirrors the helpers; the controller takes one connection at a time (the user has no phone app for it:
  this service is its only client). An idle link can die silently (it did overnight), so with nothing to send the
  service re-sends the power state every KEEPALIVE_S (45 s): a dead link then fails in the background and reconnects
  before anyone presses anything. Music sync gives it its own frame in the show (`Lights.outputs`) over UDP 127.0.0.1:38998;
  the latest intent wins: a show that starts takes the strip (even if it was off), switching it off during a show takes
  it out of that show until it's switched on again or a new show starts; after 2 s without frames it goes back to the helpers. The template light only gets `brightness`
  in set_hs when colour and brightness come together, so set_hs saves the level too. Runs when BACKLIGHT_NAME is set. The Hub's Room card has a calm colour row (six muted presets; hue and white-to-colour sliders under "Custom")
  under the orbs, sending hs_color; brightness is the orb's slider. After a drop, macOS keeps a stale link to the
  strip inside the process: rescans from it never find the strip again (9 drops of 9, 2026-11-13 to 22; once 2 h
  unreachable), while a fresh process connects within a second every time. So a link that drops is never rescanned:
  the service exits at once (`FreshStart`) and the supervisor restarts it, back in ~3 s. Scans from a fresh start get
  3 tries (the strip may really be off). Drops often line up with music sync starting or stopping; cause unknown.
- Guest photos (`input_boolean.guest_photos`, Hub "Guest" button, voice "guest mode"): the frame shows 30 Wikimedia
  Commons featured landscapes (`photos/guest.py`, face-checked, credited, cached in www/photos-guest) instead of mine,
  on the Hub and the TV screensaver. `sync_frame` runs every 2 s on its own thread (`keep_in_sync`, own Faces), so a
  click shows within seconds even mid-refresh; FRAME_LOCK keeps it and `publish` from posting at once. A refresh while
  it's on saves my new set but doesn't post it. `sync_frame` reads the switch with `guest_switch()`, which raises while
  it's unknown (HA unreachable or restarting): it skips that tick rather than swap the frame on a guess. The sensor has a `guest` attribute, and the Hub's slideshow restarts
  when the set changes (guest flag + first src) instead of waiting for its next tick.
- Photos and DNS: originals download from my.microsoftpersonalcontent.com, which macOS's resolver sometimes refuses
  for hours on this DNS64/NAT64 network while the router answers fine, so `graph.py` falls back to `dig`. A failed
  set keeps the old one on screen and logs a warning. `sensor.photo_frame` goes through core (live state), which
  re-sends it after an HA restart; `data/photos/published.json` is my set, put back when guest mode ends.
- OneDrive must never be changed (the user's whole photo library). Layers: the rclone remote's `access_scopes` are
  read-only (Files.Read, Files.Read.All, Sites.Read.All, offline_access), so Microsoft refuses any write; graph.py
  only makes GETs and only `rclone about` / `config dump|show` run (tests.test_photos `read_only()` enforces both);
  nothing references the local sync folders (~/Library/CloudStorage/OneDrive-*), which mirror deletions to the cloud;
  agent tasks always get `--disallowedTools` AGENT_DENY (rclone, rm, writes under CloudStorage, reading rclone.conf).
  Never re-authorise rclone with wider scopes, and never point a task with a shell at the sync folder.
- Photos: OneDrive sign-in is the rclone remote `onedrive` (read-only scopes; `rclone config reconnect onedrive:` if it
  lapses), so no Azure app is needed and it runs on a Pi. Only metadata is listed (Graph delta every 4h; the
  index lives in core's `media` tables, /v1/media/onedrive, not a JSON file). Judging uses ~800px thumbnails: the
  worker's `photos-look` task, hourly, 150 a run, results saved every 25 as analyser `faces`. Showing uses the originals
  at full resolution (the user asked for that), but only for the 40 in each set (`Graph.original`, via the
  pre-signed downloadUrl, which rejects a bearer token); never clone the library. HEIC is decoded with pillow-heif
  and saved as JPEG (browsers can't show HEIC). The TV gets its own ~2080px copy (`tv` in each entry, used in TV mode):
  decoding 24 MP images every few seconds made Spotify (cast to the TV) stall. Each set avoids the previous one (`media_shown`). Judging is local (OpenCV YuNet + SFace; models and the user's face embedding
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
- README images are public and come only from the Hub's demo mode (`?demo=1`, frontend/hub/demo.js: invented
  portfolio, calendar, tasks and track; no HA connection; controls do nothing; money starts hidden, so the pictures
  never show amounts, even invented ones): `.venv/bin/python
  frontend/readme_images.py` rebuilds docs/hero.jpg, hub.jpg, hub-money.jpg, hub-health.jpg and tv.jpg. Never put a
  screenshot of the real Hub in the repo. When the Hub gains a card or the README a section, extend demo.js and
  rerun it. Look at every image before committing. The README's look: docs/banner.svg (animated, CSS, honours
  reduced motion), feature icons in docs/icons/ (the Hub's own icon paths on gradient tiles).
- The TV app adds `?app=<timestamp>` when it loads the Hub, because HA caches `/local/` pages for a long time.
- `tv-app/app/src/debug/res/` is a git-ignored overlay for personal resources (the launcher banner with the user's
  photo). The committed banner in `src/main` must stay generic. Personal photos (`*.heic`) are git-ignored and blocked
  by the commit guard.
