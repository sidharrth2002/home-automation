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
const NF_CONT = "sensor.netflix_continue_watching";
const NF_WEEK = "sensor.netflix_episodes_this_week";

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
    ["party_mode", "Party", "Beat-locked colour", I.party, "linear-gradient(135deg,#ff3cac,#784ba0 55%,#2b86c5)", "#ff3cac", sync && mode === "party"],
    ["chill_mode", "Chill", "Gentle music glow", I.chill, "linear-gradient(135deg,#2af598,#009efd)", "#2af598", sync && mode === "calm"],
    ["movie_mode", "Movie", "Subtle TV glow", I.film, "linear-gradient(135deg,#f6d365,#fda085)", "#fda085", sync && mode === "tv"],
    ["all_off", "All off", "Everything dark", I.power, "linear-gradient(135deg,#3a3a48,#08080c)", "#9a9ab0", dark],
  ].map(([id, name, sub, icon, g, glow, active]) => `
    <button class="scene" data-act="script" data-id="script.${id}" aria-pressed="${active}" style="--g:${g};--glow:${glow}">
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

async function loadCalendars() {
  const ids = calIds();
  const from = new Date(); from.setHours(0, 0, 0, 0);
  const to = new Date(from); to.setDate(to.getDate() + CAL_DAYS);
  try {
    const auth = conn.options.auth;
    if (auth.expired) await auth.refreshAccessToken();
    const lists = await Promise.all(ids.map(async (id) => {
      const r = await fetch(`/api/calendars/${id}?start=${from.toISOString()}&end=${to.toISOString()}`,
        { headers: { Authorization: `Bearer ${auth.accessToken}` } });
      return r.ok ? (await r.json()).map((e) => ({ ...e, cal: id })) : [];
    }));
    calEvents = lists.flat().sort((a, b) => evStart(a) - evStart(b));
  } catch {
    calEvents = calEvents ?? [];
  }
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

// TV
section("#tv", () => [TV, TV_AUTO, SYNC, MODE], () => {
  const on = is(TV, "on");
  const app = at(TV, "app_id");
  const [name, brand] = APPS[app] ?? [app ? app.split(".").pop() : "On", "150,150,190"];
  const glowing = is(SYNC, "on") && is(MODE, "tv");
  return `
    <div class="card-head"><div class="card-title">${I.tv} TV</div><span class="kicker">${S[TV] ? (on ? "On" : "Off") : "Unavailable"}</span></div>
    <div><div class="screen ${on ? "on" : "off"}" style="--brand:${brand}"><span class="app">${on ? esc(name) : "Standby"}</span></div><div class="stand"></div></div>
    <div class="row"><span class="label">Glow with the TV</span>
      <button class="switch" role="switch" aria-checked="${is(TV_AUTO, "on")}" data-act="toggle" data-id="${TV_AUTO}" aria-label="Glow with the TV"></button></div>
    <div class="row"><span class="label">Bias lighting</span><span class="value">${glowing ? "Active" : "—"}</span></div>`;
});

// Netflix
section("#netflix", () => [NF_CONT, NF_WEEK], () => {
  const shows = at(NF_CONT, "shows") ?? [];
  const week = st(NF_WEEK);
  const list = shows.slice(0, 4).map((s) => `
    <div class="show"><div class="poster" style="--h:${hueOf(s.show)}">${esc(s.show[0] ?? "?")}</div>
      <div><b>${esc(s.show)}</b><span>${esc(s.next_after)}</span>
        <small>${esc(s.when)}${s.stopped_at ? ` · stopped at ${esc(s.stopped_at)}` : ""}</small></div></div>`).join("");
  return `
    <div class="card-head"><div class="card-title"><span class="n-logo">N</span> Continue watching</div>
      <span class="kicker">${week !== undefined ? `${week} this week` : ""}</span></div>
    ${shows.length ? `<div class="queue">${list}</div>` : `<p class="empty-note">No history yet. On netflix.com, open <b>Account → your profile → Viewing activity → Download all</b>. The file is picked up from Downloads automatically.</p>`}`;
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

// ── interaction ───────────────────────────────────────────────────
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-act]");
  if (!el || el.tagName === "INPUT") return;
  const { act, id, v } = el.dataset;
  if (act === "music") return call("script", "music_command", { command: v });
  if (act === "event") return calEvents?.[el.dataset.i] && openEvent(calEvents[el.dataset.i]);
  const domain = id.split(".")[0];
  if (act === "light") call("light", "toggle", { entity_id: id });
  else if (act === "toggle") call(domain, "toggle", { entity_id: id });
  else if (act === "script") call("script", "turn_on", { entity_id: id });
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
  conn.addEventListener("ready", () => setLive(true));
  conn.addEventListener("disconnected", () => setLive(false));
  let calKey = null;
  subscribeEntities(conn, (entities) => {
    S = entities;
    renderAll();
    const key = calIds().join();
    if (key !== calKey) { calKey = key; loadCalendars(); }
  });
  setInterval(() => conn.connected && loadCalendars(), 5 * 60_000);
})();
