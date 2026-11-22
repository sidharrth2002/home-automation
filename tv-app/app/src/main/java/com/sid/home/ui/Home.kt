package com.sid.home.ui

import android.os.SystemClock
import androidx.compose.animation.core.tween
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.util.lerp
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import com.sid.home.ha.Actions
import com.sid.home.ha.Entity
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/** The entities the TV app reads (the same ones as the Hub: frontend/hub/app.js). */
object Ids {
    val lights = listOf(
        Triple("light.wiz_rgbw_tunable_624d4e", "TV lamp", "TV · 1"), Triple("light.desk_lamp", "Desk lamp", "Desk"),
        Triple("light.wiz_rgbw_tunable_4b472c", "TV lamp", "TV · 2"), Triple("light.tv_backlight", "Cabinet", "Strip"),
    )
    const val DESK = "light.desk_lamp"
    const val STRIP = "light.tv_backlight"
    const val SYNC = "input_boolean.music_sync"
    const val MODE = "input_select.music_sync_mode"
    const val COLOURS = "input_select.music_sync_colours"
    const val TEMPO = "sensor.music_sync_tempo"
    const val NOW = "sensor.music_sync_now_playing"
    const val HOME = "binary_sensor.someone_home"
    const val WEATHER = "weather.forecast_home"
    const val OUTDOOR = "sensor.outdoor_daylight"
    const val SLEEP = "script.sleep_mode"
    const val TV = "media_player.smart_tv_pro"
}

/**
 * Everything a card needs: the entities right now, and a way to change things. Made once and kept: on the TV [s] is a
 * [LiveEntities], so a card given the same Ctx is skipped when its parent recomposes, and recomposes only for the
 * entities it read.
 */
@Stable
class Ctx(val s: Map<String, Entity>, val act: Actions, val toast: (String) -> Unit) {
    fun st(id: String) = s[id]?.state
    fun on(id: String) = s[id]?.state == "on"
}

/** The pages, each one screen: the left rail moves between them, Google TV style (no scrolling). */
enum class Page(val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector) {
    ROOM("Home", HubIcons.home), MUSIC("Music", HubIcons.music), LIGHTS("Lights", HubIcons.bulb), TODAY("Today", HubIcons.cal), MONEY("Money", HubIcons.chart), ALLOCATION("Allocation", HubIcons.pin),
    HOME("Desk & health", HubIcons.pulse), SETTINGS("Settings", HubIcons.reactor)
}

/**
 * The home screen. A rail on the left (focus it with the remote's left arrow; up and down change page, and the page
 * follows the focus) and one page at a time, each fitting the TV, under the header with the clock and greeting.
 * [railOpen]: draw the rail open without focus (for the snapshot tests).
 */
