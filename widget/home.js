// Home: an iPhone widget for the home Hub, written for the free Scriptable app.
// Install with `python -m widget install --copy` (it fills in the private feed address), then paste into a new
// Scriptable script and add a Scriptable widget to the home or lock screen. Small, medium, large and the lock
// screen widgets are all supported. It reads a small JSON feed (see widget/__main__.py), never Home Assistant itself.
// icon-color: purple; icon-glyph: lightbulb;

const FEEDS = "__FEED_URLS__"; // replaced by the installer: the feed's address on the home network
const HUB = "__HUB_URL__"; // tapping the widget opens the Hub
const STALE_MIN = 3; // the Mac normally refreshes the feed every 20s
const REFRESH_MIN = 5;

const APPS = {
  "com.netflix.ninja": "Netflix", "com.google.android.youtube.tv": "YouTube", "com.spotify.tv.android": "Spotify",
  "com.amazon.amazonvideo.livingroom": "Prime Video", "com.disney.disneyplus": "Disney+", "uk.co.bbc.iplayer": "iPlayer",
  "com.apple.atve.androidtv.appletv": "Apple TV", "com.google.android.apps.tv.launcherx": "Home screen",
  "com.google.android.tvlauncher": "Home screen",
};
const WEATHER = {
  "sunny": "Sunny", "clear-night": "Clear", "partlycloudy": "Partly cloudy", "cloudy": "Cloudy", "rainy": "Rain",
  "pouring": "Heavy rain", "fog": "Fog", "snowy": "Snow", "lightning": "Storm", "lightning-rainy": "Storm", "windy": "Windy",
};
const BASE = [10, 10, 20];

// ── data ─────────────────────────────────────────────────────────
async function load() {
  const fm = FileManager.local();
  const cache = fm.joinPath(fm.cacheDirectory(), "home-widget.json");
  for (const url of FEEDS) {
    try {
      const req = new Request(`${url}?t=${Date.now()}`); // the query string defeats Home Assistant's long caching
      req.timeoutInterval = 6;
      const data = await req.loadJSON();
      if (data && data.lights) {
        fm.writeString(cache, JSON.stringify(data));
        return { data, live: true };
      }
    } catch (e) { /* not on the home network: try the next address, then the cache */ }
  }
  if (fm.fileExists(cache)) return { data: JSON.parse(fm.readString(cache)), live: false };
  return null;
}

