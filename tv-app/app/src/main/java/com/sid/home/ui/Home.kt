package com.sid.home.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.animation.togetherWith
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.focus.focusProperties
import androidx.compose.foundation.focusGroup
import androidx.compose.ui.focus.focusRequester
import androidx.tv.material3.NavigationDrawerItem
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
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

/** Everything a card needs: the entities right now, and a way to change things. */
class Ctx(val s: Map<String, Entity>, val act: Actions, val toast: (String) -> Unit) {
    fun st(id: String) = s[id]?.state
    fun on(id: String) = s[id]?.state == "on"
}

/** The pages, each one screen: the left rail moves between them, Google TV style (no scrolling). */
enum class Page(val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector) {
    ROOM("Home", HubIcons.home), LIGHTS("Lights", HubIcons.bulb), TODAY("Today", HubIcons.cal), MONEY("Money", HubIcons.chart), ALLOCATION("Allocation", HubIcons.pin),
    HOME("Desk & health", HubIcons.pulse), SETTINGS("Settings", HubIcons.reactor)
}

/**
 * The home screen. A rail on the left (focus it with the remote's left arrow; up and down change page, and the page
 * follows the focus) and one page at a time, each fitting the TV, under the header with the clock and greeting.
 */
@OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)
@Composable
fun HomeScreen(ctx: Ctx, connected: Boolean, events: List<kotlinx.serialization.json.JsonObject> = emptyList(), start: Page = Page.ROOM,
               offline: String? = null) {
    val palette = ambientColours(ctx)
    var holding by remember { mutableStateOf<String?>(null) }
    var allApps by remember { mutableStateOf(false) }
    var page by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(start) }
    val first = remember { androidx.compose.ui.focus.FocusRequester() }
    val railItems = remember { Page.entries.map { androidx.compose.ui.focus.FocusRequester() } }
    // This is the TV's home, so Back never leaves it: it closes what's open, or goes back to the first page.
    androidx.activity.compose.BackHandler { page = Page.ROOM; runCatching { first.requestFocus() } }
    androidx.activity.compose.BackHandler(enabled = holding != null) { holding = null }
    LaunchedEffect(Unit) { runCatching { first.requestFocus() } }
    Box(Modifier.fillMaxSize().background(Hub.bg)) {
        Ambient(palette)
        // modal: the rail slides over the page (with a dimmed backdrop) instead of squeezing it
        androidx.tv.material3.ModalNavigationDrawer(scrimBrush = Brush.horizontalGradient(listOf(Hub.bg.copy(alpha = .85f), Color.Transparent)), drawerContent = { open ->
            // entering the rail lands on the page you're on, not whichever item happens to be level with you
            Column(Modifier.fillMaxHeight().focusProperties { enter = { railItems[page.ordinal] } }.focusGroup()
                .padding(horizontal = 10.dp, vertical = 24.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Spacer(Modifier.height(56.dp))
                for (p in Page.entries) {
                    NavigationDrawerItem(selected = page == p, onClick = { page = p },
                        modifier = Modifier.focusRequester(railItems[p.ordinal]).onFocusChanged { if (it.isFocused) page = p },
                        leadingContent = { HubIcon(p.icon, if (page == p) Hub.ink else Hub.ink2, 18.dp) },
                        colors = androidx.tv.material3.NavigationDrawerItemDefaults.colors(
                            containerColor = Color.Transparent, selectedContainerColor = Color.White.copy(alpha = .10f),
                            focusedContainerColor = Color.White.copy(alpha = .16f), focusedSelectedContainerColor = Color.White.copy(alpha = .2f),
                            contentColor = Hub.ink2, selectedContentColor = Hub.ink, focusedContentColor = Hub.ink),
                    ) { Text(p.label, style = Hub.text(12.sp, weight = 500)) }
                }
                Spacer(Modifier.weight(1f))
                if (open == androidx.tv.material3.DrawerValue.Open) Text(if (connected) "Live" else "Reconnecting…", style = Hub.text(9.sp, if (connected) Hub.ok else Hub.bad),
                    modifier = Modifier.padding(start = 14.dp))
            }
        }) {
            Column(Modifier.fillMaxSize().padding(start = 76.dp, end = 32.dp, top = 20.dp, bottom = 22.dp)) {
                Header(ctx, connected, palette.first(), offline)
                Spacer(Modifier.height(14.dp))
                androidx.compose.animation.AnimatedContent(page, label = "page", modifier = Modifier.weight(1f),
                    // a cross-fade only: no size animation between pages of different heights
                    transitionSpec = { (androidx.compose.animation.fadeIn(tween(220)) togetherWith androidx.compose.animation.fadeOut(tween(160))).using(null) }) { p ->
                    when (p) {
                        Page.ROOM -> Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                            AppsRow(ctx, first = first) { allApps = true }
                            Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                                NowPanel(ctx, events, Modifier.weight(1.75f).fillMaxHeight(), connected)
                                if (musicShown(ctx)) MusicCard(ctx, Modifier.weight(1f), compact = true)
                            }
                            ScenesRow(ctx)
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
        }
        holding?.let { HoldingView(ctx, it) { holding = null } }
        if (allApps) AppsGrid(ctx) { allApps = false }
    }
}

/** The page takes its light from the lamps and the album art, like the Hub's ambient field. */
fun ambientColours(ctx: Ctx): List<Color> {
    val music = ctx.on(Ids.SYNC) && ctx.s[Ids.NOW]?.str("player_state") == "playing"
    val pal = if (music) ctx.s[Ids.NOW]?.arr("palette")?.map { hex(it.toString().trim('"')) } ?: emptyList() else emptyList()
    val lamps = Ids.lights.filter { ctx.on(it.first) }.map { lightColor(ctx.s[it.first]) }
    val pool = pal + lamps
    val hour = LocalDateTime.now().hour
    val fallback = if (hour >= 21 || hour < 6) listOf(Color(60, 50, 140), Color(20, 70, 120), Color(90, 40, 90))
    else listOf(Color(255, 150, 80), Color(110, 80, 230), Color(40, 150, 190))
    return List(3) { pool.getOrNull(it) ?: pool.getOrNull(it % pool.size.coerceAtLeast(1)) ?: fallback[it] }
}

@Composable
fun Ambient(colours: List<Color>) {
    val a by animateColorAsState(colours[0], tween(2500), label = "a1")
    val b by animateColorAsState(colours[1], tween(2500), label = "a2")
    val c by animateColorAsState(colours[2], tween(2500), label = "a3")
    val t = rememberInfiniteTransition(label = "drift")
    val drift by t.animateFloat(-1f, 1f, infiniteRepeatable(tween(60_000, easing = LinearEasing), RepeatMode.Reverse), label = "d") // slow, barely noticed
    // Drawn once per colour change and cached; the drift only slides the cached layer, so the TV's GPU does almost
    // nothing per frame (redrawing big gradients every frame made the app stutter).
    fun Modifier.blob(color: Color, x: Float, y: Float, r: Float, alpha: Float) = drawWithCache {
        val brush = Brush.radialGradient(listOf(color.copy(alpha = alpha), Color.Transparent), Offset(size.width * x, size.height * y), size.width * r)
        // drawn well past the screen's edges: the layer drifts, and a screen-sized rectangle showed its edge sliding in
        val over = 160.dp.toPx()
        onDrawBehind { drawRect(brush, topLeft = Offset(-over, -over), size = androidx.compose.ui.geometry.Size(size.width + 2 * over, size.height + 2 * over)) }
    }
    Box(Modifier.fillMaxSize().graphicsLayer { translationX = drift * 30.dp.toPx() }.blob(a, .12f, .05f, .55f, .42f))
    Box(Modifier.fillMaxSize().graphicsLayer { translationX = -drift * 35.dp.toPx() }.blob(b, .95f, .9f, .5f, .36f))
    Box(Modifier.fillMaxSize().graphicsLayer { translationY = drift * 20.dp.toPx() }.blob(c, .6f, .25f, .35f, .2f))
}

@Composable
fun Header(ctx: Ctx, connected: Boolean, accent: Color, offline: String? = null) {
    var now by remember { mutableStateOf(LocalDateTime.now()) }
    LaunchedEffect(Unit) { while (true) { now = LocalDateTime.now(); delay(1000) } }
    val h = now.hour
    val hello = if (h < 5) "Still up" else if (h < 12) "Good morning" else if (h < 18) "Good afternoon" else "Good evening"
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
        Column(Modifier.weight(1f)) {
            Kicker(now.format(DateTimeFormatter.ofPattern("EEEE d MMMM")))
            Text(buildAnnotatedString {
                append("$hello, ")
                withStyle(SpanStyle(fontStyle = FontStyle.Italic, color = accent.copy(alpha = .95f))) { append("Sid") }
            }, style = Hub.text(32.sp, family = Hub.serif, spacing = (-0.5).sp))
        }
        Column(horizontalAlignment = Alignment.End) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(now.format(DateTimeFormatter.ofPattern("HH:mm")), style = Hub.text(30.sp, weight = 500, family = Hub.mono))
                Text(now.format(DateTimeFormatter.ofPattern("ss")), style = Hub.text(13.sp, Hub.ink3, family = Hub.mono),
                    modifier = Modifier.padding(start = 3.dp, bottom = 4.dp))
            }
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