@Composable
fun HomeScreen(ctx: Ctx, connected: Boolean, events: List<kotlinx.serialization.json.JsonObject> = emptyList(), start: Page = Page.ROOM,
               offline: String? = null, open: Page? = null, railOpen: Boolean = false, opened: () -> Unit = {}) {
    val palette = settled { ambientColours(ctx) }
    var holding by remember { mutableStateOf<String?>(null) }
    var allApps by remember { mutableStateOf(false) }
    var saver by remember { mutableStateOf(false) }
    // opened from Home's music card: focus moves to the Music page's controls (not when browsing the rail, which keeps it)
    var focusMusic by remember { mutableStateOf(false) }
    val musicFocus = remember { androidx.compose.ui.focus.FocusRequester() }
    var page by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(start) }
    val first = remember { androidx.compose.ui.focus.FocusRequester() }
    val railItems = remember { Page.entries.map { androidx.compose.ui.focus.FocusRequester() } }
    // This is the TV's home, so Back never leaves it: it closes what's open, or goes back to the first page.
    androidx.activity.compose.BackHandler { page = Page.ROOM; runCatching { first.requestFocus() } }
    androidx.activity.compose.BackHandler(enabled = holding != null) { holding = null }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
    // asked from outside (the Home button, or adb): that page, with nothing left open over it
    LaunchedEffect(open) {
        if (open == null) return@LaunchedEffect
        saver = false; allApps = false; holding = null
        page = open
        opened()
        if (open == Page.ROOM) runCatching { kotlinx.coroutines.delay(250); first.requestFocus() }
    }
    val covered = rememberUpdatedState(saver)
    Box(Modifier.fillMaxSize().background(Hub.bg)) {
        CompositionLocalProvider(LocalCovered provides covered) {
            // under the screensaver none of this is drawn (it's covered), so it costs nothing per frame there
            Box(Modifier.fillMaxSize().drawWithContent { if (!covered.value) drawContent() }) {
                Ambient(palette)
                Column(Modifier.fillMaxSize().padding(start = 76.dp, end = 32.dp, top = 20.dp, bottom = 22.dp)) {
                    Header(ctx, connected, palette.first(), offline)
                    Spacer(Modifier.height(14.dp))
                    androidx.compose.animation.AnimatedContent(page, label = "page", modifier = Modifier.weight(1f),
                        // a cross-fade only: no size animation between pages of different heights
                        transitionSpec = { (androidx.compose.animation.fadeIn(tween(220)) togetherWith androidx.compose.animation.fadeOut(tween(160))).using(null) }) { p ->
                        when (p) {
                            Page.ROOM -> Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                                AppsRow(ctx, first = first, onAllApps = { allApps = true }, onScreensaver = { saver = true })
                                Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                                    NowPanel(ctx, events, Modifier.weight(1.75f).fillMaxHeight(), connected)
                                    if (musicShown(ctx)) MusicCard(ctx, Modifier.weight(1f), compact = true,
                                        onOpen = { focusMusic = true; page = Page.MUSIC })
                                }
                                ScenesRow(ctx)
                            }
                            Page.MUSIC -> {
                                MusicPage(ctx, palette, musicFocus)
                                if (focusMusic) LaunchedEffect(Unit) {
                                    kotlinx.coroutines.delay(250) // after the cross-fade has put it on screen
                                    runCatching { musicFocus.requestFocus() }
                                    focusMusic = false
                                }
                            }
                            Page.LIGHTS -> RoomCard(ctx)
                            Page.TODAY -> Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                                if (ctx.s.keys.any { it.startsWith("calendar.") }) CalendarCard(ctx, events)
                                PhotosCard(ctx, Modifier.weight(1f))
                            }
                            Page.MONEY -> MoneyCard(ctx) { holding = it }
                            Page.ALLOCATION -> AllocationCard(ctx)
                            Page.SETTINGS -> SettingsPage(ctx, connected)
                            Page.HOME -> Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                                DeskCard(ctx, Modifier.weight(1f))
                                HealthCard(ctx, connected, ctx.s.keys.count { it.startsWith("calendar.") }, Modifier.weight(1.4f))
                            }
                        }
                    }
                }
                Rail(page, railItems, connected, railOpen, onRest = { page = it }, onPick = { page = it })
                holding?.let { HoldingView(ctx, it) { holding = null } }
                if (allApps) AppsGrid(ctx) { allApps = false }
            }
        }
        if (saver) Screensaver(ctx, palette, connected) { saver = false; runCatching { first.requestFocus() } }
    }
}

private val RAIL_ITEM = 40.dp  // each item's height: all eight fit the 540 dp screen with room to spare
private val RAIL_PILL = 56.dp  // an item at rest: its icon, in a pill when it's the page shown
private val RAIL_OPEN = 172.dp // the highlight's width when the names show
private const val RAIL_REST_MS = 300L

/**
 * The left rail: icons at rest, their names while it has focus. Lighter than tv-material's ModalNavigationDrawer,
 * which animated the drawer's width (measuring and laying out the rail again every frame of opening and closing) and
 * a full-screen scrim; here nothing changes size. The names and the backdrop fade as layers, and the highlight
 * widens in the draw phase. The page follows the focus once it rests on an item for [RAIL_REST_MS], so moving
 * through the rail doesn't build every page on the way (a page's first frame is the expensive one).
 */
@OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)
@Composable
private fun Rail(page: Page, items: List<androidx.compose.ui.focus.FocusRequester>, connected: Boolean, forceOpen: Boolean,
                 onRest: (Page) -> Unit, onPick: (Page) -> Unit) {
    var focused by remember { mutableStateOf(false) }
    val open by androidx.compose.animation.core.animateFloatAsState(if (focused || forceOpen) 1f else 0f, tween(if (focused) 220 else 160), label = "rail")
    var at by remember { mutableStateOf<Page?>(null) }
    val rest by rememberUpdatedState(onRest)
    LaunchedEffect(at) { at?.let { delay(RAIL_REST_MS); rest(it) } }
    // a dimmed backdrop behind the names (one cached layer; at alpha 0 it isn't drawn at all)
    Box(Modifier.fillMaxHeight().fillMaxWidth(.7f).graphicsLayer { alpha = open }
        .background(Brush.horizontalGradient(listOf(Hub.bg.copy(alpha = .85f), Color.Transparent))))
    Column(Modifier.fillMaxHeight().padding(start = 10.dp, top = 86.dp, bottom = 22.dp)
        .onFocusChanged { focused = it.hasFocus }
        // entering the rail lands on the page you're on, not whichever item happens to be level with you
        .focusProperties { enter = { items[page.ordinal] } }.focusGroup(),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (p in Page.entries) RailItem(p, page == p, { open }, items[p.ordinal], onFocus = { at = p }, onClick = { onPick(p) })
        Spacer(Modifier.weight(1f))
        Text(if (connected) "Live" else "Reconnecting…", style = Hub.text(9.sp, if (connected) Hub.ok else Hub.bad), maxLines = 1, softWrap = false,
            modifier = Modifier.padding(start = 14.dp).wrapContentWidth(Alignment.Start, unbounded = true).graphicsLayer { alpha = open })
    }
}

@Composable
private fun RailItem(p: Page, selected: Boolean, open: () -> Float, focus: androidx.compose.ui.focus.FocusRequester,
                     onFocus: () -> Unit, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    val ink = if (selected || focused) Hub.ink else Hub.ink2
    // laid out icon-sized (focus moves by these bounds); the name and the widened highlight draw past them
    Box(Modifier.size(RAIL_PILL, RAIL_ITEM).focusRequester(focus)
        .onFocusChanged { focused = it.isFocused; if (it.isFocused) onFocus() }
        .clickable(interactionSource = null, indication = null, onClick = onClick)
        .drawBehind {
            val fill = if (focused && selected) .2f else if (focused) .16f else if (selected) .1f else 0f
            if (fill > 0f) drawRoundRect(Color.White.copy(alpha = fill), size = Size(lerp(RAIL_PILL.toPx(), RAIL_OPEN.toPx(), open()), size.height),
                cornerRadius = CornerRadius(size.height / 2))
        }, contentAlignment = Alignment.CenterStart) {
        HubIcon(p.icon, ink, 18.dp, Modifier.padding(start = 19.dp))
        Text(p.label, style = Hub.text(12.sp, ink, 500), maxLines = 1, softWrap = false,
            modifier = Modifier.padding(start = 50.dp).wrapContentWidth(Alignment.Start, unbounded = true).graphicsLayer { alpha = open() })
    }
}

/** The page takes its light from the lamps (and the album art, only when that's the chosen colours), like the Hub's. */
fun ambientColours(ctx: Ctx): List<Color> {
    val music = ctx.on(Ids.SYNC) && ctx.s[Ids.NOW]?.str("player_state") == "playing" && ctx.s[Ids.COLOURS]?.state == "Album art"
    val pal = if (music) ctx.s[Ids.NOW]?.arr("palette")?.map { hex(it.toString().trim('"')) } ?: emptyList() else emptyList()
    val lamps = Ids.lights.filter { ctx.on(it.first) }.map { lightColor(ctx.s[it.first]) }
    val pool = pal + lamps
    val hour = LocalDateTime.now().hour
    val fallback = if (hour >= 21 || hour < 6) listOf(Color(60, 50, 140), Color(20, 70, 120), Color(90, 40, 90))
    else listOf(Color(255, 150, 80), Color(110, 80, 230), Color(40, 150, 190))
    return List(3) { pool.getOrNull(it) ?: pool.getOrNull(it % pool.size.coerceAtLeast(1)) ?: fallback[it] }
}

