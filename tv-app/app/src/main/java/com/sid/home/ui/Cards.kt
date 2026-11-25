package com.sid.home.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Switch
import androidx.tv.material3.SwitchDefaults
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import coil.decode.SvgDecoder
import coil.request.ImageRequest
import com.sid.home.BuildConfig
import com.sid.home.ha.data
import kotlinx.coroutines.delay
import kotlin.math.abs

// ── Room: one glowing orb per lamp ────────────────────────────────
private val STRIP_COLOURS = listOf("Candle" to (30 to 55), "Amber" to (28 to 85), "Rose" to (345 to 45),
    "Lavender" to (265 to 40), "Ocean" to (205 to 50), "Sage" to (140 to 35))

@Composable
fun RoomCard(ctx: Ctx, first: androidx.compose.ui.focus.FocusRequester? = null) {
    val on = Ids.lights.count { ctx.on(it.first) }
    val sync = ctx.on(Ids.SYNC)
    HubCard {
        CardHead("Room", HubIcons.bulb) {
            Kicker((if (on > 0) "$on of ${Ids.lights.size} on" else "All dark") + if (sync) " · ${ctx.st(Ids.MODE)} sync" else "")
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            for ((i, l) in Ids.lights.withIndex()) Lamp(ctx, l.first, l.second, l.third, sync && l.first != Ids.DESK, Modifier.weight(1f),
                if (i == 0) first else null)
        }
        ctx.s[Ids.STRIP]?.let { strip ->
            val hs = strip.arr("hs_color")?.map { it.toString().toDouble() } ?: listOf(30.0, 70.0)
            Spacer(Modifier.height(10.dp))
            Box(Modifier.fillMaxWidth().height(1.dp).background(Hub.line))
            Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Cabinet", style = Hub.text(10.sp, Hub.ink2))
                for ((n, c) in STRIP_COLOURS) {
                    val (h, s) = c
                    val chosen = strip.state == "on" && abs(((hs[0] - h + 540) % 360) - 180) < 4 && abs(hs[1] - s) < 6
                    Pressable(onClick = { ctx.act.callService("light", "turn_on", data("entity_id" to Ids.STRIP, "hs_color" to listOf(h, s))) },
                        shape = CircleShape, scale = 1.12f) {
                        Box(Modifier.size(16.dp).clip(CircleShape).background(Color.hsv(h.toFloat(), s / 100f, 1f))
                            .then(if (chosen) Modifier.border(2.dp, Hub.ink, CircleShape) else Modifier))
                    }
                }
            }
        }
        // where music sync takes its colours from: the music itself (default) or the album cover
        Spacer(Modifier.height(10.dp))
        Box(Modifier.fillMaxWidth().height(1.dp).background(Hub.line))
        Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Music colours", style = Hub.text(10.sp, Hub.ink2)); Spacer(Modifier.width(14.dp))
            ColoursChoice(ctx, Modifier.width(240.dp))
        }
    }
}

