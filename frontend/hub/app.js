// Home hub: a live view over Home Assistant's websocket API.
// Reuses the HA frontend's login (same origin, `hassTokens` in localStorage); falls back to HA's OAuth.
import { callService, createConnection, getAuth, subscribeEntities } from "./vendor/haws.js";

const LIGHTS = [
  { id: "light.wiz_rgbw_tunable_624d4e", name: "TV lamp", tag: "TV · 1" },
  { id: "light.desk_lamp", name: "Desk lamp", tag: "Desk" },
  { id: "light.wiz_rgbw_tunable_4b472c", name: "TV lamp", tag: "TV · 2" },
];
const DESK = "light.desk_lamp";
const SYNC = "input_boolean.music_sync";
const MODE = "input_select.music_sync_mode";
const COLOURS = "input_select.music_sync_colours";
const SENS = "input_number.music_sync_sensitivity";
const LAT = "input_number.music_sync_latency";
const TEMPO = "sensor.music_sync_tempo";
const NOW = "sensor.music_sync_now_playing";
const HOME = "binary_sensor.someone_home";
const WEATHER = "weather.forecast_home";
const SUN = "sun.sun";
const OUTDOOR = "sensor.outdoor_daylight";
const T_K = "sensor.desk_lamp_target_colour";
const T_B = "sensor.desk_lamp_target_brightness";
const ADAPT = "input_boolean.desk_lamp_adaptive";
const HOLD = "timer.desk_lamp_manual";
const MAXB = "input_number.desk_lamp_max_brightness";
const TV = "media_player.smart_tv_pro";
const TV_AUTO = "automation.tv_bias_lighting";
const TV_REMOTE = "remote.smart_tv_pro";
const HEALTH = "sensor.system_health";
const INVEST = "sensor.investments";
const T212 = "sensor.trading212";

const APPS = {
  "com.netflix.ninja": ["Netflix", "229,9,20"],
  "com.google.android.youtube.tv": ["YouTube", "255,40,60"],
  "com.google.android.youtube.tvkids": ["YouTube Kids", "255,40,60"],
  "com.spotify.tv.android": ["Spotify", "30,215,96"],
  "com.amazon.amazonvideo.livingroom": ["Prime Video", "0,168,225"],
  "com.disney.disneyplus": ["Disney+", "60,110,255"],
  "uk.co.bbc.iplayer": ["BBC iPlayer", "255,79,163"],
  "com.apple.atve.androidtv.appletv": ["Apple TV", "220,220,230"],
  "com.google.android.apps.tv.launcherx": ["Home screen", "150,150,190"],
  "com.google.android.tvlauncher": ["Home screen", "150,150,190"],
};

// ── icons (24px, stroked) ─────────────────────────────────────────
const svg = (body, extra = "") =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${body}</svg>`;
const CLOUD = `<path d="M7 17h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.1 8.5 4.25 4.25 0 0 0 7 17z"/>`;
const I = {
  sun: svg(`<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>`),
  moon: svg(`<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>`),
  cloud: svg(CLOUD),
  partly: svg(`<path d="M8 3.5v1M3.5 8h1M4.8 4.8l.7.7M11.2 4.8l-.7.7"/><path d="M5.6 10.4A3 3 0 1 1 10.7 7"/>` + `<path d="M9 19h8a3.5 3.5 0 0 0 .5-6.96A5 5 0 0 0 8 11.2 3.9 3.9 0 0 0 9 19z"/>`),
  rain: svg(`<g transform="translate(0 -2)">${CLOUD}</g><path d="M9 18.5l-1 2.5M13 18.5l-1 2.5M17 18.5l-1 2.5"/>`),
  fog: svg(`<path d="M4 9h16M3 13h18M5 17h14"/>`),
  snow: svg(`<g transform="translate(0 -2)">${CLOUD}</g><path d="M9 20h.01M13 21h.01M17 20h.01"/>`),
  storm: svg(`<g transform="translate(0 -2)">${CLOUD}</g><path d="M12 15l-2 4h3l-2 4"/>`),
  tv: svg(`<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>`),
  music: svg(`<path d="M9 18V6l11-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>`),
  power: svg(`<path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/>`),
  party: svg(`<path d="M11 3l1.8 4.7 4.7 1.8-4.7 1.8L11 16l-1.8-4.7L4.5 9.5l4.7-1.8z"/><path d="M18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>`),
  chill: svg(`<path d="M2 12c2.5-3 5-3 7.5 0s5 3 7.5 0 3.5-3 5 0"/><path d="M2 17c2.5-3 5-3 7.5 0s5 3 7.5 0 3.5-3 5 0"/><path d="M2 7c2.5-3 5-3 7.5 0s5 3 7.5 0 3.5-3 5 0"/>`),
  film: svg(`<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>`),
  home: svg(`<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>`),
  away: svg(`<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/>`),
  lamp: svg(`<path d="M8 3h8l3 8H5z"/><path d="M12 11v8M8 21h8"/>`),
  prev: svg(`<path d="M18 6v12L9 12z" fill="currentColor"/><path d="M6 6v12"/>`),
  next: svg(`<path d="M6 6v12l9-6z" fill="currentColor"/><path d="M18 6v12"/>`),
  play: svg(`<path d="M8 5.5v13l11-6.5z" fill="currentColor"/>`),
  pause: svg(`<rect x="7" y="5.5" width="3.2" height="13" rx="1" fill="currentColor"/><rect x="13.8" y="5.5" width="3.2" height="13" rx="1" fill="currentColor"/>`),
  pin: svg(`<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>`),
  repeat: svg(`<path d="M17 2l3 3-3 3"/><path d="M4 11V9a4 4 0 0 1 4-4h12M7 22l-3-3 3-3"/><path d="M20 13v2a4 4 0 0 1-4 4H4"/>`),
  notes: svg(`<path d="M5 4h14v16H5z"/><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4"/>`),
  up: svg(`<path d="M6 15l6-6 6 6"/>`), down: svg(`<path d="M6 9l6 6 6-6"/>`),
  left: svg(`<path d="M15 6l-6 6 6 6"/>`), right: svg(`<path d="M9 6l6 6-6 6"/>`),
  back: svg(`<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>`),
  plus: svg(`<path d="M12 5v14M5 12h14"/>`), minus: svg(`<path d="M5 12h14"/>`),
  mute: svg(`<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M16 9l5 6M21 9l-5 6"/>`),
  speaker: svg(`<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>`),
  pulse: svg(`<path d="M3 12h4l2-6 4 12 2-6h6"/>`),
  reactor: svg(`<circle cx="12" cy="12" r="9.2"/><circle cx="12" cy="12" r="5.2"/><circle cx="12" cy="12" r="1.9" fill="currentColor"/><path d="M12 2.8v3.2M12 18v3.2M4 7.4l2.8 1.6M17.2 15l2.8 1.6M4 16.6l2.8-1.6M17.2 9l2.8-1.6"/>`),
  piggy: svg(`<path d="M19 11c0-3.3-3.1-6-7-6S5 7.7 5 11c0 1.6.7 3 1.9 4.1V18h3v-1.2c.7.1 1.4.2 2.1.2s1.4-.1 2.1-.2V18h3v-2.9c.6-.5 1.1-1 1.5-1.6H21v-3h-2z"/><circle cx="15.5" cy="10.5" r=".6" fill="currentColor"/><path d="M9 7.5c.8-.9 2-1.2 3.2-1"/>`),
  chart: svg(`<path d="M3 17l5-5 4 3 8-8"/><path d="M15 7h5v5"/>`),
  eye: svg(`<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>`),
  eyeOff: svg(`<path d="M3 3l18 18"/><path d="M10.6 5.1A10.6 10.6 0 0 1 12 5c6.4 0 10 7 10 7a17.7 17.7 0 0 1-3.2 4.2M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7a9.8 9.8 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>`),
  cal: svg(`<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>`),
  bulb: svg(`<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>`),
};
const WEATHER_ICON = {
  "sunny": [I.sun, "Sunny"], "clear-night": [I.moon, "Clear"], "partlycloudy": [I.partly, "Partly cloudy"],
  "cloudy": [I.cloud, "Cloudy"], "fog": [I.fog, "Fog"], "rainy": [I.rain, "Rain"], "pouring": [I.rain, "Heavy rain"],
  "snowy": [I.snow, "Snow"], "snowy-rainy": [I.snow, "Sleet"], "lightning": [I.storm, "Thunder"],
  "lightning-rainy": [I.storm, "Thunderstorms"], "hail": [I.snow, "Hail"], "windy": [I.fog, "Windy"],
  "windy-variant": [I.cloud, "Windy"], "exceptional": [I.storm, "Severe"],
};