// ── small helpers ────────────────────────────────────────────────
const hex = (rgb) => "#" + rgb.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const ago = (ms) => { const m = Math.round(ms / 60000); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const white = (a) => new Color("#ffffff", a);

function summary(d) {
  const reachable = d.lights.filter((l) => l.reachable);
  return {
    on: d.lights.filter((l) => l.on).length,
    total: d.lights.length,
    weather: d.weather && d.weather.temp != null ? `${Math.round(d.weather.temp)}° ${WEATHER[d.weather.state] || ""}`.trim() : null,
    tv: d.tv && d.tv.state === "on" ? `TV · ${APPS[d.tv.app] || "on"}` : d.tv && d.tv.state === "off" ? "TV off" : null,
    presence: d.home === true ? "Home" : d.home === false ? "Away" : null,
    sync: d.sync && d.sync.on ? `Sync · ${d.sync.mode}` : null,
    problems: d.health && d.health !== "ok" ? "Check the Hub" : null,
    reachable: reachable.length,
  };
}

// A glowing bulb, drawn the way the Hub draws them: soft halo, then a white-hot core.
function orb(light) {
  const S = 160, c = S / 2;
  const dc = new DrawContext();
  dc.size = new Size(S, S);
  dc.opaque = false;
  dc.respectScreenScale = true;
  const disc = (r, color) => { dc.setFillColor(color); dc.fillEllipse(new Rect(c - r, c - r, 2 * r, 2 * r)); };
  if (light.on && light.rgb) {
    const rgb = light.rgb;
    const k = 0.4 + 0.6 * (light.pct / 100); // a dim bulb glows less
    for (let i = 0; i < 10; i++) disc(78 - i * 4, new Color(hex(rgb), 0.03 * k * (i + 1)));
    disc(34, new Color(hex(mix(rgb, [0, 0, 0], 0.25)), 1));
    disc(28, new Color(hex(rgb), 1));
    disc(20, new Color(hex(mix(rgb, [255, 255, 255], 0.55)), 1));
    disc(11, new Color("#ffffff", 0.95));
  } else {
    dc.setStrokeColor(white(light.reachable ? 0.2 : 0.08));
    dc.setLineWidth(4);
    dc.strokeEllipse(new Rect(c - 30, c - 30, 60, 60));
    disc(7, white(0.12));
  }
  return dc.getImage();
}

function background(w, d) {
  const lit = d.lights.filter((l) => l.on && l.rgb).map((l) => l.rgb);
  const a = lit[0] || [90, 60, 200];
  const b = lit[lit.length - 1] || [255, 140, 70];
  const g = new LinearGradient();
  g.colors = [new Color(hex(mix(BASE, a, 0.32))), new Color(hex(BASE)), new Color(hex(mix(BASE, b, 0.24)))];
  g.locations = [0, 0.55, 1];
  g.startPoint = new Point(0, 0);
  g.endPoint = new Point(1, 1);
  w.backgroundGradient = g;
}

function text(parent, str, size, opts = {}) {
  const t = parent.addText(String(str));
  t.font = opts.weight === "bold" ? Font.boldSystemFont(size) : opts.weight === "semibold" ? Font.semiboldSystemFont(size)
    : opts.weight === "medium" ? Font.mediumSystemFont(size) : Font.systemFont(size);
  t.textColor = white(opts.alpha == null ? 0.9 : opts.alpha);
  if (opts.lines) t.lineLimit = opts.lines;
  return t;
}

// The orbs with a name and brightness under each.
function orbRow(parent, d, size, gap) {
  const row = parent.addStack();
  row.centerAlignContent();
  row.spacing = gap;
  for (const l of d.lights) {
    const col = row.addStack();
    col.layoutVertically();
    col.centerAlignContent();
    const img = col.addImage(orb(l));
    img.imageSize = new Size(size, size);
    img.centerAlignImage();
    text(col, l.name, 9, { weight: "medium", alpha: l.on ? 0.8 : 0.4 }).centerAlignText();
    text(col, l.on ? `${l.pct}%` : l.reachable ? "off" : "—", 9, { alpha: 0.45 }).centerAlignText();
  }
  return row;
}

async function art(url) {
  if (!url) return null;
  try { const r = new Request(url); r.timeoutInterval = 5; return await r.loadImage(); } catch (e) { return null; }
}

async function music(parent, d, wide) {
  const m = d.music;
  const box = parent.addStack();
  box.centerAlignContent();
  box.spacing = 10;
  if (!m || !m.title) {
    text(box, d.sync && d.sync.on ? "Waiting for music" : "Nothing playing", 12, { alpha: 0.4 });
    return box;
  }
  const img = await art(m.art);
  if (img) {
    const i = box.addImage(img);
    i.imageSize = new Size(wide ? 56 : 46, wide ? 56 : 46);
    i.cornerRadius = 10;
  }
  const col = box.addStack();
  col.layoutVertically();
  col.spacing = 2;
  text(col, m.title, wide ? 14 : 12, { weight: "bold", lines: 2 });
  if (m.artist) text(col, m.artist, wide ? 12 : 10.5, { alpha: 0.6, lines: 1 });
  if (!m.playing) text(col, "Paused", 10, { alpha: 0.4 });
  return box;
}

function footer(parent, s, size, res) {
  const bits = [s.presence, s.weather, s.tv, s.sync, s.problems].filter(Boolean);
  const line = parent.addText(bits.join("  ·  ") || " ");
  line.font = Font.mediumSystemFont(size);
  line.textColor = white(0.55);
  line.lineLimit = 1;
  line.minimumScaleFactor = 0.7;
  const age = Date.now() - new Date(res.data.updated).getTime();
  if (!res.live || age > STALE_MIN * 60000) {
    const note = parent.addText(res.live ? `Feed ${ago(age)}` : `Away from home · ${ago(age)}`);
    note.font = Font.systemFont(size - 1);
    note.textColor = new Color("#ffb454", 0.8);
  }
}

// ── layouts ──────────────────────────────────────────────────────
async function small(w, res) {
  const d = res.data, s = summary(d);
  w.setPadding(12, 12, 10, 12);
  const top = w.addStack();
  text(top, "Home", 11, { weight: "semibold", alpha: 0.7 });
  top.addSpacer();
  text(top, `${s.on} of ${s.total} on`, 10, { alpha: 0.55 });
  w.addSpacer();
  const row = orbRow(w, d, 38, 6);
  row.centerAlignContent();
  w.addSpacer();
  if (d.music && d.music.title && d.music.playing) text(w, `♪ ${d.music.title}`, 10.5, { weight: "medium", alpha: 0.75, lines: 1 });
  else footer(w, { presence: s.presence, weather: s.weather }, 10, res);
}

async function medium(w, res) {
  const d = res.data, s = summary(d);
  w.setPadding(13, 15, 11, 15);
  const top = w.addStack();
  top.centerAlignContent();
  text(top, "Home", 12, { weight: "semibold", alpha: 0.75 });
  top.addSpacer();
  text(top, `${s.on} of ${s.total} lights on`, 10.5, { alpha: 0.55 });
  w.addSpacer(6);
  const mid = w.addStack();
  mid.centerAlignContent();
  orbRow(mid, d, 48, 8);
  mid.addSpacer(14);
  await music(mid, d, false);
  mid.addSpacer();
  w.addSpacer(6);
  footer(w, s, 10.5, res);
}

async function large(w, res) {
  const d = res.data, s = summary(d);
  w.setPadding(16, 18, 14, 18);
  const top = w.addStack();
  top.centerAlignContent();
  text(top, "Home", 15, { weight: "bold", alpha: 0.85 });
  top.addSpacer();
  text(top, s.presence || " ", 12, { alpha: 0.6 });
  w.addSpacer(10);
  orbRow(w, d, 70, 22);
  w.addSpacer(14);
  await music(w, d, true);
  w.addSpacer(14);
  const tiles = [["Lights", `${s.on} of ${s.total} on`], ["TV", s.tv ? s.tv.replace("TV · ", "") : "—"],
    ["Weather", s.weather || "—"], ["Music sync", d.sync && d.sync.on ? d.sync.mode : "off"]];
  for (let r = 0; r < tiles.length; r += 2) {
    const row = w.addStack();
    row.spacing = 8;
    for (const [k, v] of tiles.slice(r, r + 2)) {
      const tile = row.addStack();
      tile.layoutVertically();
      tile.setPadding(8, 10, 8, 10);
      tile.cornerRadius = 12;
      tile.backgroundColor = white(0.06);
      tile.spacing = 2;
      text(tile, k.toUpperCase(), 8.5, { weight: "semibold", alpha: 0.4 });
      text(tile, v, 13, { weight: "semibold", lines: 1 });
      tile.size = new Size(142, 0); // fixed width so the pair shares the row; 0 = height fits the content
    }
    w.addSpacer(8);
  }
  w.addSpacer();
  footer(w, { problems: s.problems }, 10.5, res);
}

function lockScreen(w, res, family) {
  const d = res.data, s = summary(d);
  if (family === "accessoryCircular") {
    w.addAccessoryWidgetBackground = true;
    const t = w.addText(String(s.on));
    t.font = Font.boldSystemFont(22);
    t.centerAlignText();
    const u = w.addText("on");
    u.font = Font.systemFont(9);
    u.centerAlignText();
  } else if (family === "accessoryInline") {
    w.addText(`💡 ${s.on} on${d.music && d.music.title ? ` · ♪ ${d.music.title}` : ""}`);
  } else {
    w.addAccessoryWidgetBackground = true;
    const a = w.addText(`Home · ${s.on} of ${s.total} on`);
    a.font = Font.boldSystemFont(12);
    const b = w.addText(d.music && d.music.title ? `♪ ${d.music.title}` : s.tv || s.weather || (s.presence || ""));
    b.font = Font.systemFont(11);
    b.lineLimit = 1;
    if (!res.live) {
      const c = w.addText(`Away · ${ago(Date.now() - new Date(d.updated).getTime())}`);
      c.font = Font.systemFont(10);
    }
  }
}

function unreachable(w) {
  w.backgroundColor = new Color(hex(BASE));
  w.setPadding(14, 14, 14, 14);
  text(w, "Home", 13, { weight: "bold" });
  w.addSpacer(4);
  text(w, "Can't reach the home yet. Open the widget on your home Wi-Fi once.", 11, { alpha: 0.6 });
}

// ── run ──────────────────────────────────────────────────────────
const family = config.widgetFamily || "medium";
const w = new ListWidget();
const res = await load();
if (!res) {
  unreachable(w);
} else if (family.startsWith("accessory")) {
  lockScreen(w, res, family);
} else {
  background(w, res.data);
  if (family === "small") await small(w, res);
  else if (family === "large" || family === "extraLarge") await large(w, res);
  else await medium(w, res);
}
w.url = HUB;
w.refreshAfterDate = new Date(Date.now() + REFRESH_MIN * 60000);
if (config.runsInWidget) Script.setWidget(w);
else await w.presentMedium();
Script.complete();
