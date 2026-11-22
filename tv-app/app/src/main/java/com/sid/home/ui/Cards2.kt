package com.sid.home.ui

import androidx.compose.animation.Crossfade
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Switch
import androidx.tv.material3.SwitchDefaults
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import coil.imageLoader
import androidx.compose.runtime.produceState
import androidx.compose.ui.layout.onSizeChanged
import coil.request.ImageRequest
import com.sid.home.BuildConfig
import com.sid.home.ha.data
import com.sid.home.ha.eventStart
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

object Ids2 {
    const val SUN = "sun.sun"
    const val T_K = "sensor.desk_lamp_target_colour"
    const val T_B = "sensor.desk_lamp_target_brightness"
    const val ADAPT = "input_boolean.desk_lamp_adaptive"
    const val HOLD = "timer.desk_lamp_manual"
    const val MAXB = "input_number.desk_lamp_max_brightness"
    const val HEALTH = "sensor.system_health"
    const val INVEST = "sensor.investments"
    const val T212 = "sensor.trading212"
    const val TASKS = "sensor.core_tasks"
    const val BONDS = "sensor.premium_bonds"
    const val PHOTOS = "sensor.photo_frame"
    const val LIBRARY = "sensor.photo_library"
    const val GUEST = "input_boolean.guest_photos"
}

private val zone = ZoneId.systemDefault()
fun parseTime(s: String?): LocalDateTime? = s?.let {
    runCatching { OffsetDateTime.parse(it).atZoneSameInstant(zone).toLocalDateTime() }.getOrNull()
        ?: runCatching { LocalDateTime.parse(it) }.getOrNull()
}

fun ago(from: LocalDateTime?): String {
    if (from == null) return "never"
    val m = Duration.between(from, LocalDateTime.now()).toMinutes()
    return if (m < 1) "just now" else if (m < 60) "$m min ago" else if (m < 1440) "${m / 60} h ago" else "${m / 1440} d ago"
}

/** The Hub's colour for a calendar: a hue from its id (hueOf in app.js). */
fun hueOf(s: String): Float = s.fold(7) { h, c -> (h * 31 + c.code) % 360 }.toFloat()

// ── Calendar ──────────────────────────────────────────────────────
@Composable
fun CalendarCard(ctx: Ctx, events: List<JsonObject>) {
    val now = LocalDateTime.now()
    fun start(e: JsonObject) = parseTime(eventStart(e)) ?: now
    fun end(e: JsonObject): LocalDateTime {
        val s = e["end"]?.jsonObject ?: return start(e)
        return parseTime(s["dateTime"]?.jsonPrimitive?.contentOrNull ?: (s["date"]?.jsonPrimitive?.contentOrNull + "T00:00:00")) ?: start(e)
    }
    val timed = { e: JsonObject -> e["start"]?.jsonObject?.get("dateTime") != null }
    val next = events.firstOrNull { timed(it) && end(it).isAfter(now) }
    val kicker = next?.let {
        val title = it["summary"]?.jsonPrimitive?.contentOrNull ?: "Busy"
        if (!start(it).isAfter(now)) "Now · $title" else {
            val mins = Duration.between(now, start(it)).toMinutes()
            "Next · $title " + if (mins < 60) "in $mins min" else if (mins < 1440) "in ${mins / 60}h ${mins % 60}m" else ""
        }
    } ?: "${events.size} this week"
    HubCard {
        CardHead("Calendar", HubIcons.cal) { Kicker(kicker) }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (i in 0 until 7) {
                val day = LocalDate.now().plusDays(i.toLong())
                val dayStart = day.atStartOfDay(); val dayEnd = dayStart.plusDays(1)
                val evs = events.filter { start(it).isBefore(dayEnd) && end(it).isAfter(dayStart) }
                Column(Modifier.weight(1f).heightIn(min = 96.dp).clip(RoundedCornerShape(12.dp))
                    .background(if (i == 0) Color.White.copy(alpha = .07f) else Color.White.copy(alpha = .035f))
                    .border(1.dp, if (i == 0) Hub.line2 else Hub.line, RoundedCornerShape(12.dp)).padding(8.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(if (i == 0) "Today" else if (i == 1) "Tomorrow" else day.format(DateTimeFormatter.ofPattern("EEE")),
                            style = Hub.text(10.sp, weight = 600)); Spacer(Modifier.weight(1f))
                        Text("${day.dayOfMonth}", style = Hub.text(16.sp, Hub.ink2, family = Hub.serif))
                    }
                    if (evs.isEmpty()) Text("Free", style = Hub.text(8.sp, Hub.ink3))
                    for (e in evs.take(3)) {
                        val cal = e["cal"]?.jsonPrimitive?.contentOrNull ?: ""
                        val c = Color.hsv(hueOf(cal), .55f, .95f)
                        val past = timed(e) && !end(e).isAfter(now)
                        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(6.dp)).background(c.copy(alpha = if (past) .06f else .14f))) {
                            Box(Modifier.width(2.dp).height(30.dp).background(c.copy(alpha = if (past) .4f else 1f)))
                            Column(Modifier.padding(horizontal = 5.dp, vertical = 3.dp)) {
                                if (timed(e)) Text(start(e).format(DateTimeFormatter.ofPattern("HH:mm")), style = Hub.text(7.sp, Hub.ink3, family = Hub.mono))
                                Text(e["summary"]?.jsonPrimitive?.contentOrNull ?: "Busy", style = Hub.text(8.5.sp, if (past) Hub.ink3 else Hub.ink, 500),
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                    if (evs.size > 3) Text("+${evs.size - 3} more", style = Hub.text(7.sp, Hub.ink3))
                }
            }
        }
    }
}

// ── Photos ────────────────────────────────────────────────────────
fun photoList(ctx: Ctx): List<JsonObject> = ctx.s[Ids2.PHOTOS]?.arr("photos")?.map { it.jsonObject } ?: emptyList()

fun photoUrl(p: JsonObject): String? {
    val path = (p["tv"] ?: p["src"])?.jsonPrimitive?.contentOrNull ?: return null
    return if (path.startsWith("http")) path else BuildConfig.HA_URL + path
}

/**
 * The frame's photos; offline, only those already on the TV's disk (a blank frame is worse than the quote). That check
 * reads the disk, so it runs off the main thread.
 */
@Composable
fun rememberShownPhotos(ctx: Ctx, connected: Boolean): List<JsonObject> {
    val all = photoList(ctx)
    if (connected) return all
    val context = LocalContext.current
    return produceState(emptyList<JsonObject>(), all) {
        value = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            all.filter { p -> photoUrl(p)?.let { PhotoCache.isCached(context, it) } == true }
        }
    }.value
}