// ── state + helpers ───────────────────────────────────────────────
let S = {};
let conn;
const $ = (sel) => document.querySelector(sel);
const st = (id) => S[id]?.state;
const at = (id, k) => S[id]?.attributes?.[k];
const is = (id, v) => st(id) === v;
const num = (id, d = NaN) => (Number.isFinite(parseFloat(st(id))) ? parseFloat(st(id)) : d);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pctOf = (e) => Math.round(((e?.attributes?.brightness ?? 0) / 255) * 100);

function kelvinToRgb(k) {
  const t = clamp(k, 1000, 40000) / 100;
  const r = t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -0.1332047592);
  const g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * Math.pow(t - 60, -0.0755148492);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  return [r, g, b].map((v) => Math.round(clamp(v, 0, 255)));
}
const rgbOf = (e) => e?.attributes?.rgb_color ?? (e?.attributes?.color_temp_kelvin ? kelvinToRgb(e.attributes.color_temp_kelvin) : [255, 196, 140]);
const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const hueOf = (s) => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

async function call(domain, service, data) {
  try {
    await callService(conn, domain, service, data);
  } catch (err) {
    toast(`Couldn't ${service.replace(/_/g, " ")}: ${err?.message || err?.code || "error"}`);
  }
}
let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

// ── sections: re-render only when their entities change, never mid-drag ──
const busy = new Set();
const lastSig = {};
const sections = [];
function section(sel, deps, render) {
  sections.push({ sel, deps, render });
}
function renderAll(force = false) {
  for (const { sel, deps, render } of sections) {
    if (busy.has(sel)) continue;
    const sig = JSON.stringify(deps().map((id) => (S[id] ? [S[id].state, S[id].attributes] : null)));
    if (!force && sig === lastSig[sel]) continue;
    lastSig[sel] = sig;
    $(sel).innerHTML = render();
    if (sel === "#invest") renderHolding(); // keep an open holding in step with fresh data
  }
  ambient();
  tick();
}

// header chips
section("#chips", () => [HOME, WEATHER, OUTDOOR], () => {
  const home = st(HOME);
  const presence = home === "on" ? `<span class="chip"><span class="dot ok"></span><b>Home</b></span>`
    : home === "off" ? `<span class="chip"><span class="dot bad"></span><b>Away</b> · all off</span>`
    : `<span class="chip"><span class="dot"></span>Presence off</span>`;
  const [icon, label] = WEATHER_ICON[st(WEATHER)] ?? [I.cloud, st(WEATHER) ?? "—"];
  const temp = at(WEATHER, "temperature");
  const weather = S[WEATHER] ? `<span class="chip">${icon}<b>${Math.round(temp)}°</b> ${esc(label)}</span>` : "";
  const out = S[OUTDOOR] ? `<span class="chip">${I.sun}Outside <b>${st(OUTDOOR)}%</b></span>` : "";
  return presence + weather + out;
});

// room: one glowing orb per bulb
section("#room", () => [...LIGHTS.map((l) => l.id), SYNC, MODE], () => {
  const on = LIGHTS.filter((l) => is(l.id, "on")).length;
  const sync = is(SYNC, "on");
  const orbs = LIGHTS.map((l) => {
    const e = S[l.id];
    const lit = e?.state === "on";
    const rgb = lit ? rgbOf(e) : [255, 255, 255];
    const pct = lit ? pctOf(e) : 0;
    const k = e?.attributes?.color_mode === "color_temp" ? `${e.attributes.color_temp_kelvin}K` : "colour";
    const meta = !e ? "Unavailable" : lit ? `${pct}% · ${k}` : "Off";
    const syncing = lit && sync && l.id !== DESK;
    return `
      <div class="light ${lit ? "on" : "off"} ${syncing ? "syncing" : ""}" style="--c:${rgb.join(",")};--b:${(pct / 100).toFixed(2)}">
        <span class="light-tag">${l.tag}${syncing ? " · live" : ""}</span>
        <button class="orb" data-act="light" data-id="${l.id}" aria-label="Toggle ${l.name}" aria-pressed="${lit}">
          <span class="halo"></span><span class="ring"></span><span class="core"></span>
        </button>
        <div><div class="light-name">${l.name}</div><div class="light-meta">${meta}</div></div>
        <input class="slider" type="range" min="1" max="100" value="${pct || 1}" ${lit ? "" : "disabled"}
               data-act="bri" data-id="${l.id}" aria-label="${l.name} brightness"
               style="--p:${pct}%;--fill:rgb(${rgb.join(",")})">
      </div>`;
  }).join("");
  return `
    <div class="card-head"><div class="card-title">${I.bulb} Room</div>
      <span class="kicker">${on ? `${on} of ${LIGHTS.length} on` : "All dark"}${sync ? ` · ${esc(st(MODE))} sync` : ""}</span></div>
    <div class="orbs">${orbs}</div>`;
});

// scenes
section("#scenes", () => [SYNC, MODE, ...LIGHTS.map((l) => l.id)], () => {
  const sync = is(SYNC, "on");
  const mode = st(MODE);
  const dark = LIGHTS.every((l) => !is(l.id, "on"));
  return [
    ["welcome_home", "Welcome home", "Lights, TV, hello", I.reactor, "linear-gradient(135deg,#00e5ff,#0077ff 55%,#001b4d)", "#00d4ff", false, "hero"],
    ["party_mode", "Party", "Beat-locked colour", I.party, "linear-gradient(135deg,#ff3cac,#784ba0 55%,#2b86c5)", "#ff3cac", sync && mode === "party"],
    ["chill_mode", "Chill", "Gentle music glow", I.chill, "linear-gradient(135deg,#2af598,#009efd)", "#2af598", sync && mode === "calm"],
    ["movie_mode", "Movie", "Subtle TV glow", I.film, "linear-gradient(135deg,#f6d365,#fda085)", "#fda085", sync && mode === "tv"],
    ["all_off", "All off", "Everything dark", I.power, "linear-gradient(135deg,#3a3a48,#08080c)", "#9a9ab0", dark],
  ].map(([id, name, sub, icon, g, glow, active, cls = ""]) => `
    <button class="scene ${cls}" data-act="script" data-id="script.${id}" aria-pressed="${active}" style="--g:${g};--glow:${glow}">
      ${icon}<div><b>${name}</b><small>${sub}</small></div>
    </button>`).join("");
});

// music sync + now playing
let tuneOpen = false;
section("#music", () => [SYNC, MODE, COLOURS, SENS, LAT, TEMPO, NOW, TV], () => {
  const sync = is(SYNC, "on");
  const mode = st(MODE);
  const [title, artist] = String(st(NOW) ?? "").split(" — ");
  const playing = at(NOW, "player_state") === "playing";
  const art = at(NOW, "entity_picture");
  const palette = at(NOW, "palette") ?? [];
  const bpm = parseFloat(st(TEMPO));
  const locked = at(TEMPO, "locked");
  const modes = at(MODE, "options") ?? ["auto", "calm", "party", "tv", "classic"];
  const colours = at(COLOURS, "options") ?? ["Album art", "Music key"];
  const nothing = !title || title === "Nothing playing";
  const sens = num(SENS, 1.35);
  const lat = num(LAT, 60);
  const sub = nothing ? "Spotify isn't playing" : `${esc(artist ?? "")}${playing ? "" : " · paused"}`;
  const dur = Number(at(NOW, "media_duration")) || 0;
  // Transport goes to the Mac's Spotify, or the TV when Spotify isn't open (see the music_command script).
  const controls = !nothing || is(TV, "on");
  const progress = !nothing && dur > 0 ? `
    <div class="progress" data-pos="${Number(at(NOW, "media_position")) || 0}" data-at="${Number(at(NOW, "media_position_updated_at")) || 0}"
         data-dur="${dur}" data-playing="${playing}">
      <div class="bar"><i></i></div>
      <div class="times"><span class="t-pos">0:00</span><span class="t-left">-${fmtTime(dur)}</span></div></div>` : "";
  const transport = controls ? `
    <div class="transport">
      <button data-act="music" data-v="previous" aria-label="Previous track">${I.prev}</button>
      <button class="pp" data-act="music" data-v="play_pause" aria-label="${playing ? "Pause" : "Play"}">${playing ? I.pause : I.play}</button>
      <button data-act="music" data-v="next" aria-label="Next track">${I.next}</button>
    </div>` : "";
  return `
    ${art ? `<div class="backdrop" style="background-image:url('${esc(art)}')"></div>` : ""}
    <div class="card-head"><div class="card-title">${I.music} Music sync</div>
      <button class="switch" role="switch" aria-checked="${sync}" data-act="toggle" data-id="${SYNC}" aria-label="Music sync"></button></div>
    <div class="art-wrap"><i class="pulse"></i><i class="pulse p2"></i>
      <div class="art ${art ? "" : "empty"}" ${art ? `style="background-image:url('${esc(art)}')"` : ""}>${art ? "" : I.music}</div></div>
    <div class="track"><h2>${esc(nothing ? "Nothing playing" : title)}</h2><p>${sub}</p>
      <div class="swatches">${palette.map((h) => `<i style="background:${esc(h)};color:${esc(h)}" title="${esc(h)}"></i>`).join("")}</div></div>
    ${progress}${transport}
    <div class="row"><span class="kicker">Mode</span>
      <span class="bpm">${Number.isFinite(bpm) ? `<b>${Math.round(bpm)}</b> BPM${locked ? " · locked" : ""}` : sync ? "finding the beat…" : "idle"}</span></div>
    <div class="seg">${modes.map((m) => `<button data-act="select" data-id="${MODE}" data-v="${esc(m)}" aria-pressed="${m === mode}">${m === "tv" ? "TV" : esc(m)}</button>`).join("")}</div>
    <div class="row"><span class="kicker">Colours</span>
      <div class="seg" style="flex:1;max-width:260px">${colours.map((c) => `<button data-act="select" data-id="${COLOURS}" data-v="${esc(c)}" aria-pressed="${c === st(COLOURS)}">${esc(c)}</button>`).join("")}</div></div>
    <details class="tune" ${tuneOpen ? "open" : ""}><summary>Fine-tune</summary>
      <div class="row"><span class="label">Sensitivity</span>
        <input class="slider" type="range" min="1" max="2.5" step="0.05" value="${sens}" data-act="number" data-id="${SENS}" data-unit="" style="--p:${((sens - 1) / 1.5) * 100}%">
        <span class="value">${sens.toFixed(2)}</span></div>
      <div class="row"><span class="label">Latency</span>
        <input class="slider" type="range" min="-200" max="300" step="10" value="${lat}" data-act="number" data-id="${LAT}" data-unit=" ms" style="--p:${((lat + 200) / 500) * 100}%">
        <span class="value">${lat} ms</span></div>
    </details>`;
});