@Composable
private fun Lamp(ctx: Ctx, id: String, name: String, tag: String, syncing: Boolean, modifier: Modifier, focus: androidx.compose.ui.focus.FocusRequester? = null) {
    val e = ctx.s[id]
    val lit = e?.state == "on"
    val color = if (lit) lightColor(e) else Color.White
    val pct = if (lit) pctOf(e) else 0
    val glow by animateFloatAsState(if (lit) 0.35f + pct / 160f else 0f, tween(600), label = "glow")
    val kind = if (e?.str("color_mode") == "color_temp") "${e.num("color_temp_kelvin")?.toInt()}K" else "colour"
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Kicker(tag + if (lit && syncing) " · live" else "", color = if (lit) color.copy(alpha = .9f) else Hub.ink3)
        Spacer(Modifier.height(8.dp))
        Pressable(onClick = { ctx.act.callService("light", "toggle", data("entity_id" to id)) }, shape = CircleShape, scale = 1.03f, glow = color,
            modifier = if (focus != null) Modifier.focusRequester(focus) else Modifier) {
            Canvas(Modifier.size(104.dp)) {
                val r = size.minDimension / 2
                drawCircle(Brush.radialGradient(listOf(color.copy(alpha = glow), Color.Transparent), center, r * 1.0f), r)
                val core = r * 0.78f
                if (lit) drawCircle(Brush.radialGradient(listOf(Color.White.copy(alpha = .85f), color, color.copy(alpha = .55f)),
                    Offset(center.x - core * .35f, center.y - core * .4f), core * 1.5f), core)
                else drawCircle(Brush.radialGradient(listOf(Color(0xFF1D1D26), Color(0xFF111117)), center, core), core)
                drawCircle(Color.White.copy(alpha = if (lit) .18f else .12f), core, style = androidx.compose.ui.graphics.drawscope.Stroke(1.dp.toPx()))
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(name, style = Hub.text(11.sp, weight = 500))
        Text(if (e == null) (if (ctx.s.isEmpty()) "" else "Unavailable") else if (lit) "$pct% · $kind" else "Off", style = Hub.text(8.sp, Hub.ink3, family = Hub.mono))
        Spacer(Modifier.height(6.dp))
        RemoteSlider(value = pct.coerceAtLeast(1).toFloat(), enabled = lit, fill = color, modifier = Modifier.fillMaxWidth().padding(horizontal = 6.dp),
            onCommit = { ctx.act.callService("light", "turn_on", data("entity_id" to id, "brightness_pct" to it.toInt())) })
    }
}

// ── Scenes ────────────────────────────────────────────────────────
private data class Scene(val id: String, val name: String, val sub: String, val icon: androidx.compose.ui.graphics.vector.ImageVector,
                         val colours: List<Color>, val glow: Color, val active: Boolean)

@Composable
fun ScenesRow(ctx: Ctx) {
    val sync = ctx.on(Ids.SYNC)
    val mode = ctx.st(Ids.MODE)
    val dark = Ids.lights.none { ctx.on(it.first) }
    val sleeping = ctx.on(Ids.SLEEP)
    val scenes = listOf(
        Scene("welcome_home", "Welcome home", "Lights, TV, hello", HubIcons.reactor, listOf(Color(0xFF00E5FF), Color(0xFF0077FF), Color(0xFF001B4D)), Color(0xFF00D4FF), false),
        Scene("party_mode", "Party", "Beat-locked colour", HubIcons.party, listOf(Color(0xFFFF3CAC), Color(0xFF784BA0), Color(0xFF2B86C5)), Color(0xFFFF3CAC), sync && mode == "party"),
        Scene("chill_mode", "Chill", "Gentle music glow", HubIcons.chill, listOf(Color(0xFF2AF598), Color(0xFF009EFD)), Color(0xFF2AF598), sync && mode == "calm"),
        Scene("movie_mode", "Movie", "Subtle TV glow", HubIcons.film, listOf(Color(0xFFF6D365), Color(0xFFFDA085)), Color(0xFFFDA085), sync && mode == "tv"),
        Scene("sleep_mode", "Sleep", if (sleeping) "Winding down…" else "Glow, then dark", HubIcons.moon, listOf(Color(0xFFFF9A5A), Color(0xFF6A3093), Color(0xFF120A2A)), Color(0xFFB07CFF), sleeping),
        Scene("all_off", "All off", "Everything dark", HubIcons.power, listOf(Color(0xFF3A3A48), Color(0xFF08080C)), Color(0xFF9A9AB0), dark && !sleeping),
    )
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        for (sc in scenes) {
            Pressable(onClick = {
                if (sc.id == "welcome_home") ctx.toast("Welcome home, Sid")
                ctx.act.callService("script", "turn_on", data("entity_id" to "script.${sc.id}"))
            }, modifier = Modifier.weight(1f), shape = RoundedCornerShape(16.dp), glow = sc.glow, scale = 1.03f) {
                // calm: dark glass and a small tinted icon; the scene that's on gets a soft outline in its colour
                Row(Modifier.fillMaxWidth().height(52.dp).background(if (sc.active) sc.glow.copy(alpha = .10f) else Hub.glass)
                    .border(1.dp, if (sc.active) sc.glow.copy(alpha = .55f) else Hub.line, RoundedCornerShape(16.dp)).padding(horizontal = 12.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(26.dp).clip(CircleShape).background(sc.glow.copy(alpha = .14f)), contentAlignment = Alignment.Center) {
                        HubIcon(sc.icon, sc.glow.copy(alpha = .9f), 13.dp)
                    }
                    Spacer(Modifier.width(9.dp))
                    Column {
                        Text(sc.name, style = Hub.text(10.5.sp, Hub.ink, 500), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(sc.sub, style = Hub.text(7.5.sp, Hub.ink3), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

// ── Music sync + now playing ──────────────────────────────────────
/** Only there while there's music: Spotify playing, or a show running off the room's sound (as in the Hub). */
fun musicShown(ctx: Ctx): Boolean {
    val playing = ctx.s[Ids.NOW]?.str("player_state") == "playing"
    return playing || (ctx.on(Ids.SYNC) && ctx.st(Ids.MODE) != "tv")
}

/** The cover's URL as Coil can load it: from Home Assistant, the web, or (demo) the app's assets. */
fun artUrl(art: String?) = art?.let { if (it.startsWith("http")) it else if (it.startsWith("/")) BuildConfig.HA_URL + it else "file:///android_asset/$it" }

/** The music sync choices, the music's own colours first (the default). */
@Composable
fun ColoursChoice(ctx: Ctx, modifier: Modifier = Modifier) {
    val colours = (ctx.s[Ids.COLOURS]?.arr("options")?.map { it.toString().trim('"') } ?: listOf("Album art", "Music key"))
        .sortedByDescending { it == "Music key" }
    Segmented(colours, ctx.st(Ids.COLOURS), modifier = modifier,
        onSelect = { ctx.act.callService("input_select", "select_option", data("entity_id" to Ids.COLOURS, "option" to it)) })
}

/** [onOpen]: pressing the cover opens the Music page (the compact card on Home). [focus]: where focus lands when it opens. */
@Composable
fun MusicCard(ctx: Ctx, modifier: Modifier = Modifier, compact: Boolean = false, onOpen: (() -> Unit)? = null,
              focus: androidx.compose.ui.focus.FocusRequester? = null) {
    val now = ctx.s[Ids.NOW]
    val parts = (now?.state ?: "").split(" — ")
    val title = parts.getOrNull(0).orEmpty()
    val artist = parts.getOrNull(1).orEmpty()
    val nothing = title.isBlank() || title == "Nothing playing"
    val playing = now?.str("player_state") == "playing"
    val art = now?.str("entity_picture")
    val palette = now?.arr("palette")?.map { hex(it.toString().trim('"')) } ?: emptyList()
    val dur = now?.num("media_duration") ?: 0.0
    var pos by remember { mutableDoubleStateOf(0.0) }
    LaunchedEffect(now) {
        while (true) {
            val since = if (playing) System.currentTimeMillis() / 1000.0 - (now?.num("media_position_updated_at") ?: 0.0) else 0.0
            pos = ((now?.num("media_position") ?: 0.0) + since).coerceIn(0.0, dur.coerceAtLeast(1.0))
            delay(1000)
        }
    }
    val tempo = ctx.s[Ids.TEMPO]
    val controls = !nothing || ctx.on(Ids.TV)
    HubCard(modifier) {
        CardHead("Music sync", HubIcons.music) {
            Switch(checked = ctx.on(Ids.SYNC), onCheckedChange = { ctx.act.callService("input_boolean", "toggle", data("entity_id" to Ids.SYNC)) },
                colors = SwitchDefaults.colors(checkedTrackColor = palette.firstOrNull() ?: Hub.accent),
                modifier = if (focus != null && !controls) Modifier.focusRequester(focus) else Modifier)
        }
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            val ctxAndroid = LocalContext.current
            val url = artUrl(art)
            val cover = @Composable {
                Box(Modifier.size(if (compact) 72.dp else 118.dp).clip(RoundedCornerShape(16.dp)).background(Color.White.copy(alpha = .06f))) {
                    if (url != null) AsyncImage(ImageRequest.Builder(ctxAndroid).data(url).decoderFactory(SvgDecoder.Factory()).crossfade(true).build(),
                        contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                }
            }
            if (onOpen != null) Pressable(onClick = onOpen, shape = RoundedCornerShape(16.dp), scale = 1.04f) { cover() } else cover()
        }
        Spacer(Modifier.height(10.dp))
        Text(if (nothing) "Nothing playing" else title, style = Hub.text(20.sp, family = Hub.serif), textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(), maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(if (nothing) "Spotify isn't playing" else artist + if (playing) "" else " · paused", style = Hub.text(10.sp, Hub.ink2),
            textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth(), maxLines = 1)
        Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.Center) {
            for (c in palette) Box(Modifier.padding(horizontal = 2.dp).size(9.dp).clip(CircleShape).background(c))
        }
        if (!nothing && dur > 0) {
            Spacer(Modifier.height(8.dp))
            Box(Modifier.fillMaxWidth().height(3.dp).clip(CircleShape).background(Color.White.copy(alpha = .1f))) {
                Box(Modifier.fillMaxWidth((pos / dur).toFloat()).height(3.dp).background(Brush.horizontalGradient(palette.ifEmpty { listOf(Hub.accent) }.let { if (it.size < 2) it + it else it })))
            }
            Row(Modifier.fillMaxWidth().padding(top = 3.dp)) {
                Text(fmt(pos), style = Hub.text(8.sp, Hub.ink3, family = Hub.mono)); Spacer(Modifier.weight(1f))
                Text("-" + fmt(dur - pos), style = Hub.text(8.sp, Hub.ink3, family = Hub.mono))
            }
        }
        if (controls) Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically) {
            fun music(cmd: String) = ctx.act.callService("script", "music_command", data("command" to cmd))
            Pressable(onClick = { music("previous") }, shape = CircleShape) { Box(Modifier.padding(8.dp)) { HubIcon(HubIcons.prev, Hub.ink2, 14.dp) } }
            Spacer(Modifier.width(10.dp))
            Pressable(onClick = { music("play_pause") }, shape = CircleShape, color = Hub.ink, focusedColor = Color.White,
                modifier = if (focus != null) Modifier.focusRequester(focus) else Modifier) {
                Box(Modifier.padding(10.dp)) { HubIcon(if (playing) HubIcons.pause else HubIcons.play, Hub.bg, 16.dp) }
            }
            Spacer(Modifier.width(10.dp))
            Pressable(onClick = { music("next") }, shape = CircleShape) { Box(Modifier.padding(8.dp)) { HubIcon(HubIcons.next, Hub.ink2, 14.dp) } }
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 5.dp), verticalAlignment = Alignment.CenterVertically) {
            Kicker("Mode"); Spacer(Modifier.weight(1f))
            tempo?.number?.let { bpm ->
                Text("${bpm.toInt()}", style = Hub.text(13.sp, weight = 600, family = Hub.mono))
                Text(" BPM" + if (tempo.bool("locked") == true) " · locked" else " · finding the beat…", style = Hub.text(8.sp, Hub.ink3, family = Hub.mono))
            }
        }
        val modes = ctx.s[Ids.MODE]?.arr("options")?.map { it.toString().trim('"') } ?: listOf("auto", "calm", "party", "tv", "classic")
        Segmented(modes, ctx.st(Ids.MODE), label = { if (it == "tv") "TV" else it },
            onSelect = { ctx.act.callService("input_select", "select_option", data("entity_id" to Ids.MODE, "option" to it)) })
        if (!compact) Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Kicker("Colours"); Spacer(Modifier.width(14.dp))
            ColoursChoice(ctx, Modifier.weight(1f))
        }
    }
}

private fun fmt(s: Double) = "${(s / 60).toInt()}:${(s % 60).toInt().toString().padStart(2, '0')}"


// ── Apps: the TV's own apps, opened directly (instant, unlike asking Home Assistant to do it) ──
data class TvApp(val name: String, val pkg: String, val brand: Color)

val TV_APPS = listOf(
    TvApp("Netflix", "com.netflix.ninja", Color(229, 9, 20)),
    TvApp("Prime Video", "com.amazon.amazonvideo.livingroom", Color(0, 168, 225)),
    TvApp("YouTube", "com.google.android.youtube.tv", Color(255, 40, 60)),
    TvApp("Spotify", "com.spotify.tv.android", Color(30, 215, 96)),
)

/** Open an app on this TV: its TV launch screen, or its ordinary one. */
fun launch(context: android.content.Context, pkg: String): Boolean {
    val pm = context.packageManager
    val intent = pm.getLeanbackLaunchIntentForPackage(pkg) ?: pm.getLaunchIntentForPackage(pkg) ?: return false
    context.startActivity(intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
    return true
}

/**
 * Apps' Google TV banners (or icons), drawn once per process and off the main thread: asking the package manager and
 * drawing each one took a few ms, and Home's apps row did it again every time the page was shown.
 */
object Banners {
    private val none = Any()
    private val cache = java.util.concurrent.ConcurrentHashMap<String, Any>()

    fun cached(pkg: String): androidx.compose.ui.graphics.ImageBitmap? = cache[pkg] as? androidx.compose.ui.graphics.ImageBitmap
    fun known(pkg: String) = cache.containsKey(pkg)

    /** The banner, null when the app isn't installed (or in tests). Call off the main thread. */
    fun load(context: android.content.Context, pkg: String): androidx.compose.ui.graphics.ImageBitmap? {
        cache[pkg]?.let { return it as? androidx.compose.ui.graphics.ImageBitmap }
        val bmp = runCatching {
            val pm = context.packageManager
            val d = pm.getApplicationBanner(pkg) ?: pm.getApplicationIcon(pkg)
            val w = d.intrinsicWidth.coerceAtLeast(1); val h = d.intrinsicHeight.coerceAtLeast(1)
            val bmp = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
            d.setBounds(0, 0, w, h); d.draw(android.graphics.Canvas(bmp))
            bmp.asImageBitmap().also { it.prepareToDraw() }
        }.getOrNull()
        cache[pkg] = bmp ?: none
        return bmp
    }
}

/** An app's banner: at once if it's been drawn before, otherwise as soon as it's ready. */
@Composable
fun rememberBanner(pkg: String): androidx.compose.ui.graphics.ImageBitmap? {
    val context = LocalContext.current
    return androidx.compose.runtime.produceState(Banners.cached(pkg), pkg) {
        if (value == null && !Banners.known(pkg)) value = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { Banners.load(context, pkg) }
    }.value
}

@Composable
fun AppsRow(ctx: Ctx, modifier: Modifier = Modifier, first: androidx.compose.ui.focus.FocusRequester? = null, onAllApps: () -> Unit = {},
            onScreensaver: () -> Unit = {}) {
    val context = LocalContext.current
    Row(modifier.fillMaxWidth().oneStepAtATime(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        for ((i, app) in TV_APPS.withIndex()) {
            val banner = rememberBanner(app.pkg)
            var focused by remember { androidx.compose.runtime.mutableStateOf(false) }
            // calm: the brand colours rest dimmed and only come up when the tile is focused
            val dim by animateFloatAsState(if (focused) 1f else .42f, tween(350), label = "dim")
            Pressable(onClick = { if (!launch(context, app.pkg)) ctx.toast("${app.name} isn't installed") },
                modifier = Modifier.weight(1f).then(if (i == 0 && first != null) Modifier.focusRequester(first) else Modifier)
                    .onFocusChanged { focused = it.isFocused },
                shape = RoundedCornerShape(14.dp), glow = app.brand, scale = 1.03f) {
                Box(Modifier.fillMaxWidth().height(66.dp).graphicsLayer { alpha = dim }
                    .background(Brush.linearGradient(listOf(app.brand, app.brand.copy(alpha = .55f)))), contentAlignment = Alignment.Center) {
                    if (banner != null) androidx.compose.foundation.Image(banner, app.name, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                    else Text(app.name, style = Hub.text(13.sp, Color.White, 700))
                }
            }
        }
        // the rest: Google TV's own home (every other app), and the TV's settings
        for ((label, icon, open) in listOf<Triple<String, androidx.compose.ui.graphics.vector.ImageVector, () -> Boolean>>(
            Triple("All apps", HubIcons.tv) { onAllApps(); true },
            Triple("Screensaver", HubIcons.moon) { onScreensaver(); true },
            Triple("Google TV", HubIcons.home) { com.sid.home.HomeRedirect.chooseGoogleTv(context); launch(context, com.sid.home.HomeRedirect.GOOGLE_TV) },
            Triple("Settings", HubIcons.reactor) { com.sid.home.HomeRedirect.openSettings(context) },
        )) {
            Pressable(onClick = { open() }, modifier = Modifier.weight(.62f), shape = RoundedCornerShape(14.dp), color = Hub.glass, scale = 1.03f) {
                Column(Modifier.fillMaxWidth().height(66.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                    HubIcon(icon, Hub.ink2, 16.dp); Spacer(Modifier.height(5.dp)); Text(label, style = Hub.text(10.sp, Hub.ink2, 500))
                }
            }
        }
    }
}

/** Every app on the TV with a TV launch screen, by name (the home screen's own "All apps"). */
fun installedApps(context: android.content.Context): List<Pair<String, String>> {
    val pm = context.packageManager
    val intent = android.content.Intent(android.content.Intent.ACTION_MAIN).addCategory(android.content.Intent.CATEGORY_LEANBACK_LAUNCHER)
    return pm.queryIntentActivities(intent, 0).map { it.activityInfo.packageName }.distinct().filter { it != context.packageName }
        .map { it to (runCatching { pm.getApplicationLabel(pm.getApplicationInfo(it, 0)).toString() }.getOrDefault(it)) }
        .sortedBy { it.second.lowercase() }
}

/** All apps, as a grid of their banners over the home screen; Back closes it. */
@Composable
fun AppsGrid(ctx: Ctx, onClose: () -> Unit) {
    val context = LocalContext.current
    // the package manager is slow on this TV: ask it off the main thread (the grid fills in a moment later)
    val apps by androidx.compose.runtime.produceState(emptyList<Pair<String, String>>()) {
        value = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { installedApps(context) }
    }
    val first = remember { androidx.compose.ui.focus.FocusRequester() }
    androidx.activity.compose.BackHandler { onClose() }
    LaunchedEffect(apps.isEmpty()) { if (apps.isNotEmpty()) { androidx.compose.runtime.withFrameNanos { }; runCatching { first.requestFocus() } } }
    Box(Modifier.fillMaxSize().background(Hub.bg.copy(alpha = .94f)).padding(horizontal = 56.dp, vertical = 36.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("All apps", style = Hub.text(28.sp, family = Hub.serif)); Spacer(Modifier.weight(1f)); Kicker("${apps.size} apps · Back to close")
            }
            Spacer(Modifier.height(18.dp))
            androidx.compose.foundation.lazy.grid.LazyVerticalGrid(androidx.compose.foundation.lazy.grid.GridCells.Fixed(5),
                horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(6.dp)) {
                items(apps.size) { i ->
                    val (pkg, label) = apps[i]
                    val banner = rememberBanner(pkg)
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Pressable(onClick = { launch(context, pkg); onClose() }, shape = RoundedCornerShape(12.dp), scale = 1.03f,
                            modifier = Modifier.fillMaxWidth().then(if (i == 0) Modifier.focusRequester(first) else Modifier)) {
                            Box(Modifier.fillMaxWidth().height(86.dp).background(Hub.glass), contentAlignment = Alignment.Center) {
                                if (banner != null) androidx.compose.foundation.Image(banner, label, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize())
                                else Text(label, style = Hub.text(11.sp, weight = 600))
                            }
                        }
                        Text(label, style = Hub.text(9.sp, Hub.ink2), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 5.dp))
                    }
                }
            }
        }
    }
}
