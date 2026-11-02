// Runs widget/home.js against a strict stand-in for Scriptable's API: any method or property the real app doesn't
// have throws, so typos are caught here rather than on the phone. Not a substitute for looking at it on a device.
//   node tests/widget_smoke.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const strict = (name, methods, props, init = {}) => {
  const target = { __calls: [], __children: [], ...init };
  return new Proxy(target, {
    get(t, k) {
      if (k === "then") return undefined; // awaiting an object probes for .then; real objects just don't have one
      if (k in t || typeof k === "symbol" || props.includes(k)) return t[k];
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
  ["text", "font", "textColor", "lineLimit", "minimumScaleFactor", "url"]);
const image = () => strict("WidgetImage", ["centerAlignImage"], ["imageSize", "cornerRadius", "url"], { __isImage: true });
function ret(name, k, t, a) {
  const child = k === "addStack" ? stack() : k === "addText" ? text() : k === "addImage" ? image() : null;
  if (child) { if (k === "addText") child.text = a[0]; t.__children.push(child); return child; }
  if (k === "getImage") return { image: true };
  return undefined;
}
// every image (by its size) anywhere in a widget
const images = (node, out = []) => { if ("__isImage" in node) out.push(node.imageSize.w); node.__children.forEach((c) => images(c, out)); return out; };
// every tap target (stack url) anywhere in a widget
const urls = (node, out = []) => { if (node.url) out.push(node.url); node.__children.forEach((c) => urls(c, out)); return out; };

const ACTIONS = { ids: { tv1: "id-tv1", desk: "id-desk", tv2: "id-tv2", off: "id-off", ping: "id-ping" }, bases: ["http://x:8123", "http://y.local:8123"] };
const results = [];
async function run(family, feed, { param = null, online = true, cached = null, art = true, query = {}, runsInWidget = true, actions = ACTIONS, status = 200 } = {}) {
  const widget = strict("ListWidget", ["addText", "addImage", "addStack", "addSpacer", "setPadding", "presentSmall",
    "presentMedium", "presentLarge"], ["backgroundColor", "backgroundGradient", "url", "refreshAfterDate",
    "addAccessoryWidgetBackground", "spacing"]);
  const files = new Map(cached ? [["cache/home-widget.json", JSON.stringify(cached)]] : []);
  const log = { posts: [], alerts: [], widgets: [], completed: 0 };
  const ctx = {
    config: { runsInWidget, widgetFamily: family },
    args: { queryParameters: query, widgetParameter: param },
    Script: { setWidget: (w) => log.widgets.push(w), complete() { log.completed++; }, name: () => "Home" },
    ListWidget: function () { return widget; },
    Alert: function () {
      return strict("Alert", ["addAction", "presentAlert"], ["title", "message"], { __log: log });
    },
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
      const t = {};
      return new Proxy(t, {
        get(_, k) {
          if (k === "then") return undefined;
          if (k === "loadJSON") return async () => { if (!online) throw new Error("offline"); if (!url.includes("feed")) throw new Error("bad url"); return feed; };
          if (k === "loadImage") return async () => { if (!art) throw new Error("no art"); return { img: true }; };
          if (k === "load") return async () => { if (!online || url.startsWith("http://y.local")) throw new Error("offline"); log.posts.push({ url, method: t.method }); return ""; };
          if (k === "response") return { statusCode: status };
          if (k in t) return t[k];
          throw new Error(`Request.${String(k)} is not a Scriptable member`);
        },
        set(_, k, v) { if (!["timeoutInterval", "method"].includes(k)) throw new Error(`Request.${String(k)} is not a Scriptable property`); t[k] = v; return true; },
      });
    },
    FileManager: { local: () => ({ cacheDirectory: () => "cache", joinPath: (a, b) => `${a}/${b}`,
      writeString: (p, s) => files.set(p, s), readString: (p) => files.get(p), fileExists: (p) => files.has(p) }) },
    Date, JSON, Math, Promise, String, Number, Object, Array, console, encodeURIComponent,
  };
  // The Alert stand-in records when it's shown.
  const RealAlert = ctx.Alert;
  ctx.Alert = function () {
    const a = RealAlert();
    const orig = a.presentAlert;
    return new Proxy(a, { get(t, k) { if (k === "presentAlert") return async () => { log.alerts.push({ title: t.title, message: t.message }); }; return t[k]; },
      set(t, k, v) { t[k] = v; return true; } });
  };
  let src = fs.readFileSync(process.env.WIDGET_JS || path.join(__dirname, "..", "widget", "home.js"), "utf8")
    .replace('"__FEED_URLS__"', '["http://192.168.0.1:8123/local/widget/feed.json"]')
    .replace('"__ACTIONS__"', JSON.stringify(actions)).replace("__HUB_URL__", "http://hub");
  await vm.runInNewContext(`(async () => {\n${src}\n})()`, ctx);
  results.push({ family, widget, log });
  return { widget, log };
}

const now = () => new Date().toISOString();
const feed = (over = {}) => ({
  updated: now(),
  lights: [{ name: "TV 1", action: "tv1", on: true, reachable: true, pct: 60, rgb: [28, 120, 255] },
    { name: "Desk", action: "desk", on: true, reachable: true, pct: 12, rgb: [255, 167, 87] },
    { name: "TV 2", action: "tv2", on: false, reachable: true, pct: 0, rgb: null }],
  sync: { on: true, mode: "party" },
  music: { title: "No Surprises", artist: "Radiohead", playing: true, art: "https://i.scdn.co/image/x", palette: ["#aabbcc"] },
  tv: { state: "on", app: "com.netflix.ninja" }, home: true, weather: { state: "cloudy", temp: 8.2 }, health: "ok", ...over,
});
const assert = (cond, msg) => { if (!cond) { console.error(`FAIL ${msg}`); process.exit(1); } };

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
    "no tap targets configured": [feed(), { actions: { ids: {}, bases: [] } }],
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
  const renders = results.length;
  const online = await run("medium", feed());
  assert(online.widget.backgroundGradient, "a normal render fell back to the 'can't reach the home' screen (a request stand-in is probably failing)");
  const offline = await run("medium", feed(), { online: false });
  assert(!offline.widget.backgroundGradient, "with no connection and no cache it should show the fallback screen");
  const lock = await run("accessoryRectangular", feed());
  assert(lock.widget.__children.some((c) => /lights|on/.test(String(c.text))), "the lock screen widget should show the lights summary");

  // ── tap targets ───────────────────────────────────────────────
  const tapUrls = (family, opts) => run(family, feed(), opts).then(({ widget }) => urls(widget).filter((u) => u.includes("action=")));
  const medium = await tapUrls("medium");
  assert(["tv1", "desk", "tv2"].every((a) => medium.some((u) => u.endsWith(`?action=${a}`))), `medium should tap-toggle all three bulbs: ${medium}`);
  const large = await tapUrls("large");
  assert(large.length === 4 && large.some((u) => u.endsWith("?action=off")), `large should have three bulbs and All lights off: ${large}`);
  assert((await tapUrls("small")).length === 0, "small widgets only have the one whole-widget tap");
  assert((await tapUrls("medium", { actions: { ids: {}, bases: [] } })).length === 0, "no tap targets without webhooks");
  assert(medium.every((u) => u.startsWith("scriptable:///run/Home?action=")), `tap URLs should open the Home script: ${medium}`);
  const whole = (await run("medium", feed())).widget.url;
  assert(whole === "http://hub", "the widget itself should still open the Hub");

  // ── one-lamp button widgets (small, with a parameter): the whole widget is the tap target ──
  for (const [param, expect] of [["desk", "?action=desk"], ["tv1", "?action=tv1"], ["tv2", "?action=tv2"], ["off", "?action=off"]]) {
    const b = (await run("small", feed(), { param })).widget;
    assert(b.url && b.url.startsWith("scriptable:///run/Home") && b.url.endsWith(expect), `button widget ${param} should toggle on tap: ${b.url}`);
    const sizes = images(b);
    assert(param === "off" ? sizes.length === 0 : sizes.length === 1 && sizes[0] === 96, `button ${param} should draw one big bulb (or none for All off), got ${sizes}`);
  }
  assert(images((await run("small", feed())).widget).length === 3, "the plain small widget shows all three bulbs");
  assert((await run("small", feed(), { param: "nonsense" })).widget.url === "http://hub", "an unknown parameter falls back to the normal small widget");
  assert((await run("small", feed(), { param: "ping" })).widget.url === "http://hub", "the check action is not a button");
  assert((await run("small", feed(), { param: null })).widget.url === "http://hub", "a small widget with no parameter opens the Hub");
  assert((await run("small", feed(), { param: "desk", online: false })).widget.url === "http://hub", "with no data at all the button shouldn't try to toggle");
  assert((await run("medium", feed(), { param: "desk" })).widget.url === "http://hub", "the parameter only matters for small widgets");

  // ── a tap runs the script in the app ──────────────────────────
  let r = await run("medium", feed(), { runsInWidget: false, query: { action: "desk" } });
  assert(r.log.posts.length === 1 && r.log.posts[0].url === "http://x:8123/api/webhook/id-desk" && r.log.posts[0].method === "POST",
    `tap should POST once to the desk webhook: ${JSON.stringify(r.log.posts)}`);
  assert(r.log.alerts.length === 0 && r.log.widgets.length === 0 && r.log.completed === 1, "a successful tap shows nothing and stops");

  r = await run("medium", feed(), { runsInWidget: false, query: { action: "evil" } });
  assert(r.log.posts.length === 0, "an unknown action must not make any request");
  assert(r.log.alerts.length === 1, "an unknown action should say it didn't work");

  r = await run("medium", feed(), { runsInWidget: false, query: { action: "off" }, online: false });
  assert(r.log.posts.length === 0 && r.log.alerts.length === 1 && /home Wi-Fi/.test(r.log.alerts[0].message), "away from home it should say so");

  r = await run("medium", feed(), { runsInWidget: false, query: { action: "tv1" }, status: 500 });
  assert(r.log.alerts.length === 1, "a non-200 answer should be reported, not swallowed");

  // run from inside Scriptable with no action: a setup check that says what works, then the preview
  r = await run("medium", feed(), { runsInWidget: false });
  assert(r.log.alerts.length === 1 && /version 4/.test(r.log.alerts[0].message) && /Can read the home's feed/.test(r.log.alerts[0].message)
    && /Tap actions work/.test(r.log.alerts[0].message), `the check should report success: ${JSON.stringify(r.log.alerts)}`);
  assert(r.log.posts.length === 1 && r.log.posts[0].url.endsWith("/id-ping"), "the check should only ping, never toggle a light");
  assert(r.widget.__calls.some(([k]) => k === "presentMedium"), "the check should still show the preview");
  r = await run("medium", feed(), { runsInWidget: false, online: false });
  assert(/Can't read the feed/.test(r.log.alerts[0].message) && /Can't reach the tap actions/.test(r.log.alerts[0].message), "the check should say what's wrong away from home");

  // the same query inside a widget (iOS rendering it) must not trigger anything
  r = await run("medium", feed(), { runsInWidget: true, query: { action: "desk" } });
  assert(r.log.posts.length === 0, "rendering a widget must never toggle a light");

  console.log(`widget script OK (${renders} renders across ${families.length} sizes, tap targets, button widgets and the tap handler checked)`);
})();