// calendar: the week ahead from every calendar.* entity (iCloud via CalDAV)
const CAL_DAYS = 7;
let calEvents = null; // null until the first fetch
const calIds = () => Object.keys(S).filter((id) => id.startsWith("calendar.")).sort();
const evStart = (e) => new Date(e.start.dateTime ?? `${e.start.date}T00:00:00`);
const evEnd = (e) => new Date(e.end.dateTime ?? `${e.end.date}T00:00:00`);
const hm = (d) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

let calFetchedAt = null; // when the calendars last loaded cleanly, for the health card
let calFailed = false;
async function loadCalendars() {
  const ids = calIds();
  const from = new Date(); from.setHours(0, 0, 0, 0);
  const to = new Date(from); to.setDate(to.getDate() + CAL_DAYS);
  try {
    const auth = conn.options.auth;
    if (auth.expired) await auth.refreshAccessToken();
    let failed = false;
    const lists = await Promise.all(ids.map(async (id) => {
      const r = await fetch(`/api/calendars/${id}?start=${from.toISOString()}&end=${to.toISOString()}`,
        { headers: { Authorization: `Bearer ${auth.accessToken}` } });
      if (!r.ok) failed = true;
      return r.ok ? (await r.json()).map((e) => ({ ...e, cal: id })) : [];
    }));
    calEvents = lists.flat().sort((a, b) => evStart(a) - evStart(b));
    calFailed = failed;
    if (!failed) calFetchedAt = Date.now();
  } catch {
    calEvents = calEvents ?? [];
    calFailed = true;
  }
  lastSig["#health"] = null;
  lastSig["#calendar"] = null;
  renderAll();
}

// event details
const URL_RE = /\bhttps?:\/\/[^\s<>"]+/g;
const CALL_RE = /https?:\/\/[^\s<>"]*(zoom\.us|meet\.google\.com|teams\.microsoft\.com|teams\.live\.com|facetime\.apple\.com|webex\.com|whereby\.com)[^\s<>"]*/i;
const linkify = (text) => esc(text).replace(URL_RE, (u) => `<a href="${u}" target="_blank" rel="noopener">${u.replace(/^https?:\/\//, "").slice(0, 48)}${u.length > 56 ? "…" : ""}</a>`);
const dur = (ms) => { const m = Math.round(ms / 60000); return m < 60 ? `${m} min` : m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m / 60} h`; };
function when(e) {
  const a = evStart(e), b = evEnd(e);
  const day = (d) => d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  if (!e.start.dateTime) {
    const last = new Date(b - 1);
    return [a.toDateString() === last.toDateString() ? day(a) : `${day(a)} – ${day(last)}`, "All day"];
  }
  return [day(a), `${hm(a)} – ${hm(b)}${a.toDateString() === b.toDateString() ? "" : ` (${day(b)})`} · ${dur(b - a)}`];
}
function relative(e) {
  const now = Date.now(), a = evStart(e).getTime(), b = evEnd(e).getTime();
  if (b <= now) return "Ended";
  if (a <= now) return `Happening now · ${dur(b - now)} left`;
  return `Starts in ${dur(a - now)}`;
}
function openEvent(e) {
  const dlg = $("#event");
  const [date, time] = when(e);
  const call = `${e.location ?? ""} ${e.description ?? ""}`.match(CALL_RE)?.[0];
  const isUrl = e.location && /^https?:\/\//.test(e.location.trim());
  dlg.style.setProperty("--h", hueOf(e.cal));
  dlg.innerHTML = `
    <form method="dialog" class="ev-close"><button aria-label="Close">×</button></form>
    <span class="ev-cal"><i></i>${esc(at(e.cal, "friendly_name") ?? e.cal)}</span>
    <h3>${esc(e.summary || "Busy")}</h3>
    <div class="ev-rows">
      <div class="ev-row">${I.cal}<div><b>${esc(date)}</b><span>${esc(time)}</span><small>${esc(relative(e))}</small></div></div>
      ${e.location && !isUrl ? `<div class="ev-row">${I.pin}<div><b>${esc(e.location)}</b>
        <a href="https://maps.apple.com/?q=${encodeURIComponent(e.location)}" target="_blank" rel="noopener">Open in Maps →</a></div></div>` : ""}
      ${e.rrule ? `<div class="ev-row">${I.repeat}<div><span>Repeats · ${esc(e.rrule.match(/FREQ=(\w+)/)?.[1]?.toLowerCase() ?? "custom")}</span></div></div>` : ""}
      ${e.description ? `<div class="ev-row">${I.notes}<div class="ev-notes">${linkify(e.description)}</div></div>` : ""}
    </div>
    ${call ? `<a class="ev-join" href="${esc(call)}" target="_blank" rel="noopener">Join call</a>` : ""}`;
  dlg.showModal();
}

section("#calendar", () => calIds(), () => {
  const ids = calIds();
  const head = (kicker) => `<div class="card-head"><div class="card-title">${I.cal} Calendar</div><span class="kicker">${kicker}</span></div>`;
  if (!ids.length) {
    return head("Not connected") + `<p class="empty-note">Connect iCloud: create an app-specific password at <b>account.apple.com → Sign-In and Security</b>, put <b>ICLOUD_USERNAME</b> and <b>ICLOUD_APP_PASSWORD</b> in the project's <b>.env</b>, then run <b>python -m homeassistant.apply</b>.</p>`;
  }
  if (!calEvents) return head("") + `<span class="skeleton">Loading…</span>`;
  const now = new Date();
  const next = calEvents.find((e) => e.start.dateTime && evEnd(e) > now);
  const days = Array.from({ length: CAL_DAYS }, (_, i) => {
    const d = new Date(now); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + i);
    const end = new Date(d); end.setDate(end.getDate() + 1);
    const evs = calEvents.filter((e) => evStart(e) < end && evEnd(e) > d);
    const name = i === 0 ? "Today" : i === 1 ? "Tomorrow" : d.toLocaleDateString(undefined, { weekday: "short" });
    const list = evs.map((e) => {
      const allDay = !e.start.dateTime;
      const live = !allDay && evStart(e) <= now && evEnd(e) > now;
      const past = !allDay && evEnd(e) <= now;
      return `<button class="ev ${allDay ? "all-day" : ""} ${live ? "live" : ""} ${past ? "past" : ""}" style="--h:${hueOf(e.cal)}"
                   data-act="event" data-i="${calEvents.indexOf(e)}" aria-haspopup="dialog">
        ${allDay ? "" : `<small>${hm(evStart(e))}</small>`}<b>${esc(e.summary || "Busy")}</b>
        ${e.location && !allDay ? `<span>${esc(e.location)}</span>` : ""}</button>`;
    }).join("");
    return `<div class="day ${i === 0 ? "today" : ""}"><div class="day-head"><b>${name}</b><span>${d.getDate()}</span></div>
      ${list || `<p class="free">Free</p>`}</div>`;
  }).join("");
  const kicker = next
    ? (evStart(next) <= now ? `Now · ${esc(next.summary || "Busy")}` : `Next · ${esc(next.summary || "Busy")} <b data-starts="${evStart(next).toISOString()}"></b>`)
    : `${calEvents.length} this week`;
  return head(kicker) + `<div class="week">${days}</div>`;
});

