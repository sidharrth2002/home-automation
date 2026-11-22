package com.sid.home.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.ui.draw.clip
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import com.sid.home.ha.eventStart
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.Duration
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * The home page's quiet middle. With something still on today: what's next. With nothing left: the photo frame (your
 * photos, or the landscapes in guest mode), cross-fading slowly. Either way the weather and the lights in one line.
 */
@Composable
fun NowPanel(ctx: Ctx, events: List<JsonObject>, modifier: Modifier = Modifier, connected: Boolean = true) {
    val now = LocalDateTime.now()
    val next = events.firstOrNull { it["start"]?.jsonObject?.get("dateTime") != null &&
        (parseTime(it["end"]?.jsonObject?.get("dateTime")?.jsonPrimitive?.contentOrNull) ?: now).isAfter(now) }
    // offline, only the photos already on the TV (a blank frame is worse than the quote)
    val context = androidx.compose.ui.platform.LocalContext.current
    val photos = photoList(ctx).let { all -> if (connected) all else all.filter { p -> photoUrl(p)?.let { PhotoCache.isCached(context, it) } == true } }
    if (next == null && photos.isNotEmpty()) {
        androidx.compose.foundation.layout.Box(modifier.clip(androidx.compose.foundation.shape.RoundedCornerShape(Hub.radius))
            .border(1.dp, Hub.line, androidx.compose.foundation.shape.RoundedCornerShape(Hub.radius))) {
            PhotoFrame(photos, 20_000, Modifier.fillMaxSize(), label = false)
            androidx.compose.foundation.layout.Box(Modifier.fillMaxWidth().height(90.dp).align(Alignment.BottomCenter)
                .background(androidx.compose.ui.graphics.Brush.verticalGradient(listOf(androidx.compose.ui.graphics.Color.Transparent,
                    androidx.compose.ui.graphics.Color.Black.copy(alpha = .55f)))))
            androidx.compose.foundation.layout.Box(Modifier.align(Alignment.BottomStart).padding(20.dp)) { StatusLine(ctx) }
        }
        return
    }
    HubCard(modifier, padding = 22.dp) { NowText(ctx, next, now); Spacer(Modifier.weight(1f)); StatusLine(ctx) }
}

@Composable
private fun NowText(ctx: Ctx, next: JsonObject?, now: LocalDateTime) {
    if (next == null) {
        // nothing left today: a quote instead, the same one all day (calm: it doesn't keep changing)
        val (quote, author) = COMFORT[java.time.LocalDate.now().dayOfYear % COMFORT.size]
        Kicker("For today")
        Spacer(Modifier.height(10.dp))
        Text("\u201C$quote\u201D", style = Hub.text(24.sp, family = Hub.serif).copy(fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
            lineHeight = 30.sp), maxLines = 4, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(8.dp))
        Text(author.uppercase(), style = Hub.kicker)
    } else {
        Kicker("Next")
        Spacer(Modifier.height(6.dp))
        val start = parseTime(eventStart(next)) ?: now
        val mins = Duration.between(now, start).toMinutes()
        Text(next["summary"]?.jsonPrimitive?.contentOrNull ?: "Busy", style = Hub.text(28.sp, family = Hub.serif), maxLines = 1, overflow = TextOverflow.Ellipsis)
        val loc = next["location"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }
        Text((if (mins <= 0) "Now" else if (mins < 60) "In $mins min" else start.format(DateTimeFormatter.ofPattern("EEE HH:mm"))) +
            (loc?.let { " · $it" } ?: ""), style = Hub.text(11.sp, Hub.ink2), maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** The weather and the lights, in one line. */
@Composable
private fun StatusLine(ctx: Ctx) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(18.dp)) {
        ctx.s[Ids.WEATHER]?.let { w ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                HubIcon(weatherIcon(w.state), Hub.ink2, 18.dp); Spacer(Modifier.width(7.dp))
                Text("${w.num("temperature")?.toInt() ?: "–"}°  ${weatherLabel(w.state)}", style = Hub.text(12.sp, Hub.ink2))
            }
        }
        val on = Ids.lights.filter { ctx.on(it.first) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            HubIcon(HubIcons.bulb, Hub.ink2, 16.dp); Spacer(Modifier.width(6.dp))
            Text(if (on.isEmpty()) "Lights off" else "${on.size} on" + (if (ctx.on(Ids.SYNC)) " · ${ctx.st(Ids.MODE)} sync" else ""),
                style = Hub.text(12.sp, Hub.ink2))
            for ((id) in on) { Spacer(Modifier.width(5.dp)); Dot(lightColor(ctx.s[id])) }
        }
    }
}