/**
 * A cross-fading photo frame (the Hub's Memories card, and the screensaver's background). The next photo is decoded
 * ahead, at the frame's size, so each cross-fade starts from a ready picture (it used to fade towards an empty frame
 * and pop the photo in mid-fade, while the TV decoded it).
 */
@Composable
fun PhotoFrame(photos: List<JsonObject>, every: Long, modifier: Modifier = Modifier, label: Boolean = true) {
    var i by remember(photos) { mutableIntStateOf((0 until maxOf(photos.size, 1)).random()) }
    val context = LocalContext.current
    var px by remember { mutableStateOf(androidx.compose.ui.unit.IntSize.Zero) }
    LaunchedEffect(photos, px) {
        while (photos.isNotEmpty()) {
            if (px != androidx.compose.ui.unit.IntSize.Zero) photoUrl(photos[(i + 1) % photos.size])?.let { url ->
                context.imageLoader.enqueue(ImageRequest.Builder(context).data(url).size(px.width, px.height).scale(coil.size.Scale.FILL).build())
            }
            delay(every); i = (i + 1) % photos.size
        }
    }
    Box(modifier.onSizeChanged { px = it }) {
        Crossfade(photos.getOrNull(i), animationSpec = tween(1600), label = "photo") { p ->
            if (p != null) AsyncImage(ImageRequest.Builder(context).data(photoUrl(p)).crossfade(false).build(), null,
                contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
        val caption = photos.getOrNull(i)?.get("label")?.jsonPrimitive?.contentOrNull
        if (label && !caption.isNullOrBlank()) Text(caption.uppercase(), style = Hub.kicker.copy(color = Color.White.copy(alpha = .75f)),
            modifier = Modifier.align(Alignment.BottomEnd).padding(14.dp), maxLines = 1)
    }
}

@Composable
fun PhotosCard(ctx: Ctx, modifier: Modifier = Modifier) {
    val photos = photoList(ctx)
    if (photos.isEmpty()) return
    val guest = ctx.s[Ids2.PHOTOS]?.bool("guest") == true
    Box(modifier.fillMaxWidth().heightIn(min = 200.dp).clip(RoundedCornerShape(Hub.radius)).border(1.dp, Hub.line, RoundedCornerShape(Hub.radius))) {
        PhotoFrame(photos, 10_000, Modifier.fillMaxSize())
        Box(Modifier.fillMaxWidth().height(60.dp).background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = .45f), Color.Transparent))))
        Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (guest) "Landscapes" else "Memories", style = Hub.text(12.sp, Color.White, 600)); Spacer(Modifier.weight(1f))
            Pressable(onClick = { ctx.act.callService("input_boolean", "toggle", data("entity_id" to Ids2.GUEST)) }, shape = CircleShape,
                color = if (ctx.on(Ids2.GUEST)) Color.White else Color.Black.copy(alpha = .35f), focusedColor = if (ctx.on(Ids2.GUEST)) Color.White else Color.White.copy(alpha = .3f)) {
                Text("GUEST", style = Hub.kicker.copy(color = if (ctx.on(Ids2.GUEST)) Hub.bg else Color.White), modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp))
            }
        }
    }
}