// investments (Hargreaves Lansdown): hidden until revealed on this device
let showMoney = (() => { try { return localStorage.hubShowMoney === "1"; } catch { return false; } })();
let invRange = "1Y";
let invAll = false;
let openHolding = null; // { sedol, range }
const gbp = (v, dp = 0) => v == null ? "—" : new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: dp, minimumFractionDigits: dp }).format(v);
const signed = (v, fmt) => v == null ? "—" : `${v >= 0 ? "+" : "−"}${fmt(Math.abs(v))}`;
const pct = (v, dp = 1) => signed(v, (x) => `${x.toFixed(dp)}%`);
const pence = (p) => p == null ? "—" : p >= 1000 ? gbp(p / 100, 2) : `${p.toFixed(2)}p`;
const DAY = 86400000;
const RANGES = { "1M": 31, "3M": 92, "6M": 183, "1Y": 366, "3Y": 1096, "5Y": 1827 };
const seriesOf = (sedol) => at(`sensor.investment_${String(sedol).toLowerCase()}`, "series") ?? [];
const sinceDays = (pts, days) => { if (!pts.length) return pts; const cut = pts.at(-1)[0] - days; const i = pts.findIndex((p) => p[0] >= cut); return pts.slice(Math.max(0, i)); };
const change = (pts) => pts.length > 1 ? (pts.at(-1)[1] / pts[0][1] - 1) * 100 : null;
const dayDate = (d) => new Date(d * DAY);

// Value of today's holdings through time: units now × each fund's price then (forward-filled), from the day all
// funds have data. It's "how what I hold has moved", not account value (no deposits/withdrawals in it).
function portfolioSeries(holdings) {
  const all = holdings.map((h) => ({ units: h.units ?? 0, pts: seriesOf(h.sedol) })).filter((x) => x.pts.length);
  if (!all.length) return [];
  const start = Math.max(...all.map((x) => x.pts[0][0]));
  const days = [...new Set(all.flatMap((x) => x.pts.map((p) => p[0])))].filter((d) => d >= start).sort((a, b) => a - b);
  const idx = all.map(() => 0);
  return days.map((d) => [d, all.reduce((sum, x, k) => {
    while (idx[k] + 1 < x.pts.length && x.pts[idx[k] + 1][0] <= d) idx[k]++;
    return sum + (x.units * x.pts[idx[k]][1]) / 100;
  }, 0)]);
}