/**
 * The latest [colours], looked at every [everyMs] (outside composition, so nothing recomposes when a lamp changes in
 * between). During music sync the lamps change several times a second; following each change restarted the glow's
 * colour fade and redrew its full-screen gradients every frame, which starved the UI thread (the rail felt laggy).
 */
@Composable
fun settled(everyMs: Long = 4000, colours: () -> List<Color>): List<Color> {
    var shown by remember { mutableStateOf(Snapshot.withoutReadObservation(colours)) }
    val latest by rememberUpdatedState(colours)
    LaunchedEffect(Unit) { while (true) { delay(everyMs); val c = latest(); if (c != shown) shown = c } }
    return shown
}

private const val AMBIENT_FADE_MS = 2500L
private const val AMBIENT_DRIFT_MS = 60_000L

/**
 * The glow behind everything: three soft lights in the lamps' colours, drifting so slowly it's barely noticed. It moves
 * about 2 px a second, so it's stepped twice a second (and colour fades ten times a second) instead of asking for 60
 * frames a second forever: every frame redraws the whole window, and on this TV that alone kept the UI thread busy.
 * The three lights are drawn together into one offscreen layer, so other frames (focus moves, the rail) only copy a
 * texture instead of filling three overscanned full-screen gradients. Paused while the screensaver covers it.
 */
@Composable
fun Ambient(colours: List<Color>) {
    val covered = LocalCovered.current
    val target by rememberUpdatedState(colours)
    val shown = remember { mutableStateOf(colours) }
    val drift = remember { mutableFloatStateOf(-1f) }
    LaunchedEffect(Unit) {
        val t0 = SystemClock.uptimeMillis()
        var from = shown.value; var to = from; var since = 0L
        while (true) {
            if (covered.value) snapshotFlow { covered.value }.first { !it }
            val now = SystemClock.uptimeMillis()
            if (target != to) { from = shown.value; to = target; since = now }
            val f = ((now - since) / AMBIENT_FADE_MS.toFloat()).coerceIn(0f, 1f)
            shown.value = if (f < 1f) List(3) { lerp(from[it], to[it], f) } else to
            val phase = (now - t0) % (2 * AMBIENT_DRIFT_MS) / AMBIENT_DRIFT_MS.toFloat() // 0..2: across and back
            drift.floatValue = if (phase < 1f) -1f + 2f * phase else 3f - 2f * phase
            delay(if (f < 1f) 100 else 500)
        }
    }
    Box(Modifier.fillMaxSize().graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }.drawWithCache {
        val c = shown.value
        fun blob(i: Int, x: Float, y: Float, r: Float, alpha: Float) =
            Brush.radialGradient(listOf(c[i].copy(alpha = alpha), Color.Transparent), Offset(size.width * x, size.height * y), size.width * r)
        val lights = listOf(blob(0, .12f, .05f, .55f, .42f), blob(1, .95f, .9f, .5f, .36f), blob(2, .6f, .25f, .35f, .2f))
        onDrawBehind {
            val d = drift.floatValue
            val moves = listOf(Offset(d * 30.dp.toPx(), 0f), Offset(-d * 35.dp.toPx(), 0f), Offset(0f, d * 20.dp.toPx()))
            // the light moves; the rectangle it fills stays on the screen (no edge can slide into view)
            for (i in 0..2) translate(moves[i].x, moves[i].y) { drawRect(lights[i], topLeft = -moves[i], size = size) }
        }
    })
}

private val DAY = DateTimeFormatter.ofPattern("EEEE d MMMM")
private val HM = DateTimeFormatter.ofPattern("HH:mm")
private val SS = DateTimeFormatter.ofPattern("ss")