// ── Desk lamp and the sky ─────────────────────────────────────────
@Composable
fun DeskCard(ctx: Ctx, modifier: Modifier = Modifier) {
    val sun = ctx.s[Ids2.SUN]
    val elev = sun?.num("elevation") ?: 0.0
    val az = sun?.num("azimuth") ?: 180.0
    val day = elev > 0
    val sunCol = if (elev > 10) Color(0xFFFFF3C4) else if (elev > -2) Color(0xFFFFAB5E) else Color(0xFFB9C3FF)
    val w = ctx.s[Ids.WEATHER]
    val lamp = ctx.s[Ids.DESK]
    val lampK = if (lamp?.state == "on" && lamp.str("color_mode") == "color_temp") lamp.num("color_temp_kelvin") else null
    val tk = ctx.s[Ids2.T_K]?.number
    val hold = ctx.st(Ids2.HOLD) == "active"
    val maxb = ctx.s[Ids2.MAXB]?.number ?: 55.0
    HubCard(modifier) {
        CardHead("Desk", HubIcons.lamp) { Kicker(if (ctx.on(Ids2.ADAPT)) (if (hold) "Manual hold" else "Adaptive") else "Manual") }
        Canvas(Modifier.fillMaxWidth().height(86.dp)) {
            val sx = size.width / 300f; val sy = size.height / 120f
            val arc = Path().apply { moveTo(20 * sx, 100 * sy); quadraticTo(150 * sx, -40 * sy, 280 * sx, 100 * sy) }
            drawPath(arc, Hub.ink3, style = Stroke(1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4f, 6f))))
            drawLine(Hub.line2, Offset(0f, 100 * sy), Offset(size.width, 100 * sy), 1.dp.toPx())
            val x = (20 + 260 * ((az - 45) / 270).coerceIn(0.0, 1.0)).toFloat() * sx
            val y = (if (elev >= 0) 100 - 84 * (elev / 62).coerceIn(0.0, 1.0) else 100 + (-elev).coerceIn(0.0, 18.0)).toFloat() * sy
            val r = (if (day) 34 else 18) * sx
            drawCircle(Brush.radialGradient(listOf(sunCol.copy(alpha = if (day) .9f else .45f), Color.Transparent), Offset(x, y), r), r, Offset(x, y))
            drawCircle(sunCol.copy(alpha = if (day) 1f else .7f), (if (day) 7 else 5) * sx, Offset(x, y))
        }
        Row(Modifier.fillMaxWidth()) {
            Text("E", style = Hub.text(8.sp, Hub.ink3, family = Hub.mono)); Spacer(Modifier.weight(1f))
            Text("S", style = Hub.text(8.sp, Hub.ink3, family = Hub.mono)); Spacer(Modifier.weight(1f))
            Text("W   ${if (elev >= 0) "+" else ""}${"%.1f".format(elev)}°", style = Hub.text(8.sp, Hub.ink3, family = Hub.mono))
        }
        Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            HubIcon(weatherIcon(w?.state ?: ""), Hub.ink, 22.dp); Spacer(Modifier.width(8.dp))
            Text("${w?.num("temperature")?.toInt() ?: "—"}°", style = Hub.text(26.sp, family = Hub.serif)); Spacer(Modifier.width(10.dp))
            Column {
                Text(weatherLabel(w?.state ?: "—"), style = Hub.text(10.sp, Hub.ink2))
                Text("Cloud ${w?.num("cloud_coverage")?.toInt() ?: 0}% · light outside ${ctx.st(Ids.OUTDOOR) ?: "—"}%", style = Hub.text(9.sp, Hub.ink3))
            }
        }
        Box(Modifier.fillMaxWidth().height(8.dp).clip(CircleShape)
            .background(Brush.horizontalGradient(listOf(Color(0xFFFF9A3C), Color(0xFFFFD9A8), Color(0xFFE8EEFF), Color(0xFFBFD3FF))))) {
            fun pos(k: Double) = ((k - 2200) / 4300).coerceIn(0.0, 1.0).toFloat()
            tk?.let { Box(Modifier.fillMaxWidth(pos(it).coerceAtLeast(.02f)), contentAlignment = Alignment.CenterEnd) { Box(Modifier.size(8.dp).clip(CircleShape).background(Color.White).border(2.dp, Hub.bg, CircleShape)) } }
            lampK?.let { Box(Modifier.fillMaxWidth(pos(it).coerceAtLeast(.02f)), contentAlignment = Alignment.CenterEnd) { Box(Modifier.size(width = 2.dp, height = 8.dp).background(Hub.bg)) } }
        }
        Row(Modifier.fillMaxWidth().padding(top = 3.dp)) {
            Text("2200K candle", style = Hub.text(7.sp, Hub.ink3, family = Hub.mono)); Spacer(Modifier.weight(1f))
            Text("daylight 6500K", style = Hub.text(7.sp, Hub.ink3, family = Hub.mono))
        }
        Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Stat("Colour", tk?.toInt()?.toString() ?: "—", "K", Modifier.weight(1f))
            Stat("Bright", ctx.st(Ids2.T_B) ?: "—", "%", Modifier.weight(1f))
            Stat("Hold", if (hold) "on" else "—", "", Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Follow the sky", style = Hub.text(10.sp, Hub.ink2)); Spacer(Modifier.weight(1f))
            Switch(checked = ctx.on(Ids2.ADAPT), onCheckedChange = { ctx.act.callService("input_boolean", "toggle", data("entity_id" to Ids2.ADAPT)) },
                colors = SwitchDefaults.colors(checkedTrackColor = Hub.accent))
        }
        Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Max brightness", style = Hub.text(10.sp, Hub.ink2)); Spacer(Modifier.width(10.dp))
            RemoteSlider(maxb.toFloat(), range = 15f..100f, modifier = Modifier.weight(1f),
                onCommit = { ctx.act.callService("input_number", "set_value", data("entity_id" to Ids2.MAXB, "value" to it.toInt())) })
            Text("${maxb.toInt()}%", style = Hub.text(9.sp, Hub.ink2, family = Hub.mono), modifier = Modifier.padding(start = 6.dp))
        }
    }
}

