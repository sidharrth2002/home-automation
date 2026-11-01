// Runs widget/home.js against a strict stand-in for Scriptable's API: any method or property the real app doesn't
// have throws, so typos are caught here rather than on the phone. Not a substitute for looking at it on a device.
//   node tests/widget_smoke.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const strict = (name, methods, props, init = {}) => {
  const target = { __calls: [], ...init };
  return new Proxy(target, {
    get(t, k) {
      if (k === "then") return undefined; // awaiting an object probes for .then; real objects just don't have one
      if (k in t || typeof k === "symbol") return t[k];
      if (!methods.includes(k)) throw new Error(`${name}.${String(k)} is not a Scriptable method`);
      return (...a) => { t.__calls.push([k, a]); return ret(name, k, t, a); };
    },
    set(t, k, v) {
      if (!props.includes(k)) throw new Error(`${name}.${String(k)} is not a Scriptable property`);
      t[k] = v; return true;
    },
  });
};
const stack = () => strict("WidgetStack", ["addText", "addImage", "addStack", "addSpacer", "layoutHorizontally", "layoutVertically",
  "centerAlignContent", "setPadding"], ["backgroundColor", "cornerRadius", "size", "spacing", "url"]);
const text = () => strict("WidgetText", ["centerAlignText", "leftAlignText", "rightAlignText"],
  ["text", "font", "textColor", "lineLimit", "minimumScaleFactor"]);
const image = () => strict("WidgetImage", ["centerAlignImage"], ["imageSize", "cornerRadius"]);
function ret(name, k, t, a) {
  if (k === "addStack") return stack();
  if (k === "addText") { const x = text(); x.text = a[0]; return x; }
  if (k === "addImage") return image();
  if (k === "getImage") return { image: true };
  return undefined;
}

const results = [];
async function run(family, feed, { online = true, cached = null, art = true } = {}) {
  const widget = strict("ListWidget", ["addText", "addImage", "addStack", "addSpacer", "setPadding", "presentSmall",
    "presentMedium", "presentLarge"], ["backgroundColor", "backgroundGradient", "url", "refreshAfterDate",
    "addAccessoryWidgetBackground", "spacing"]);
  const files = new Map(cached ? [["cache/home-widget.json", JSON.stringify(cached)]] : []);
  const ctx = {
    config: { runsInWidget: true, widgetFamily: family },
    Script: { setWidget: (w) => results.push({ family, w }), complete() {} },
    ListWidget: function () { return widget; },
    LinearGradient: function () { return strict("LinearGradient", [], ["colors", "locations", "startPoint", "endPoint"]); },
    Color: function (h, a) { if (!/^#[0-9a-f]{6}$/i.test(h)) throw new Error(`bad colour ${h}`); this.h = h; this.a = a; },
    Size: function (w, h) { this.w = w; this.h = h; },
    Rect: function (x, y, w, h) { Object.assign(this, { x, y, w, h }); },
    Point: function (x, y) { this.x = x; this.y = y; },
    Font: Object.fromEntries(["boldSystemFont", "semiboldSystemFont", "mediumSystemFont", "systemFont"].map((n) => [n, (s) => ({ n, s })])),
    DrawContext: function () {
      return strict("DrawContext", ["setFillColor", "fillEllipse", "setStrokeColor", "setLineWidth", "strokeEllipse", "getImage"],
        ["size", "opaque", "respectScreenScale"]);
    },
    Request: function (url) {
      return {
        timeoutInterval: 0,
        loadJSON: async () => { if (!online) throw new Error("offline"); if (!url.includes("feed")) throw new Error("bad url"); return feed; },
        loadImage: async () => { if (!art) throw new Error("no art"); return { img: true }; },
      };
    },
    FileManager: { local: () => ({ cacheDirectory: () => "cache", joinPath: (a, b) => `${a}/${b}`,
      writeString: (p, s) => files.set(p, s), readString: (p) => files.get(p), fileExists: (p) => files.has(p) }) },
    Date, JSON, Math, Promise, String, Number, Object, Array, console,
  };
  let src = fs.readFileSync(process.env.WIDGET_JS || path.join(__dirname, "..", "widget", "home.js"), "utf8")
    .replace('"__FEED_URLS__"', '["http://192.168.0.1:8123/local/widget/feed.json"]').replace("__HUB_URL__", "http://hub");
  await vm.runInNewContext(`(async () => {\n${src}\n})()`, ctx);
}

const now = () => new Date().toISOString();
const feed = (over = {}) => ({
  updated: now(),
  lights: [{ name: "TV 1", on: true, reachable: true, pct: 60, rgb: [28, 120, 255] },
    { name: "Desk", on: true, reachable: true, pct: 12, rgb: [255, 167, 87] },
    { name: "TV 2", on: false, reachable: true, pct: 0, rgb: null }],
  sync: { on: true, mode: "party" },
  music: { title: "No Surprises", artist: "Radiohead", playing: true, art: "https://i.scdn.co/image/x", palette: ["#aabbcc"] },
  tv: { state: "on", app: "com.netflix.ninja" }, home: true, weather: { state: "cloudy", temp: 8.2 }, health: "ok", ...over,
});

(async () => {
  const families = ["small", "medium", "large", "extraLarge", "accessoryCircular", "accessoryRectangular", "accessoryInline"];
  const cases = {
    "normal": [feed(), {}],
    "nothing playing": [feed({ music: { title: null, artist: null, playing: false, art: null, palette: [] } }), {}],
    "paused, no art": [feed({ music: { title: "A very long track title that has to wrap or truncate cleanly", artist: "Someone", playing: false, art: null, palette: [] } }), { art: false }],
    "all off, away, tv off": [feed({ lights: feed().lights.map((l) => ({ ...l, on: false, rgb: null, pct: 0 })), home: false, tv: { state: "off", app: null }, sync: { on: false, mode: "auto" } }), {}],
    "unreachable bulb, problems": [feed({ lights: feed().lights.map((l, i) => i === 1 ? { ...l, on: false, reachable: false, rgb: null } : l), health: "degraded" }), {}],
    "sparse feed": [feed({ weather: null, tv: null, home: null, health: null, sync: null }), {}],
    "stale feed": [feed({ updated: new Date(Date.now() - 3 * 3600e3).toISOString() }), {}],
  };
  for (const family of families) {
    for (const [name, [data, opts]] of Object.entries(cases)) {
      try { await run(family, data, opts); } catch (e) { console.error(`FAIL ${family} / ${name}: ${e.message}`); process.exit(1); }
    }
    // offline with a cached copy, and offline with nothing at all
    try {
      await run(family, feed(), { online: false, cached: feed({ updated: new Date(Date.now() - 2 * 3600e3).toISOString() }) });
      await run(family, feed(), { online: false });
    } catch (e) { console.error(`FAIL ${family} / offline: ${e.message}`); process.exit(1); }
  }
  const offline = results.filter((r) => r.family === "medium").slice(-1)[0];
  if (!offline.w.url) throw new Error("tapping the widget should open the Hub");
  console.log(`widget script OK (${results.length} renders across ${families.length} sizes)`);
})();
