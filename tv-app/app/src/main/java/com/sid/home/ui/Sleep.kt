package com.sid.home.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.sid.home.ha.data
import kotlinx.coroutines.delay
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

private const val SLEEP_TIMER = "sensor.sleep_timer"
private const val PLAYLISTS = "sensor.spotify_playlists"
private val LENGTHS = listOf(30, 45, 60, 90)

private data class Playlist(val name: String, val uri: String, val image: String?)

/**
 * Fall asleep to music, from the sofa: choose a length, then press a playlist to start it on the TV (the sleep
 * service fades it out at the end and turns everything off; see sleep/__main__.py). While it runs: the time left,
 * +15 min and Cancel. Calm: no countdown animation, just the minutes.
 */
@Composable
fun SleepStrip(ctx: Ctx, modifier: Modifier = Modifier) {
    val timer = ctx.s[SLEEP_TIMER]
    val lists = ctx.s[PLAYLISTS]?.arr("playlists")?.mapNotNull { e ->
        val o = e.jsonObject
        val uri = o["uri"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
        Playlist(o["name"]?.jsonPrimitive?.contentOrNull ?: "Playlist", uri, o["image"]?.jsonPrimitive?.contentOrNull)
    } ?: emptyList()
    val running = timer?.state == "on"
    if (!running && lists.isEmpty()) return
    HubCard(modifier, padding = 16.dp) {
        if (running) Running(ctx) else Choose(ctx, lists, timer?.str("error"))
    }
}

@Composable
private fun Choose(ctx: Ctx, lists: List<Playlist>, error: String?) {
    var minutes by rememberSaveable { mutableIntStateOf(45) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        HubIcon(HubIcons.moon, Hub.ink2, 15.dp); Spacer(Modifier.width(8.dp))
        Text("Sleep timer", style = Hub.text(13.sp, weight = 500)); Spacer(Modifier.width(14.dp))
        Segmented(LENGTHS.map { it.toString() }, minutes.toString(), label = { "$it min" }, onSelect = { minutes = it.toInt() },
            modifier = Modifier.width(300.dp))
        Spacer(Modifier.weight(1f))
        Text(error ?: "Press one to start", style = Hub.text(10.sp, Hub.ink3), maxLines = 1,
            overflow = TextOverflow.Ellipsis, modifier = Modifier.width(200.dp))
    }
    Spacer(Modifier.height(10.dp))
    val context = LocalContext.current
    LazyRow(Modifier.fillMaxWidth().oneStepAtATime(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        items(lists, key = { it.uri }) { p ->
            Pressable(onClick = {
                ctx.toast("Starting ${p.name} on the TV…")
                ctx.act.callService("script", "sleep_timer_start", data("playlist" to p.uri, "name" to p.name, "minutes" to minutes))
            }, shape = RoundedCornerShape(12.dp), scale = 1.05f) {
                Column(Modifier.width(84.dp).padding(4.dp)) {
                    Cover(p.image, 76.dp, context)
                    Spacer(Modifier.height(5.dp))
                    Text(p.name, style = Hub.text(10.sp, Hub.ink2), maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

@Composable
private fun Running(ctx: Ctx) {
    val timer = ctx.s[SLEEP_TIMER]
    val ends = remember(timer?.str("ends_at")) {
        runCatching { java.time.Instant.parse(timer?.str("ends_at")).toEpochMilli() }
            .recoverCatching { java.time.OffsetDateTime.parse(timer?.str("ends_at")).toInstant().toEpochMilli() }.getOrDefault(0L)
    }
    // the minutes left, refreshed every 20 s (nothing here moves in between)
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(ends) { while (true) { now = System.currentTimeMillis(); delay(20_000) } }
    val left = ((ends - now + 59_999) / 60_000).coerceAtLeast(0)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Cover(timer?.str("image"), 64.dp, LocalContext.current)
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Kicker("Sleep timer")
            Text("Sleep · $left min", style = Hub.text(22.sp, family = Hub.serif))
            Text("${timer?.str("playlist") ?: "Spotify"} on the TV · fades out at the end", style = Hub.text(11.sp, Hub.ink2),
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Pressable(onClick = { ctx.act.callService("script", "sleep_timer_extend", data("minutes" to 15)) }, shape = RoundedCornerShape(10.dp)) {
            Text("+15 min", style = Hub.text(12.sp, weight = 500), modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp))
        }
        Spacer(Modifier.width(8.dp))
        Pressable(onClick = { ctx.act.callService("script", "sleep_timer_cancel", data()) }, shape = RoundedCornerShape(10.dp)) {
            Text("Cancel", style = Hub.text(12.sp, Hub.ink2, 500), modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp))
        }
    }
}

@Composable
private fun Cover(url: String?, size: androidx.compose.ui.unit.Dp, context: android.content.Context) {
    Box(Modifier.size(size).clip(RoundedCornerShape(10.dp)).background(Color.White.copy(alpha = .06f)), contentAlignment = Alignment.Center) {
        if (url != null) AsyncImage(ImageRequest.Builder(context).data(url).size(240).crossfade(false).build(), null,
            contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        else HubIcon(HubIcons.music, Hub.ink3, 20.dp)
    }
}