/** The time, updated on each minute: for what shows the hour or the date (so it doesn't recompose every second). */
@Composable
fun rememberMinute(): androidx.compose.runtime.State<LocalDateTime> = produceState(LocalDateTime.now()) {
    while (true) { delay(60_000L - System.currentTimeMillis() % 60_000L + 20); value = LocalDateTime.now() }
}

/** The ticking clock on its own, so each second redraws two short texts, not the header. */
@Composable
private fun Clock() {
    val now by produceState(LocalDateTime.now()) { while (true) { delay(1000L - System.currentTimeMillis() % 1000L + 5); value = LocalDateTime.now() } }
    Row(verticalAlignment = Alignment.Bottom) {
        Text(now.format(HM), style = Hub.text(30.sp, weight = 500, family = Hub.mono))
        Text(now.format(SS), style = Hub.text(13.sp, Hub.ink3, family = Hub.mono), modifier = Modifier.padding(start = 3.dp, bottom = 4.dp))
    }
}

@Composable
fun Header(ctx: Ctx, connected: Boolean, accent: Color, offline: String? = null) {
    val now by rememberMinute()
    val h = now.hour
    val hello = if (h < 5) "Still up" else if (h < 12) "Good morning" else if (h < 18) "Good afternoon" else "Good evening"
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
        Column(Modifier.weight(1f)) {
            Kicker(now.format(DAY))
            Text(buildAnnotatedString {
                append("$hello, ")
                withStyle(SpanStyle(fontStyle = FontStyle.Italic, color = accent.copy(alpha = .95f))) { append("Sid") }
            }, style = Hub.text(32.sp, family = Hub.serif, spacing = (-0.5).sp))
        }
        Column(horizontalAlignment = Alignment.End) {
            Clock()
            Spacer(Modifier.size(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (!connected) Chip { Dot(Hub.warn); Text(offline ?: "Offline", style = Hub.text(10.sp, Hub.ink2)) }
                when (ctx.st(Ids.HOME)) {
                    "on" -> Chip { Dot(Hub.ok); Text("Home", style = Hub.text(10.sp, weight = 600)) }
                    "off" -> Chip { Dot(Hub.bad); Text("Away · all off", style = Hub.text(10.sp, Hub.ink2)) }
                }
                ctx.s[Ids.WEATHER]?.let { w ->
                    Chip {
                        HubIcon(weatherIcon(w.state), Hub.ink2, 11.dp)
                        Text("${w.num("temperature")?.toInt() ?: "–"}°", style = Hub.text(10.sp, weight = 600))
                        Text(weatherLabel(w.state), style = Hub.text(10.sp, Hub.ink2))
                    }
                }
                ctx.s[Ids.OUTDOOR]?.let { o ->
                    Chip { HubIcon(HubIcons.sun, Hub.ink2, 11.dp); Text("Outside", style = Hub.text(10.sp, Hub.ink2)); Text("${o.state}%", style = Hub.text(10.sp, weight = 600)) }
                }
            }
        }
    }
}

@Composable
fun Dot(c: Color) = Box(Modifier.size(6.dp).clip(CircleShape).background(c))

fun weatherIcon(s: String) = when (s) {
    "sunny", "clear-night" -> HubIcons.sun; "partlycloudy" -> HubIcons.partly; "rainy", "pouring" -> HubIcons.rain
    "fog" -> HubIcons.fog; "snowy", "snowy-rainy" -> HubIcons.snow; "lightning", "lightning-rainy" -> HubIcons.storm; else -> HubIcons.cloud
}

fun weatherLabel(s: String) = when (s) {
    "clear-night" -> "Clear"; "partlycloudy" -> "Partly cloudy"; "rainy" -> "Rain"; "pouring" -> "Heavy rain"; "snowy" -> "Snow"
    "snowy-rainy" -> "Sleet"; "lightning", "lightning-rainy" -> "Storms"; "windy", "windy-variant" -> "Windy"
    else -> s.replaceFirstChar { it.uppercase() }
}

