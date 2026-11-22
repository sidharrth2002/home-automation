package com.sid.home.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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

/** The home page's quiet middle: what's next, the weather, and the lights in one line (their controls are on Lights). */
@Composable
fun NowPanel(ctx: Ctx, events: List<JsonObject>, modifier: Modifier = Modifier) = HubCard(modifier, padding = 22.dp) {
    val now = LocalDateTime.now()
    val next = events.firstOrNull { it["start"]?.jsonObject?.get("dateTime") != null &&
        (parseTime(it["end"]?.jsonObject?.get("dateTime")?.jsonPrimitive?.contentOrNull) ?: now).isAfter(now) }
    Kicker("Next")
    Spacer(Modifier.height(6.dp))
    if (next == null) Text("Nothing else today", style = Hub.text(26.sp, Hub.ink2, family = Hub.serif))
    else {
        val start = parseTime(eventStart(next)) ?: now
        val mins = Duration.between(now, start).toMinutes()
        Text(next["summary"]?.jsonPrimitive?.contentOrNull ?: "Busy", style = Hub.text(28.sp, family = Hub.serif), maxLines = 1, overflow = TextOverflow.Ellipsis)
        val loc = next["location"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }
        Text((if (mins <= 0) "Now" else if (mins < 60) "In $mins min" else start.format(DateTimeFormatter.ofPattern("EEE HH:mm"))) +
            (loc?.let { " · $it" } ?: ""), style = Hub.text(11.sp, Hub.ink2), maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
    Spacer(Modifier.weight(1f))
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
    Spacer(Modifier.height(2.dp).padding(0.dp))
}
