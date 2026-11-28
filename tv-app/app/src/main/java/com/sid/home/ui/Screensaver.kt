package com.sid.home.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * The screensaver, on demand (Home's Screensaver tile): your photos full screen, cross-fading slowly, with the time,
 * what's playing and the lights. Any button closes it. Works with the Mac off (only photos already on the TV).
 * Android won't start the system screensaver for an app on this TV (SystemUI's Somnambulator quietly declines), so
 * this is the same thing, drawn by the app.
 */
@Composable
fun Screensaver(ctx: Ctx, colours: List<Color>, connected: Boolean, onClose: () -> Unit) {
    val photos = rememberShownPhotos(ctx, connected)
    // it shows hours and minutes only, so it changes once a minute: nothing here asks for a frame in between
    val now by rememberMinute()
    // the words drift a little each minute, so nothing sits on one spot of the screen for hours
    val drift = (now.minute % 6) * 6
    val focus = remember { FocusRequester() }
    val opened = remember { System.currentTimeMillis() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    // a fresh press closes it (not the tail of the press that opened it)
    Box(Modifier.fillMaxSize().background(Color.Black).focusRequester(focus).focusable()
        .onPreviewKeyEvent { if (it.type == KeyEventType.KeyDown && System.currentTimeMillis() - opened > 500) onClose(); true }) {
        // a sleep timer running: just the faint time left (see Sleep.kt)
        if (sleeping(ctx)) SleepNight(ctx) else {
            if (photos.isNotEmpty()) PhotoFrame(photos, 20_000, Modifier.fillMaxSize(), label = false)
            else Ambient(colours)
            Box(Modifier.fillMaxWidth().fillMaxHeight(.5f).align(Alignment.BottomCenter)
                .background(Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = .6f)))))
            Column(Modifier.align(Alignment.BottomStart).padding(start = 56.dp, bottom = 44.dp).offset(x = drift.dp, y = -(drift / 2).dp)) {
                Text(now.format(DateTimeFormatter.ofPattern("HH:mm")), style = Hub.text(72.sp, Color.White, family = Hub.serif))
                Text(now.format(DateTimeFormatter.ofPattern("EEEE d MMMM")), style = Hub.text(14.sp, Color.White.copy(alpha = .8f)))
                val playing = ctx.s[Ids.NOW]?.takeIf { it.str("player_state") == "playing" }?.state
                if (!playing.isNullOrBlank()) Text("♪  $playing", style = Hub.text(12.sp, Color.White.copy(alpha = .7f)), modifier = Modifier.padding(top = 10.dp))
                Box(Modifier.padding(top = 12.dp)) { StatusLine(ctx) }
            }
        }
    }
}
