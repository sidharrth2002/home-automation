// Demo mode (?demo=1): a made-up household for screenshots and showing the Hub off. Nothing here is real (the
// portfolio, the calendar, the tasks and the track are invented) and nothing is controlled: the Hub doesn't connect
// to Home Assistant at all. Photos are the guest set (freely licensed landscapes) if this machine has one.

const DAY = 86400000;

function rng(seed) { // mulberry32: the same "random" numbers every time, so screenshots are stable
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const iso = (ms) => new Date(ms).toISOString();
const day = (ms) => Math.floor(ms / DAY);

// A fund's price history: a random walk with drift, ending at today's price (pence), daily for ~14 months.
function walk(r, end, drift, vol, days = 420) {
  const raw = [1];
  for (let i = 1; i < days; i++) raw.push(raw[i - 1] * (1 + drift / 252 + (r() - 0.5) * 2 * vol));
  const k = end / raw.at(-1);
  const today = day(Date.now());
  return raw.map((v, i) => [today - (days - 1 - i), +(v * k).toFixed(2)]);
}

const FUNDS = [ // name, account, value, gain %, today %, drift, volatility, price (p), exposure
  ["Global Equity Index Fund", "isa", 18420, 31.2, -0.42, 0.11, 0.009, 412.6, { s: 97, b: 0, c: 3, r: { us: 62, eu: 14, uk: 4, jp: 6, ap: 5, em: 9 } }],
  ["US Large Cap Tracker", "isa", 12750, 44.8, -0.71, 0.14, 0.011, 688.1, { s: 99, b: 0, c: 1, r: { us: 99, eu: 1 } }],
  ["Emerging Markets Fund", "isa", 6310, 8.4, 0.35, 0.05, 0.010, 151.9, { s: 96, b: 0, c: 4, r: { em: 78, ap: 12, us: 6, eu: 4 } }],
  ["Japan Index Fund", "isa", 4880, 18.9, 0.92, 0.08, 0.010, 236.4, { s: 99, b: 0, c: 1, r: { jp: 100 } }],
  ["Global Bond Fund", "isa", 5600, -2.1, 0.08, 0.01, 0.003, 98.7, { s: 0, b: 92, c: 8, r: {} }],
  ["Asia Income Fund", "gia", 3950, 12.3, 0.21, 0.06, 0.008, 310.2, { s: 97, b: 0, c: 3, r: { ap: 70, em: 22, jp: 8 } }],
  ["UK All Share Index", "gia", 4200, 15.6, -0.18, 0.07, 0.008, 289.3, { s: 99, b: 0, c: 1, r: { uk: 100 } }],
  ["Sterling Money Market", "gia", 3000, 4.9, 0.01, 0.048, 0.0002, 100.4, { s: 0, b: 6, c: 94, r: {} }],
];
const REGIONS = { us: ["Americas", "United States"], eu: ["Europe", "Eurozone"], uk: ["Europe", "United Kingdom"],
  jp: ["Asia-Pacific", "Japan"], ap: ["Asia-Pacific", "Developed Asia"], em: ["Asia-Pacific", "Emerging Asia"] };

function investments(now, r) {
  const sources = [
    { id: "hl", name: "Broker", kind: "auto", as_of: iso(now).slice(0, 10), updated: iso(now - 40 * 60000), status: "ok" },
    { id: "bank", name: "Bank", kind: "manual", as_of: iso(now - 2 * DAY).slice(0, 10), updated: iso(now - 2 * DAY), status: "ok" },
    { id: "nsandi", name: "NS&I", kind: "manual", as_of: iso(now - 9 * DAY).slice(0, 10), updated: iso(now - 9 * DAY), status: "ok" },
    { id: "t212", name: "Trading 212", kind: "auto", as_of: iso(now).slice(0, 10), updated: iso(now - 12 * 60000), status: "ok" },
  ];
  const series = {};
  const holdings = FUNDS.map(([name, acc, value, gain, today, drift, vol, price], i) => {
    const sedol = `demo${String(i + 1).padStart(3, "0")}`;
    series[sedol] = walk(r, price, drift, vol);
    const cost = value / (1 + gain / 100);
    return { name, value, cost: +cost.toFixed(2), gain: +(value - cost).toFixed(2), gain_pct: gain, units: +(value / (price / 100)).toFixed(2),
      price_p: price, unit_type: acc === "isa" ? "Accumulation" : "Income", day_change: +(value * today / 100).toFixed(2),
      day_change_pct: today, status: "held", account: acc === "isa" ? "Stocks & Shares ISA" : "GIA", sedol,
      source: acc === "isa" ? "hl" : "bank", in_total: true };
  });
  holdings.push({ name: "World Small Companies Fund", value: 2000, cost: 2000, gain: 0, gain_pct: 0, status: "pending",
    settles: iso(now + 2 * DAY).slice(0, 10), account: "GIA", sedol: "demo-pending", source: "bank", in_total: true });
  const sum = (acc) => holdings.filter((h) => (acc === "isa" ? h.source === "hl" : h.source === "bank")).reduce((s, h) => s + h.value, 0);
  const accounts = [
    { name: "Broker Stocks & Shares ISA", label: "Stocks & Shares ISA", provider: "Broker", type: "isa", source: "hl", in_total: true, total: sum("isa") + 640, stock: sum("isa"), cash: 640 },
    { name: "Bank GIA", label: "GIA", provider: "Bank", type: "gia", source: "bank", in_total: true, total: sum("gia") + 210, cash: 210 },
    { name: "Bank Regular Saver", label: "Regular Saver", provider: "Bank", type: "savings", source: "bank", in_total: true, total: 3600, cash: 3600, interest_pct: 6.0, matures: iso(now + 200 * DAY).slice(0, 10) },
    { name: "Bank Current account", label: "Current account", provider: "Bank", type: "current", source: "bank", in_total: false, total: 1450, cash: 1450 },
    { name: "NS&I Premium Bonds", label: "Premium Bonds", provider: "NS&I", type: "premium_bonds", source: "nsandi", in_total: true, total: 5000, cash: 5000 },
    { name: "Trading 212 Cash", label: "Cash", provider: "Trading 212", type: "cash", source: "t212", in_total: true, total: 2480, cash: 2480 },
  ];
  const total = accounts.filter((a) => a.in_total).reduce((s, a) => s + a.total, 0);
  const dayChange = holdings.reduce((s, h) => s + (h.day_change ?? 0), 0);
  const invested = holdings.filter((h) => h.cost != null).reduce((s, h) => s + h.cost, 0);
  const gain = holdings.reduce((s, h) => s + (h.gain ?? 0), 0);
  // exposure: what the funds hold, weighted by value, plus the cash accounts
  const asset = { Shares: 0, Bonds: 0, Cash: 640 + 210 + 3600 + 5000 + 2480, "Not analysed": 2000 };
  const regions = {};
  FUNDS.forEach(([, , value, , , , , , x]) => {
    asset.Shares += value * x.s / 100; asset.Bonds += value * x.b / 100; asset.Cash += value * x.c / 100;
    for (const [k, pct] of Object.entries(x.r)) {
      const [g, n] = REGIONS[k];
      regions[`${g}|${n}`] = (regions[`${g}|${n}`] ?? 0) + value * x.s / 100 * pct / 100;
    }
  });
  const history = [];
  for (let i = 179; i >= 0; i--) history.push([iso(now - i * DAY).slice(0, 10), +(total * (0.86 + 0.14 * (179 - i) / 179) * (1 + (r() - 0.5) * 0.01)).toFixed(2)]);
  const attrs = {
    friendly_name: "Investments", status: "ok", updated: iso(now - 40 * 60000), cash: 850, invested_cost: +invested.toFixed(2),
    gain: +gain.toFixed(2), gain_pct: +(gain / invested * 100).toFixed(2), day_change: +dayChange.toFixed(2),
    day_change_pct: +(dayChange / (total - dayChange) * 100).toFixed(2), accounts, holdings, history, sources,
    exposure: { funds: FUNDS.length + 1, analysed: FUNDS.length, as_of: iso(now - 3 * DAY).slice(0, 10),
      asset: Object.entries(asset).map(([name, value]) => ({ name, value: +value.toFixed(2) })),
      regions: Object.entries(regions).map(([k, value]) => ({ group: k.split("|")[0], name: k.split("|")[1], value: +value.toFixed(2) }))
        .sort((a, b) => b.value - a.value) },
  };
  return { total, attrs, series };
}

export function demo(now = Date.now()) {
  const r = rng(20261121);
  const E = {};
  const put = (id, state, attributes = {}) => { E[id] = { entity_id: id, state: String(state), attributes, last_changed: iso(now - 3600000), last_updated: iso(now - 60000) }; };
  const palette = ["#ff5e7e", "#ffa44d", "#7b6cff", "#3fd0c9"];

  // the room: party mode, lamps in the album's colours
  const lamp = (id, name, rgb, b) => put(id, "on", { friendly_name: name, brightness: b, rgb_color: rgb, color_mode: "rgb", supported_color_modes: ["color_temp", "rgb"] });
  lamp("light.wiz_rgbw_tunable_624d4e", "TV lamp", [255, 94, 126], 190);
  lamp("light.wiz_rgbw_tunable_4b472c", "TV lamp", [123, 108, 255], 170);
  put("light.desk_lamp", "on", { friendly_name: "Desk lamp", brightness: 38, color_temp_kelvin: 2300, color_mode: "color_temp", supported_color_modes: ["color_temp", "rgb"] });
  put("light.tv_backlight", "on", { friendly_name: "Cabinet", brightness: 150, rgb_color: [255, 164, 77], color_mode: "hs", supported_color_modes: ["hs"] });

  put("input_boolean.music_sync", "on", { friendly_name: "Music sync" });
  put("input_select.music_sync_mode", "party", { options: ["auto", "calm", "party", "tv", "classic"] });
  put("input_select.music_sync_colours", "Music key", { options: ["Album art", "Music key"] });
  // the sleep timer's playlist picker: made-up playlists, no covers (the cards show a note icon)
  put("sensor.spotify_playlists", 6, { friendly_name: "Spotify playlists", playlists: ["Wind down", "Rain on the window",
    "Slow piano", "Lo-fi nights", "Ambient drift", "Sunday morning"].map((name, i) => ({ name, uri: `spotify:playlist:demo${i}`, image: null })) });
  put("sensor.sleep_timer", "off", { friendly_name: "Sleep timer" });
  put("input_number.music_sync_sensitivity", 1.4, { min: 0.5, max: 3, step: 0.1 });
  put("input_number.music_sync_latency", 60, { min: -300, max: 300, step: 10, unit_of_measurement: "ms" });
  put("sensor.music_sync_tempo", 124, { locked: true, confidence: 0.86, unit_of_measurement: "BPM" });
  put("sensor.music_sync_now_playing", "Neon Tide — The Midnight Arcs", {
    entity_picture: "demo-art.svg", palette, player_state: "playing", media_position: 81, media_duration: 236,
    media_position_updated_at: now / 1000 }); // epoch seconds, like music_sync's

  // outside, the desk lamp, the TV
  put("sun.sun", "below_horizon", { elevation: -21.4, azimuth: 285, rising: false, next_rising: iso(now + 10 * 3600000), next_setting: iso(now + 19 * 3600000) });
  put("weather.forecast_home", "partlycloudy", { temperature: 9, cloud_coverage: 55, humidity: 78, wind_speed: 14, temperature_unit: "°C" });
  put("sensor.outdoor_daylight", 0, { unit_of_measurement: "%" });
  put("sensor.desk_lamp_target_colour", 2300, { unit_of_measurement: "K" });
  put("sensor.desk_lamp_target_brightness", 15, { unit_of_measurement: "%" });
  put("input_boolean.desk_lamp_adaptive", "on", {});
  put("input_number.desk_lamp_max_brightness", 40, { min: 5, max: 100, step: 1, unit_of_measurement: "%" });
  put("timer.desk_lamp_manual", "idle", { duration: "2:00:00" });
  put("automation.tv_bias_lighting", "on", {});
  put("media_player.smart_tv_pro", "on", { friendly_name: "TV", app_id: "com.spotify.tv.android", app_name: "Spotify" });
  put("remote.smart_tv_pro", "on", { current_activity: "com.spotify.tv.android" });
  put("binary_sensor.someone_home", "on", { friendly_name: "Someone home" });

  // money
  const inv = investments(now, r);
  put("sensor.investments", inv.total.toFixed(2), inv.attrs);
  for (const [sedol, pts] of Object.entries(inv.series)) put(`sensor.investment_${sedol}`, pts.at(-1)[1], { series: pts, unit_of_measurement: "GBX" });
  const daily = Array.from({ length: 92 }, (_, i) => [day(now) - 91 + i, +(0.38 + (i / 92) * 0.04 + (r() - 0.5) * 0.02).toFixed(2)]);
  put("sensor.trading212", 2480, { status: "ok", updated: iso(now - 12 * 60000), interest: { est_rate_pct: 5.6, last_amount: 0.41,
    last_date: iso(now - DAY).slice(0, 10), month: 8.6, last30: 12.1, ytd: 118.4, all_time: 162.9, daily } });
  put("sensor.premium_bonds", "won", { holding: 5000, last_draw: iso(now).slice(0, 7), last_checked: iso(now - 5 * 3600000),
    won_this_year: 2, won_this_year_total: 50, unclaimed: 0, unclaimed_total: 0, next_check: iso(now + 12 * DAY).slice(0, 10) });

  // photos (filled in from the guest set when there is one), tasks, health
  put("input_boolean.guest_photos", "on", {});
  put("sensor.photo_frame", 0, { guest: true, photos: [], updated: iso(now) });
  put("sensor.photo_library", 64, { looked_at: 11240, remaining: 6310, last_batch: 150, updated: iso(now - 20 * 60000), unit_of_measurement: "%" });
  put("sensor.core_tasks", 1, { counts: { done: 41, running: 1 }, recent: [
    { id: 52, kind: "agent", title: "Summarise the budget spreadsheets", status: "running", progress: 0.6, message: "working (14 steps)", created_by: "claude", created_at: iso(now - 4 * 60000), started_at: iso(now - 4 * 60000) },
    { id: 51, kind: "agent", title: "Find three quiet cafés near the office", status: "done", progress: 1, created_by: "claude", created_at: iso(now - 3 * 3600000), finished_at: iso(now - 3 * 3600000 + 40000) },
    { id: 50, kind: "agent", title: "Compare broadband deals for the flat", status: "done", progress: 1, created_by: "claude", created_at: iso(now - 7 * 3600000), finished_at: iso(now - 7 * 3600000 + 90000) }] });
  const svc = (s) => ({ state: "running", restarts: 0, pid: 1000 + s });
  put("sensor.system_health", "ok", { updated: iso(now - 20000), supervisor_since: iso(now - 4 * DAY),
    services: Object.fromEntries(["core", "tasks", "music_sync", "widget", "announce", "investments", "backlight", "home_button", "home_mcp", "photos", "presence"].map((n, i) => [n, svc(i)])),
    host: { disk_free_pct: 41, load1: 1.9, cores: 10, platform: "Darwin" } });

  // the calendar: two calendars, a few made-up plans this week
  put("calendar.home", "off", { friendly_name: "Home" });
  put("calendar.work", "off", { friendly_name: "Work" });
  const at = (d, h, m = 0) => { const t = new Date(now); t.setDate(t.getDate() + d); t.setHours(h, m, 0, 0); return t.toISOString(); };
  const ev = (cal, summary, d, h1, h2, location = "") => ({ cal, summary, location, start: { dateTime: at(d, h1) }, end: { dateTime: at(d, h2) } });
  const soon = (cal, summary, inMin, mins, location = "") => { // today's, whatever the time: always still to come
    const s = Math.ceil((now + inMin * 60000) / 900000) * 900000;
    return { cal, summary, location, start: { dateTime: iso(s) }, end: { dateTime: iso(s + mins * 60000) } };
  };
  const events = [
    soon("calendar.home", "Call Mum", 40, 30), soon("calendar.home", "Climbing", 150, 90, "The Castle Climbing Centre"),
    ev("calendar.home", "Dinner with Sam and Priya", 1, 19, 22, "Dishoom, King's Cross"), ev("calendar.work", "Quarterly planning", 2, 14, 16),
    ev("calendar.home", "Football", 3, 18, 19), ev("calendar.home", "Cinema", 5, 20, 23, "Prince Charles Cinema"),
    { cal: "calendar.home", summary: "Brunch", start: { date: at(6, 0).slice(0, 10) }, end: { date: at(7, 0).slice(0, 10) } },
  ].sort((a, b) => new Date(a.start.dateTime ?? a.start.date) - new Date(b.start.dateTime ?? b.start.date));
  return { entities: E, events };
}