@Composable
fun Stat(label: String, value: String, unit: String, modifier: Modifier = Modifier) =
    Column(modifier.clip(RoundedCornerShape(Hub.radiusSm)).background(Color.White.copy(alpha = .04f)).border(1.dp, Hub.line, RoundedCornerShape(Hub.radiusSm)).padding(8.dp)) {
        Kicker(label)
        Row(verticalAlignment = Alignment.Bottom) {
            Text(value, style = Hub.text(14.sp, weight = 500, family = Hub.mono)); Text(unit, style = Hub.text(8.sp, Hub.ink3), modifier = Modifier.padding(start = 2.dp, bottom = 2.dp))
        }
    }

// ── System health ─────────────────────────────────────────────────
private enum class Lvl(val c: Color) { OK(Hub.ok), WARN(Hub.warn), BAD(Hub.bad), IDLE(Hub.ink3) }

@Composable
fun HealthCard(ctx: Ctx, connected: Boolean, calendars: Int, modifier: Modifier = Modifier) {
    val h = ctx.s[Ids2.HEALTH]
    val updated = parseTime(h?.str("updated"))
    val hAge = updated?.let { Duration.between(it, LocalDateTime.now()).seconds } ?: Long.MAX_VALUE
    val supOk = h != null && h.state != "stopped" && hAge < 180
    val services = h?.obj("services")
    val hour = LocalDateTime.now().hour
    val daytime = hour in 7..21
    fun svc(key: String, label: String, missing: String = "Not set up", okDetail: () -> String): Triple<Lvl, String, String> {
        if (!supOk) return Triple(Lvl.IDLE, label, "Unknown while the supervisor isn't reporting")
        val sv = services?.get(key)?.jsonObject ?: return Triple(Lvl.IDLE, label, missing)
        val state = sv["state"]?.jsonPrimitive?.contentOrNull
        val restarts = sv["restarts"]?.jsonPrimitive?.contentOrNull?.toIntOrNull() ?: 0
        val rs = if (restarts > 0) " · restarted $restarts×" else ""
        return when (state) {
            "running" -> Triple(if (restarts >= 3) Lvl.WARN else Lvl.OK, label, okDetail() + rs)
            "restarting" -> Triple(Lvl.WARN, label, "Restarting$rs")
            else -> Triple(Lvl.BAD, label, "Stopped")
        }
    }
    fun feed(label: String, id: String, key: String, limitDay: Long, limitNight: Long): Triple<Lvl, String, String> {
        val e = ctx.s[id] ?: return Triple(Lvl.IDLE, label, "Not set up")
        if (e.str("status") == "paused") return Triple(Lvl.BAD, label, "Paused: ${e.str("paused_reason").orEmpty().take(80)}")
        val sv = services?.get(key)?.jsonObject
        if (supOk && sv?.get("state")?.jsonPrimitive?.contentOrNull != "running") return Triple(Lvl.BAD, label, "Service not running")
        val t = parseTime(e.str("updated"))
        val mins = t?.let { Duration.between(it, LocalDateTime.now()).toMinutes() } ?: Long.MAX_VALUE
        val stale = mins > (if (daytime) limitDay else limitNight)
        return Triple(if (stale) Lvl.WARN else Lvl.OK, label, (if (stale) "Last refresh " else "Refreshed ") + ago(t))
    }
    val sup = when {
        h == null -> Triple(Lvl.WARN, "Supervisor", "Not running")
        h.state == "stopped" -> Triple(Lvl.BAD, "Supervisor", "Stopped")
        hAge > 180 -> Triple(Lvl.BAD, "Supervisor", "Not reporting · last seen ${ago(updated)}")
        else -> {
            val host = h.obj("host")
            val load = host?.get("load1")?.jsonPrimitive?.contentOrNull
            val disk = host?.get("disk_free_pct")?.jsonPrimitive?.contentOrNull?.toDoubleOrNull()
            val since = parseTime(h.str("supervisor_since"))
            val up = since?.let { Duration.between(it, LocalDateTime.now()) }
            val upS = up?.let { if (it.toHours() < 48) "${it.toHours()} h" else "${it.toDays()} d" } ?: "—"
            Triple(if (disk != null && disk < 5) Lvl.BAD else Lvl.OK, "Supervisor", "Up $upS" + (load?.let { " · load $it" } ?: "") + (disk?.let { " · ${it.toInt()}% disk free" } ?: ""))
        }
    }
    val lib = ctx.s[Ids2.LIBRARY]
    val bonds = ctx.s[Ids2.BONDS]
    val tvE = ctx.s[Ids.TV]
    val down = Ids.lights.filter { ctx.s[it.first] == null || ctx.st(it.first) == "unavailable" }
    val tiles = listOf(
        if (connected) Triple(Lvl.OK, "Home Assistant", "Connected") else Triple(Lvl.BAD, "Home Assistant", "Reconnecting…"),
        sup,
        svc("music_sync", "Music sync", "Not running") { if (ctx.on(Ids.SYNC)) "Following the music · ${ctx.st(Ids.MODE)}" else "Idle, ready" },
        svc("announce", "Voice", "Not running") { "Ready to speak" },
        svc("presence", "Presence") { if (ctx.on(Ids.HOME)) "Home" else if (ctx.st(Ids.HOME) == "off") "Away · lights off" else "Running" },
        svc("core", "State service", "Not running") { "Serving the API" },
        svc("tasks", "Task worker", "Not running") { val n = ctx.st(Ids2.TASKS)?.toIntOrNull() ?: 0; if (n > 0) "Running $n task${if (n > 1) "s" else ""}" else "Idle, ready" },
        feed("Hargreaves Lansdown", Ids2.INVEST, "investments", 180, 540),
        feed("Trading 212", Ids2.T212, "investments", 90, 300),
        svc("photos", "Photos", "Not running") {
            val n = ctx.st(Ids2.PHOTOS)?.toIntOrNull() ?: 0
            (if (n > 0) "$n ${if (ctx.on(Ids2.GUEST)) "guest landscapes" else "on the frame"}" else "No set yet") +
                (lib?.let { if ((it.num("remaining") ?: 0.0) > 0) " · ${it.state}% of library looked at" else " · whole library looked at" } ?: "")
        },
        when {
            bonds == null || bonds.state == "not set up" -> Triple(Lvl.IDLE, "Premium Bonds", "Not set up · needs the holder number")
            bonds.state == "error" -> Triple(Lvl.WARN, "Premium Bonds", "Check failed")
            bonds.state == "waiting" -> Triple(Lvl.IDLE, "Premium Bonds", "Waiting for the first draw check")
            else -> Triple(Lvl.OK, "Premium Bonds", (if (bonds.state == "won") "Prize" else "No prize") + " · checked ${ago(parseTime(bonds.str("last_checked")))}")
        },
        if (calendars == 0) Triple(Lvl.IDLE, "Calendar", "Not connected") else Triple(Lvl.OK, "Calendar", "$calendars calendar${if (calendars > 1) "s" else ""}"),
        ctx.s[Ids.WEATHER]?.let { Triple(Lvl.OK, "Weather", "${it.num("temperature")?.toInt()}° · ${weatherLabel(it.state)}") } ?: Triple(Lvl.WARN, "Weather", "No data"),
        if (down.isEmpty()) Triple(Lvl.OK, "Bulbs", "All ${Ids.lights.size} reachable") else if (down.size == Ids.lights.size) Triple(Lvl.BAD, "Bulbs", "None reachable")
        else Triple(Lvl.WARN, "Bulbs", "${down.joinToString { it.second }} unreachable"),
        if (tvE == null || tvE.state == "unavailable") Triple(Lvl.WARN, "TV", "Unreachable") else Triple(Lvl.OK, "TV", if (tvE.state == "on") "On" else "Standby"),
    )
    val bad = tiles.count { it.first == Lvl.BAD }; val warn = tiles.count { it.first == Lvl.WARN }
    HubCard(modifier) {
        CardHead("System health", HubIcons.pulse) {
            val (c, t) = if (bad > 0) Hub.bad to "$bad problem${if (bad > 1) "s" else ""}" else if (warn > 0) Hub.warn to "$warn to check" else Hub.ok to "All systems normal"
            Chip { Dot(c); Text(t, style = Hub.text(9.sp, weight = 500)) }
        }
        for (row in tiles.chunked(3)) Row(Modifier.fillMaxWidth().padding(bottom = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((lvl, name, detail) in row) Row(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(Color.White.copy(alpha = .035f))
                .border(1.dp, Hub.line, RoundedCornerShape(12.dp)).padding(8.dp)) {
                Box(Modifier.padding(top = 3.dp).size(6.dp).clip(CircleShape).background(lvl.c)); Spacer(Modifier.width(7.dp))
                Column {
                    Text(name, style = Hub.text(9.5.sp, weight = 600), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(detail, style = Hub.text(8.sp, Hub.ink3), maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
            repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
        }
        val dayAgo = LocalDateTime.now().minusDays(1)
        val recent = ctx.s[Ids2.TASKS]?.arr("recent")?.map { it.jsonObject }?.filter {
            val st = it["status"]?.jsonPrimitive?.contentOrNull
            st == "running" || st == "queued" || (parseTime((it["finished_at"] ?: it["created_at"])?.jsonPrimitive?.contentOrNull)?.isAfter(dayAgo) ?: false)
        }?.take(5).orEmpty()
        if (recent.isNotEmpty()) {
            Kicker("Background tasks", modifier = Modifier.padding(top = 6.dp, bottom = 4.dp))
            for (t in recent) {
                val st = t["status"]?.jsonPrimitive?.contentOrNull ?: ""
                val c = when (st) { "running", "done" -> Hub.ok; "failed" -> Hub.bad; else -> Hub.ink3 }
                val right = when (st) {
                    "running" -> "${((t["progress"]?.jsonPrimitive?.contentOrNull?.toDoubleOrNull() ?: 0.0) * 100).toInt()}% · ${t["message"]?.jsonPrimitive?.contentOrNull ?: "working"}"
                    "queued" -> "Queued"
                    else -> "${st.replaceFirstChar { it.uppercase() }} ${ago(parseTime(t["finished_at"]?.jsonPrimitive?.contentOrNull))}"
                }
                Row(Modifier.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    Dot(c); Spacer(Modifier.width(7.dp))
                    Text(t["title"]?.jsonPrimitive?.contentOrNull ?: "", style = Hub.text(9.sp, weight = 500), modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(right, style = Hub.text(8.sp, Hub.ink3))
                }
            }
        }
    }
}