// Interactive line chart: SVG drawn in a stretchable viewBox, with HTML crosshair/dot/tooltip on hover.
const charts = new Map();
let chartSeq = 0;
function lineChart(pts, { fmt, ref = null, refLabel = "", h = 200, cls = "", delta = true } = {}) {
  if (pts.length < 2) return `<div class="chart empty" style="--h:${h}px"><span>Not enough history yet</span></div>`;
  const id = `c${++chartSeq}`;
  if (charts.size > 40) charts.delete(charts.keys().next().value);
  const vals = pts.map((p) => p[1]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (ref != null) { lo = Math.min(lo, ref); hi = Math.max(hi, ref); }
  const pad = (hi - lo || hi * 0.02 || 1) * 0.12;
  lo -= pad; hi += pad;
  const t0 = pts[0][0], t1 = pts.at(-1)[0];
  const X = (t) => ((t - t0) / (t1 - t0 || 1)) * 1000;
  const Y = (v) => h - ((v - lo) / (hi - lo)) * h;
  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)} ${Y(p[1]).toFixed(1)}`).join("");
  const up = vals.at(-1) >= vals[0];
  charts.set(id, { pts, fmt, delta, x: pts.map((p) => X(p[0]) / 10), y: pts.map((p) => (Y(p[1]) / h) * 100) });
  const refY = ref != null ? (Y(ref) / h) * 100 : null;
  return `<div class="chart ${up ? "up" : "down"} ${cls}" data-chart="${id}" style="--h:${h}px">
    <svg viewBox="0 0 1000 ${h}" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="g${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".32"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
      <path d="${line}L1000 ${h}L0 ${h}Z" fill="url(#g${id})"/>
      <path d="${line}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    </svg>
    ${refY != null ? `<i class="chart-ref" style="top:${refY}%"><span>${esc(refLabel)}</span></i>` : ""}
    <i class="chart-x"></i><i class="chart-dot"></i><div class="chart-tip"></div>
  </div>`;
}
function chartHover(el, clientX) {
  const c = charts.get(el.dataset.chart);
  if (!c) return;
  const r = el.getBoundingClientRect();
  const fx = clamp(((clientX - r.left) / r.width) * 100, 0, 100);
  let i = c.x.findIndex((x) => x >= fx);
  if (i < 0) i = c.x.length - 1;
  if (i > 0 && fx - c.x[i - 1] < c.x[i] - fx) i--;
  const [d, v] = c.pts[i];
  const from = c.pts[0][1];
  el.style.setProperty("--hx", `${c.x[i]}%`);
  el.style.setProperty("--hy", `${c.y[i]}%`);
  el.classList.add("hover");
  el.querySelector(".chart-tip").innerHTML = `<b>${c.fmt(v)}</b>${c.delta ? `<span class="${v >= from ? "up" : "down"}">${pct((v / from - 1) * 100)}</span>` : ""}<small>${dayDate(d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</small>`;
}
document.addEventListener("pointermove", (ev) => { const el = ev.target.closest?.(".chart[data-chart]"); if (el) chartHover(el, ev.clientX); });
document.addEventListener("pointerout", (ev) => { const el = ev.target.closest?.(".chart[data-chart]"); if (el && !el.contains(ev.relatedTarget)) el.classList.remove("hover"); });

function spark(pts) {
  if (pts.length < 2) return "";
  const vals = pts.map((p) => p[1]), lo = Math.min(...vals), hi = Math.max(...vals) || 1, span = hi - lo || 1;
  const d = vals.map((v, i) => `${i ? "L" : "M"}${((i / (vals.length - 1)) * 100).toFixed(1)} ${(26 - ((v - lo) / span) * 24).toFixed(1)}`).join("");
  return `<svg class="mini ${vals.at(-1) >= vals[0] ? "up" : "down"}" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}
const rangeTabsFor = (act, current, avail, keys) => `<div class="ranges">${keys.filter((k) => avail >= RANGES[k] * 0.8 || k === keys[0])
  .map((k) => `<button data-act="${act}" data-v="${k}" aria-pressed="${k === current}">${k}</button>`).join("")}</div>`;
const rangeTabs = (act, current, avail) => `<div class="ranges">${Object.keys(RANGES).filter((k) => avail >= RANGES[k] * 0.8 || k === "1M")
  .map((k) => `<button data-act="${act}" data-v="${k}" aria-pressed="${k === current}">${k}</button>`).join("")}</div>`;

section("#invest", () => [INVEST, ...Object.keys(S).filter((id) => id.startsWith("sensor.investment_"))], () => {
  const e = S[INVEST];
  const head = (right) => `<div class="card-head"><div class="card-title">${I.chart} Investments</div>${right}</div>`;
  if (!e) return head(`<span class="kicker">Not connected</span>`) +
    `<p class="empty-note">Run <b>python -m investments setup</b> in the project (your Hargreaves Lansdown details go into the macOS Keychain), then <b>python -m investments login</b>.</p>`;
  const a = e.attributes;
  const total = parseFloat(e.state);
  const holdings = a.holdings ?? [];
  const stock = holdings.reduce((s, h) => s + (h.value ?? 0), 0) || 1;
  const paused = a.status === "paused" ? `<p class="invest-paused"><b>Refresh paused</b> · ${esc(a.paused_reason ?? "")}<br>Check your details, then run <b>python -m investments login</b> once by hand.</p>` : "";
  const updated = a.updated ? new Date(a.updated) : null;
  const toggle = `<button class="eye" data-act="money" aria-pressed="${showMoney}" aria-label="${showMoney ? "Hide" : "Show"} values">${showMoney ? I.eye : I.eyeOff}</button>`;
  const biggest = Math.max(...holdings.map((h) => h.value ?? 0), 1);
  const port = portfolioSeries(holdings);
  const span = port.length ? port.at(-1)[0] - port[0][0] : 0;
  const ranged = sinceDays(port, RANGES[invRange]);
  const rangeMove = change(ranged);
  const chart = port.length > 1
    ? `<div class="chart-head"><span class="kicker">Today's holdings over ${invRange} <b class="${(rangeMove ?? 0) >= 0 ? "up" : "down"}">${pct(rangeMove)}</b></span>${rangeTabs("inv-range", invRange, span)}</div>
       ${lineChart(ranged, { fmt: (v) => `<span class="money">${gbp(v)}</span>`, h: 170 })}`
    : sparkline(a.history);
  const rows = (invAll ? holdings : holdings.slice(0, 7)).map((h) => `
    <button class="holding" data-act="holding" data-v="${esc(h.sedol)}" style="--w:${((h.value ?? 0) / biggest).toFixed(3)}">
      <i class="bar"></i>
      <div class="holding-name"><b>${esc(h.name)}</b><span>${((h.value ?? 0) / stock * 100).toFixed(1)}% · ${esc(h.unit_type || h.account)}</span></div>
      ${spark(sinceDays(seriesOf(h.sedol), 92))}
      <div class="holding-val"><b class="money">${gbp(h.value)}</b>
        <span><em class="${(h.day_change_pct ?? 0) >= 0 ? "up" : "down"}">${h.day_change_pct != null ? pct(h.day_change_pct, 2) : ""}</em> <em class="${(h.gain_pct ?? 0) >= 0 ? "up" : "down"}">${h.gain_pct != null ? pct(h.gain_pct) : ""}</em></span></div>
    </button>`).join("");
  return head(`<span class="kicker">${updated ? `Updated ${hm(updated)}` : ""}</span>${toggle}`) + paused + `
    <div class="invest ${showMoney ? "" : "private"}">
      <div class="invest-summary">
        <div class="invest-total money">${Number.isFinite(total) ? gbp(total) : "—"}</div>
        <div class="invest-deltas">
          ${a.day_change != null ? `<span class="delta ${a.day_change >= 0 ? "up" : "down"}"><span class="money">${signed(a.day_change, gbp)}</span>${a.day_change_pct != null ? ` · ${pct(a.day_change_pct, 2)}` : ""} today</span>` : ""}
          ${a.gain != null ? `<span class="delta ${a.gain >= 0 ? "up" : "down"}"><span class="money">${signed(a.gain, gbp)}</span>${a.gain_pct != null ? ` · ${pct(a.gain_pct)}` : ""} all time</span>` : ""}
        </div>
        ${chart}
        <div class="accounts">${(a.accounts ?? []).map((acc) => `<div class="acct"><span>${esc(acc.name)}</span><b class="money">${gbp(acc.total)}</b></div>`).join("")}
          ${a.cash ? `<div class="acct"><span>Cash</span><b class="money">${gbp(a.cash)}</b></div>` : ""}</div>
      </div>
      <div class="holdings">
        <div class="holdings-head"><span>Holding</span><span>3M</span><span>Today · all time</span></div>
        ${rows || `<p class="empty-note">No holdings.</p>`}
        ${holdings.length > 7 ? `<button class="more" data-act="inv-all">${invAll ? "Show fewer" : `Show all ${holdings.length}`}</button>` : ""}
      </div>
    </div>`;
});

// cash (Trading 212): balance and the interest it pays, hidden until revealed like the investments card
let cashRange = "3M";
section("#cash", () => [T212], () => {
  const e = S[T212];
  const eye = `<button class="eye" data-act="money" aria-pressed="${showMoney}" aria-label="${showMoney ? "Hide" : "Show"} values">${showMoney ? I.eye : I.eyeOff}</button>`;
  const head = (right) => `<div class="card-head"><div class="card-title">${I.piggy} Cash</div>${right}</div>`;
  if (!e) return head(`<span class="kicker">Not connected</span>`) +
    `<p class="empty-note">In the Trading 212 app create a <b>read-only</b> API key (Settings → API), then run <b>python -m investments setup-t212</b> and <b>python -m investments t212</b>.</p>`;
  const a = e.attributes, it = a.interest ?? {};
  const cash = parseFloat(e.state);
  const paused = a.status === "paused" ? `<p class="invest-paused"><b>Refresh paused</b> · ${esc(a.paused_reason ?? "")}<br>Fix the key, then run <b>python -m investments t212</b> by hand.</p>` : "";
  const updated = a.updated ? new Date(a.updated) : null;
  const daily = it.daily ?? [];
  const span = daily.length ? daily.at(-1)[0] - daily[0][0] : 0;
  const cut = daily.length ? daily.at(-1)[0] - RANGES[cashRange] : 0;
  let run = 0;
  const cum = daily.filter((d) => d[0] >= cut).map(([d, v]) => [d, (run += v)]);
  const lastDay = it.last_date ? new Date(`${it.last_date}T12:00:00`) : null;
  const stat = (label, v) => `<div class="pos"><span>${label}</span><b class="money">${v == null ? "—" : gbp(v, 2)}</b></div>`;
  return head(`<span class="kicker">Trading 212</span>${eye}`) + paused + `
    <div class="cash ${showMoney ? "" : "private"}">
      <div class="invest-total money">${Number.isFinite(cash) ? gbp(cash, 2) : "—"}</div>
      <div class="invest-deltas">
        ${it.last_amount != null ? `<span class="delta up"><span class="money">+${gbp(it.last_amount, 2)}</span> interest${lastDay ? ` · ${lastDay.toLocaleDateString(undefined, { day: "numeric", month: "short" })}` : ""}</span>` : `<span class="delta">No interest paid yet</span>`}
        ${it.est_rate_pct != null ? `<span class="delta" title="Latest daily payment ×365 over today's balance. The rate and the balance both move.">≈ ${it.est_rate_pct.toFixed(2)}% a year <em class="est">est.</em></span>` : ""}
      </div>
      ${cum.length > 1 ? `<div class="chart-head"><span class="kicker">Interest earned</span>${rangeTabsFor("cash-range", cashRange, span, ["1M", "3M", "1Y"])}</div>
        ${lineChart(cum, { fmt: (v) => `<span class="money">${gbp(v, 2)}</span>`, h: 120, delta: false })}` : ""}
      <div class="positions cash-stats">
        ${stat("This month", it.month)}${stat("Last 30 days", it.last30)}
        ${stat("This year", it.ytd)}${stat("All time", it.all_time)}
      </div>
      <p class="h-src">${it.est_month != null ? `At today's rate, about <span class="money">${gbp(it.est_month, 2)}</span> a month. ` : ""}Interest is paid daily${updated ? ` · updated ${hm(updated)}` : ""}.</p>
    </div>`;
});

function renderHolding() {
  const dlg = $("#holding");
  if (!openHolding || !dlg.open) return;
  const inv = S[INVEST]?.attributes;
  const h = inv?.holdings?.find((x) => x.sedol === openHolding.sedol);
  if (!h) { dlg.close(); return; }
  const all = seriesOf(h.sedol);
  const span = all.length ? all.at(-1)[0] - all[0][0] : 0;
  const pts = sinceDays(all, RANGES[openHolding.range]);
  const avg = h.cost && h.units ? (h.cost / h.units) * 100 : null; // pence per unit
  const stock = (inv.holdings ?? []).reduce((s, x) => s + (x.value ?? 0), 0) || 1;
  const rets = Object.keys(RANGES).filter((k) => span >= RANGES[k] * 0.8)
    .map((k) => { const r = change(sinceDays(all, RANGES[k])); return `<div class="ret"><span>${k}</span><b class="${(r ?? 0) >= 0 ? "up" : "down"}">${pct(r)}</b></div>`; }).join("");
  const stat = (label, value, extra = "") => `<div class="pos"><span>${label}</span><b>${value}</b>${extra}</div>`;
  dlg.style.setProperty("--h", hueOf(h.sedol));
  dlg.innerHTML = `
    <form method="dialog" class="ev-close"><button aria-label="Close">×</button></form>
    <span class="ev-cal"><i></i>${esc(h.stock_type || "Fund")} · ${esc(h.sedol)} · ${esc(h.account)}</span>
    <h3>${esc(h.name)}</h3>
    <p class="h-sub">${esc(h.unit_type)}</p>
    <div class="h-price"><b>${pence(h.price_p)}</b>
      <span class="${(h.day_change_pct ?? 0) >= 0 ? "up" : "down"}">${h.day_change_pct != null ? `${pct(h.day_change_pct, 2)} today` : ""}</span></div>
    <div class="chart-head"><span class="kicker">Price, ${openHolding.range} <b class="${(change(pts) ?? 0) >= 0 ? "up" : "down"}">${pct(change(pts))}</b></span>${rangeTabs("h-range", openHolding.range, span)}</div>
    ${lineChart(pts, { fmt: pence, ref: avg, refLabel: avg ? `Your average ${pence(avg)}` : "", h: 230 })}
    <div class="rets">${rets}</div>
    <div class="positions ${showMoney ? "" : "private"}">
      ${stat("Value", `<span class="money">${gbp(h.value, 2)}</span>`)}
      ${stat("Gain", `<span class="money ${(h.gain ?? 0) >= 0 ? "up" : "down"}">${signed(h.gain, (v) => gbp(v, 2))}</span>`, `<small class="${(h.gain_pct ?? 0) >= 0 ? "up" : "down"}">${pct(h.gain_pct, 2)}</small>`)}
      ${stat("Today", `<span class="money ${(h.day_change ?? 0) >= 0 ? "up" : "down"}">${signed(h.day_change, (v) => gbp(v, 2))}</span>`, `<small class="${(h.day_change_pct ?? 0) >= 0 ? "up" : "down"}">${pct(h.day_change_pct, 2)}</small>`)}
      ${stat("Cost", `<span class="money">${gbp(h.cost, 2)}</span>`)}
      ${stat("Units", `<span class="money">${h.units?.toLocaleString(undefined, { maximumFractionDigits: 3 }) ?? "—"}</span>`)}
      ${stat("Average cost", pence(avg))}
      ${stat("Of portfolio", `${(((h.value ?? 0) / stock) * 100).toFixed(1)}%`)}
      ${stat("Yield", h.yield_pct != null ? `${h.yield_pct.toFixed(2)}%` : "—")}
    </div>
    <p class="h-src">Prices: Financial Times, daily close. Position: Hargreaves Lansdown.</p>`;
}

// desk: real sun position, weather, adaptive targets
section("#desk", () => [SUN, WEATHER, OUTDOOR, T_K, T_B, ADAPT, HOLD, MAXB, DESK], () => {
  const elev = at(SUN, "elevation") ?? 0;
  const az = at(SUN, "azimuth") ?? 180;
  const x = 20 + 260 * clamp((az - 45) / 270, 0, 1);
  const y = elev >= 0 ? 100 - 84 * clamp(elev / 62, 0, 1) : 100 + clamp(-elev, 0, 18);
  const day = elev > 0;
  const sunCol = elev > 10 ? "#fff3c4" : elev > -2 ? "#ffab5e" : "#b9c3ff";
  const [wIcon, wLabel] = WEATHER_ICON[st(WEATHER)] ?? [I.cloud, st(WEATHER) ?? "—"];
  const lamp = S[DESK];
  const lampK = lamp?.state === "on" && lamp.attributes.color_mode === "color_temp" ? lamp.attributes.color_temp_kelvin : null;
  const tk = num(T_K);
  const pos = (k) => `${clamp(((k - 2200) / 4300) * 100, 0, 100)}%`;
  const hold = is(HOLD, "active") ? at(HOLD, "finishes_at") : null;
  const maxb = num(MAXB, 55);
  return `
    <div class="card-head"><div class="card-title">${I.lamp} Desk</div>
      <span class="kicker">${is(ADAPT, "on") ? (hold ? "Manual hold" : "Adaptive") : "Manual"}</span></div>
    <div class="sky"><svg viewBox="0 0 300 120" preserveAspectRatio="none">
      <defs><radialGradient id="sg"><stop offset="0" stop-color="${sunCol}" stop-opacity=".9"/><stop offset="1" stop-color="${sunCol}" stop-opacity="0"/></radialGradient></defs>
      <path class="arc" d="M20 100 Q150 -40 280 100"/>
      <line class="horizon" x1="0" y1="100" x2="300" y2="100"/>
      <circle class="sun-glow" cx="${x}" cy="${y}" r="${day ? 34 : 18}" fill="url(#sg)" opacity="${day ? 1 : 0.5}"/>
      <circle class="sun" cx="${x}" cy="${y}" r="${day ? 7 : 5}" fill="${sunCol}" opacity="${day ? 1 : 0.7}"/>
      <text class="tick" x="20" y="116" text-anchor="middle">E</text><text class="tick" x="150" y="116" text-anchor="middle">S</text><text class="tick" x="280" y="116" text-anchor="middle">W</text>
      <text class="tick" x="296" y="12" text-anchor="end">${elev >= 0 ? "+" : ""}${elev.toFixed(1)}°</text>
    </svg></div>
    <div class="weather">${wIcon}<div class="temp">${S[WEATHER] ? Math.round(at(WEATHER, "temperature")) + "°" : "—"}</div>
      <div class="cond">${esc(wLabel)}<br>Cloud ${Math.round(at(WEATHER, "cloud_coverage") ?? 0)}% · light outside ${st(OUTDOOR) ?? "—"}%</div></div>
    <div class="kbar">${Number.isFinite(tk) ? `<i class="mark target" style="left:${pos(tk)}" title="Target"></i>` : ""}${lampK ? `<i class="mark" style="left:${pos(lampK)}" title="Lamp now"></i>` : ""}</div>
    <div class="kscale"><span>2200K candle</span><span>daylight 6500K</span></div>
    <div class="stats">
      <div class="stat"><span class="kicker">Colour</span><b>${Number.isFinite(tk) ? tk : "—"}</b><small>K</small></div>
      <div class="stat"><span class="kicker">Bright</span><b>${st(T_B) ?? "—"}</b><small>%</small></div>
      <div class="stat"><span class="kicker">Hold</span><b data-until="${hold ?? ""}">${hold ? "…" : "—"}</b></div>
    </div>
    <div class="row" style="margin-top:18px"><span class="label">Follow the sky</span>
      <button class="switch" role="switch" aria-checked="${is(ADAPT, "on")}" data-act="toggle" data-id="${ADAPT}" aria-label="Adaptive desk lamp"></button></div>
    <div class="row"><span class="label">Max brightness</span>
      <input class="slider" style="flex:1;--p:${((maxb - 15) / 85) * 100}%" type="range" min="15" max="100" step="5" value="${maxb}" data-act="number" data-id="${MAXB}" data-unit="%">
      <span class="value">${maxb}%</span></div>`;
});

// TV: a remote control plus what's on. Keys go through remote.send_command, apps through play_media.
const TV_APPS = [["Netflix", "com.netflix.ninja"], ["YouTube", "com.google.android.youtube.tv"], ["Spotify", "com.spotify.tv.android"],
  ["Prime Video", "com.amazon.amazonvideo.livingroom"], ["Disney+", "com.disney.disneyplus"], ["iPlayer", "uk.co.bbc.iplayer"],
  ["Apple TV", "com.apple.atve.androidtv.appletv"]];
const tvKey = (key) => call("remote", "send_command", { entity_id: TV_REMOTE, command: key });
section("#tv", () => [TV, TV_AUTO, SYNC, MODE], () => {
  const on = is(TV, "on");
  const live = S[TV] && S[TV].state !== "unavailable";
  const app = at(TV, "app_id");
  const [name, brand] = APPS[app] ?? [app ? app.split(".").pop() : "On", "150,150,190"];
  const glowing = is(SYNC, "on") && is(MODE, "tv");
  const vol = at(TV, "volume_level");
  const muted = at(TV, "is_volume_muted");
  const dis = on ? "" : "disabled";
  const key = (k, icon, label, cls = "", hold = false) =>
    `<button class="rk ${cls}" data-act="tv-key" data-v="${k}" ${hold ? "data-hold" : ""} aria-label="${label}" ${dis}>${icon}</button>`;
  return `
    <div class="card-head"><div class="card-title">${I.tv} TV</div>
      <span class="kicker">${S[TV] ? (on ? "On" : live ? "Off" : "Unavailable") : "Unavailable"}</span>
      <button class="rk power ${on ? "on" : ""}" data-act="tv-power" aria-label="${on ? "Turn the TV off" : "Turn the TV on"}" ${live ? "" : "disabled"}>${I.power}</button></div>
    <div><div class="screen ${on ? "on" : "off"}" style="--brand:${brand}"><span class="app">${on ? esc(name) : "Standby"}</span></div><div class="stand"></div></div>
    <div class="remote ${on ? "" : "off"}">
      <div class="dpad">
        ${key("DPAD_UP", I.up, "Up", "u", true)}${key("DPAD_LEFT", I.left, "Left", "l", true)}
        ${key("DPAD_CENTER", `<span>OK</span>`, "Select", "c")}
        ${key("DPAD_RIGHT", I.right, "Right", "r", true)}${key("DPAD_DOWN", I.down, "Down", "d", true)}
      </div>
      <div class="rrow">
        ${key("BACK", I.back, "Back")}${key("HOME", I.home, "Home")}${key("MEDIA_PLAY_PAUSE", `${I.play}`, "Play or pause")}
        <button class="rk" data-act="tv-mute" aria-label="${muted ? "Unmute" : "Mute"}" ${dis}>${muted ? I.mute : I.speaker}</button>
      </div>
      <div class="vol"><button class="rk" data-act="tv-key" data-v="VOLUME_DOWN" data-hold aria-label="Volume down" ${dis}>${I.minus}</button>
        <div class="vol-bar" style="--p:${typeof vol === "number" ? Math.round(vol * 100) : 0}%"><i></i><span>${typeof vol === "number" ? `${Math.round(vol * 100)}%` : "Volume"}</span></div>
        <button class="rk" data-act="tv-key" data-v="VOLUME_UP" data-hold aria-label="Volume up" ${dis}>${I.plus}</button></div>
    </div>
    <div class="apps">${TV_APPS.map(([n, pkg]) => `<button class="app-chip ${app === pkg ? "now" : ""}" style="--brand:${(APPS[pkg] ?? [0, "150,150,190"])[1]}"
      data-act="tv-app" data-v="${pkg}" data-name="${esc(n)}" ${live ? "" : "disabled"}>${esc(n)}</button>`).join("")}</div>
    <div class="row"><span class="label">Glow with the TV</span>
      <button class="switch" role="switch" aria-checked="${is(TV_AUTO, "on")}" data-act="toggle" data-id="${TV_AUTO}" aria-label="Glow with the TV"></button></div>
    <div class="row"><span class="label">Bias lighting</span><span class="value">${glowing ? "Active" : "—"}</span></div>`;
});

// System health: what's running, what's fresh and what's reachable, at a glance
const ago = (ms) => { const m = Math.round(ms / 60000); return !Number.isFinite(m) ? "no refresh yet" : m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const upFor = (ms) => { const m = Math.floor(ms / 60000); return m < 60 ? `${m} min` : m < 2880 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.floor(m / 1440)} d`; };
const ageMs = (iso) => iso ? Date.now() - new Date(iso).getTime() : Infinity;
section("#health", () => [HEALTH, INVEST, T212, SYNC, MODE, HOME, WEATHER, TV, ...LIGHTS.map((l) => l.id), ...calIds()], () => {
  const h = S[HEALTH];
  const ha = h?.attributes ?? {};
  const hAge = ageMs(ha.updated);
  const supOk = !!h && h.state !== "stopped" && hAge < 180_000;
  const daytime = new Date().getHours() >= 7 && new Date().getHours() < 22;

  const svcTile = (key, label, okDetail, missing = "Not set up") => {
    if (!supOk) return ["idle", label, "Unknown while the supervisor isn't reporting"];
    const sv = ha.services?.[key];
    if (!sv) return ["idle", label, missing];
    const rs = sv.restarts ? ` · restarted ${sv.restarts}×` : "";
    if (sv.state === "running") return [sv.restarts >= 3 ? "warn" : "ok", label, `${okDetail()}${rs}`];
    if (sv.state === "restarting") return ["warn", label, `Restarting${sv.last_exit != null ? ` (exit ${sv.last_exit})` : ""}${rs}`];
    return ["bad", label, "Stopped"];
  };
  // A data feed is healthy when its service is up, it isn't paused and it refreshed recently enough.
  const feedTile = (label, id, svcKey, limitDay, limitNight) => {
    const e = S[id];
    if (!e) return ["idle", label, "Not set up"];
    const a = e.attributes;
    if (a.status === "paused") return ["bad", label, `Paused: ${esc(String(a.paused_reason ?? "").slice(0, 110))}`];
    const sv = supOk ? ha.services?.[svcKey] : undefined;
    if (supOk && (!sv || sv.state !== "running")) return ["bad", label, `Service ${sv ? sv.state : "not running"}`];
    const ms = ageMs(a.updated);
    return [ms > (daytime ? limitDay : limitNight) * 60_000 ? "warn" : "ok", label, ms > (daytime ? limitDay : limitNight) * 60_000 ? `Last refresh ${ago(ms)}` : `Refreshed ${ago(ms)}`];
  };

  let sup;
  if (!h) sup = ["warn", "Supervisor", "Not running. Start it with ./home up so services are watched and restarted"];
  else if (h.state === "stopped") sup = ["bad", "Supervisor", "Stopped"];
  else if (hAge > 180_000) sup = ["bad", "Supervisor", `Not reporting · last seen ${ago(hAge)}`];
  else {
    const host = ha.host ?? {};
    const { disk_free_pct: disk, load1: load, cores = 1 } = host;
    const lvl = disk != null && disk < 5 ? "bad" : (disk != null && disk < 10) || (load != null && load > cores * 1.5) ? "warn" : "ok";
    sup = [lvl, "Supervisor", `Up ${upFor(ageMs(ha.supervisor_since))}${load != null ? ` · load ${load}` : ""}${disk != null ? ` · ${Math.round(disk)}% disk free` : ""}`];
  }

  const cals = calIds();
  const cal = !cals.length ? ["idle", "Calendar", "Not connected"]
    : calFailed ? ["warn", "Calendar", "Couldn't sync"]
    : !calFetchedAt ? ["idle", "Calendar", "Loading…"]
    : Date.now() - calFetchedAt > 15 * 60_000 ? ["warn", "Calendar", `Last synced ${ago(Date.now() - calFetchedAt)}`]
    : ["ok", "Calendar", `${cals.length} calendar${cals.length > 1 ? "s" : ""} · synced ${ago(Date.now() - calFetchedAt)}`];

  const w = S[WEATHER];
  const weather = !w || ["unavailable", "unknown"].includes(w.state) ? ["warn", "Weather", "No data"]
    : ["ok", "Weather", `${Math.round(w.attributes.temperature)}° · ${esc((WEATHER_ICON[w.state] ?? [])[1] ?? w.state)}`];

  const down = LIGHTS.filter((l) => !S[l.id] || S[l.id].state === "unavailable");
  const bulbs = !down.length ? ["ok", "Bulbs", `All ${LIGHTS.length} reachable`]
    : down.length === LIGHTS.length ? ["bad", "Bulbs", "None reachable"]
    : ["warn", "Bulbs", `${down.map((l) => esc(l.name)).join(", ")} unreachable`];

  const tvTile = !S[TV] || S[TV].state === "unavailable" ? ["warn", "TV", "Unreachable"]
    : ["ok", "TV", is(TV, "on") ? `On · ${esc((APPS[at(TV, "app_id")] ?? [])[0] ?? "app")}` : "Standby"];

  const tiles = [
    conn?.connected ? ["ok", "Home Assistant", `Connected${conn.haVersion ? ` · ${esc(conn.haVersion)}` : ""}`] : ["bad", "Home Assistant", "Reconnecting…"],
    sup,
    svcTile("music_sync", "Music sync", () => is(SYNC, "on") ? `Following the music · ${esc(st(MODE))}` : "Idle, ready", "Not running"),
    svcTile("announce", "Voice", () => "Ready to speak", "Not running"),
    svcTile("presence", "Presence", () => is(HOME, "on") ? "Home" : is(HOME, "off") ? "Away · lights off" : "Running"),
    feedTile("Hargreaves Lansdown", INVEST, "investments", 180, 540),
    feedTile("Trading 212", T212, "investments", 90, 300),
    cal, weather, bulbs, tvTile,
  ];
  const bad = tiles.filter((t) => t[0] === "bad").length;
  const warn = tiles.filter((t) => t[0] === "warn").length;
  const [cls, text] = bad ? ["bad", `${bad} problem${bad > 1 ? "s" : ""}`] : warn ? ["warn", `${warn} to check`] : ["", "All systems normal"];
  return `
    <div class="card-head"><div class="card-title">${I.pulse} System health</div><span class="health-pill ${cls}"><i></i>${text}</span></div>
    <div class="tiles">${tiles.map(([lvl, name, detail]) => `<div class="tile ${lvl}"><i class="tdot"></i><div><b>${name}</b><span>${detail}</span></div></div>`).join("")}</div>`;
});

section("#foot", () => [], () => `
  <div><span class="svc"><span class="dot ${conn?.connected ? "ok" : "bad"}" id="conn-dot"></span><span id="conn-label">${conn?.connected ? "Live" : "Connecting…"}</span></span>
  <span class="svc">${LIGHTS.length} lights · music sync · desk · TV</span></div>
  <a href="/home-hub/home" target="_top" style="color:inherit">Classic dashboard →</a>`);

// ── ambient colour field ─────────────────────────────────────────
function ambient() {
  const cols = LIGHTS.filter((l) => is(l.id, "on")).map((l) => rgbOf(S[l.id]));
  const palette = (at(NOW, "palette") ?? []).map(hexToRgb);
  const music = is(SYNC, "on") && at(NOW, "player_state") === "playing" && palette.length;
  const pool = music ? [...palette, ...cols] : cols;
  const hour = new Date().getHours();
  const fallback = hour >= 21 || hour < 6 ? [[60, 50, 140], [20, 70, 120], [90, 40, 90]] : [[255, 150, 80], [110, 80, 230], [40, 150, 190]];
  const pick = (i) => (pool.length ? pool[i % pool.length] : fallback[i]);
  const root = document.documentElement.style;
  ["--a1", "--a2", "--a3"].forEach((v, i) => root.setProperty(v, pick(i).join(",")));
  document.body.classList.toggle("dim", !cols.length && !music);
  const bpm = parseFloat(st(TEMPO));
  const beat = Number.isFinite(bpm) && is(SYNC, "on") ? `${(60 / bpm).toFixed(3)}s` : "0.5s";
  $("#hub").style.setProperty("--beat", beat);
  $("#music")?.classList.toggle("live", is(SYNC, "on") && Number.isFinite(bpm));
}

// ── clock, greeting, countdowns ──────────────────────────────────
function tick() {
  const d = new Date();
  const h = d.getHours();
  $("#clock").innerHTML = `${String(h).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}<span class="sec">${String(d.getSeconds()).padStart(2, "0")}</span>`;
  $("#date").textContent = d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  $("#hello").textContent = h < 5 ? "Still up" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  document.querySelectorAll(".progress").forEach((el) => {
    const dur = Number(el.dataset.dur);
    const since = el.dataset.playing === "true" ? Date.now() / 1000 - Number(el.dataset.at) : 0;
    const pos = clamp(Number(el.dataset.pos) + since, 0, dur);
    el.style.setProperty("--p", `${(pos / dur) * 100}%`);
    el.querySelector(".t-pos").textContent = fmtTime(pos);
    el.querySelector(".t-left").textContent = `-${fmtTime(dur - pos)}`;
  });
  document.querySelectorAll("[data-starts]").forEach((el) => {
    const mins = Math.round((new Date(el.dataset.starts) - d) / 60000);
    el.textContent = mins <= 0 ? "now" : mins < 60 ? `in ${mins} min` : mins < 1440 ? `in ${Math.floor(mins / 60)}h ${mins % 60}m` : "";
  });
  document.querySelectorAll("[data-until]").forEach((el) => {
    const until = el.dataset.until && new Date(el.dataset.until);
    if (!until) return;
    const s = Math.max(0, Math.round((until - d) / 1000));
    el.textContent = `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
  });
}

// The welcome button sends a ring of arc-reactor light out across the Hub.
function welcomeBurst(el) {
  const r = el.getBoundingClientRect();
  const burst = document.createElement("i");
  burst.className = "arc-burst";
  burst.style.left = `${r.left + 34}px`;
  burst.style.top = `${r.top + 34}px`;
  document.body.append(burst);
  burst.addEventListener("animationend", () => burst.remove());
  setTimeout(() => burst.remove(), 2000);
  toast("Welcome home, Sid");
}

// ── interaction ───────────────────────────────────────────────────
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-act]");
  if (!el || el.tagName === "INPUT") return;
  const { act, id, v } = el.dataset;
  if (act === "music") return call("script", "music_command", { command: v });
  // Mouse/touch presses are handled on pointerdown (so holding repeats); a click with no pointer is the keyboard.
  if (act === "tv-key") return ev.detail === 0 ? tvKey(v) : undefined;
  if (act === "tv-power") return call("media_player", is(TV, "on") ? "turn_off" : "turn_on", { entity_id: TV });
  if (act === "tv-mute") return call("media_player", "volume_mute", { entity_id: TV, is_volume_muted: !at(TV, "is_volume_muted") });
  if (act === "tv-app") { toast(`Opening ${el.dataset.name}…`); return call("media_player", "play_media", { entity_id: TV, media_type: "app", media_id: v }); }
  if (act === "holding") {
    openHolding = { sedol: v, range: "1Y" };
    const dlg = $("#holding");
    dlg.showModal();
    return renderHolding();
  }
  if (act === "h-range") { openHolding.range = v; return renderHolding(); }
  if (act === "cash-range") { cashRange = v; lastSig["#cash"] = null; return renderAll(); }
  if (act === "inv-range") { invRange = v; lastSig["#invest"] = null; return renderAll(); }
  if (act === "inv-all") { invAll = !invAll; lastSig["#invest"] = null; return renderAll(); }
  if (act === "money") {
    showMoney = !showMoney;
    try { localStorage.hubShowMoney = showMoney ? "1" : "0"; } catch { /* private mode */ }
    lastSig["#invest"] = null;
    lastSig["#cash"] = null;
    renderHolding();
    return renderAll();
  }
  if (act === "event") return calEvents?.[el.dataset.i] && openEvent(calEvents[el.dataset.i]);
  const domain = id.split(".")[0];
  if (act === "light") call("light", "toggle", { entity_id: id });
  else if (act === "toggle") call(domain, "toggle", { entity_id: id });
  else if (act === "script") {
    if (id === "script.welcome_home") welcomeBurst(el);
    call("script", "turn_on", { entity_id: id });
  }
  else if (act === "select") call(domain, "select_option", { entity_id: id, option: v });
});
document.addEventListener("toggle", (ev) => {
  if (ev.target.matches?.("details.tune")) tuneOpen = ev.target.open;
}, true);
document.addEventListener("input", (ev) => {
  const el = ev.target;
  if (!el.matches(".slider")) return;
  el.style.setProperty("--p", `${((el.value - el.min) / (el.max - el.min)) * 100}%`);
  if (el.dataset.act === "bri") {
    const light = el.closest(".light");
    light.style.setProperty("--b", (el.value / 100).toFixed(2));
    light.querySelector(".light-meta").textContent = `${el.value}%`;
  } else {
    const out = el.parentElement.querySelector(".value");
    if (out) out.textContent = `${el.dataset.id === SENS ? Number(el.value).toFixed(2) : el.value}${el.dataset.unit ?? ""}`;
  }
});
document.addEventListener("change", (ev) => {
  const el = ev.target;
  if (!el.matches(".slider")) return;
  if (el.dataset.act === "bri") call("light", "turn_on", { entity_id: el.dataset.id, brightness_pct: Number(el.value) });
  else call("input_number", "set_value", { entity_id: el.dataset.id, value: Number(el.value) });
});
// Hold a card still while a slider in it is being dragged, then catch up.
// Remote keys: press once on touch-down, and keep repeating while the arrows or volume are held.
let holdTimer, holdRepeat;
function stopHold() {
  clearTimeout(holdTimer);
  clearInterval(holdRepeat);
  if (busy.delete("#tv")) renderAll(); // catch the card up once the key is released
}
document.addEventListener("pointerdown", (ev) => {
  const b = ev.target.closest?.('[data-act="tv-key"]');
  if (!b || b.disabled) return;
  const key = b.dataset.v;
  tvKey(key);
  if (b.hasAttribute("data-hold")) {
    busy.add("#tv"); // don't rebuild the button under the finger while it's held
    holdTimer = setTimeout(() => { holdRepeat = setInterval(() => tvKey(key), 140); }, 380);
  }
});
document.addEventListener("pointerup", stopHold);
document.addEventListener("pointercancel", stopHold);
window.addEventListener("blur", stopHold);
document.addEventListener("contextmenu", (ev) => { if (ev.target.closest?.(".remote")) ev.preventDefault(); }); // no long-press menu
document.addEventListener("pointerdown", (ev) => {
  const card = ev.target.closest(".slider")?.closest("section");
  if (card) busy.add(`#${card.id}`);
});
document.addEventListener("pointerup", () => {
  if (!busy.size) return;
  setTimeout(() => { busy.clear(); renderAll(); }, 900);
});

// ── boot ──────────────────────────────────────────────────────────
async function connect() {
  const auth = await getAuth({
    hassUrl: location.origin,
    loadTokens: async () => { try { return JSON.parse(localStorage.hassTokens); } catch { return null; } },
    saveTokens: (data) => { try { localStorage.hassTokens = JSON.stringify(data); } catch { /* private mode */ } },
  });
  if (location.search.includes("auth_callback")) history.replaceState(null, "", location.pathname);
  return createConnection({ auth });
}

function setLive(ok) {
  const dot = $("#conn-dot");
  const label = $("#conn-label");
  if (dot) dot.className = `dot ${ok ? "ok" : "bad"}`;
  if (label) label.textContent = ok ? "Live" : "Reconnecting…";
}

(async () => {
  tick();
  setInterval(tick, 1000);
  setInterval(ambient, 60_000);
  for (const { sel } of sections) $(sel).innerHTML = `<span class="skeleton">Loading…</span>`;
  try {
    conn = await connect();
  } catch (err) {
    $("#room").innerHTML = `<p class="empty-note">Couldn't connect to Home Assistant (${esc(err)}). Open this page from Home Assistant's sidebar, or sign in at <a href="/" style="color:inherit">${esc(location.origin)}</a> first.</p>`;
    return;
  }
  setLive(true);
  const refreshHealth = () => { lastSig["#health"] = null; renderAll(); };
  conn.addEventListener("ready", () => { setLive(true); refreshHealth(); });
  conn.addEventListener("disconnected", () => { setLive(false); refreshHealth(); });
  setInterval(refreshHealth, 30_000); // ages ("refreshed 12 min ago") drift even when no entity changes
  let calKey = null;
  subscribeEntities(conn, (entities) => {
    S = entities;
    renderAll();
    const key = calIds().join();
    if (key !== calKey) { calKey = key; loadCalendars(); }
  });
  setInterval(() => conn.connected && loadCalendars(), 5 * 60_000);
})();
