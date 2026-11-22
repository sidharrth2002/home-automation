package com.sid.home.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import coil.decode.SvgDecoder
import coil.request.ImageRequest
import kotlin.math.PI
import kotlin.math.cos

/** The Music page: the song's cover with soft rings moving out from it in time with the music, and the full music card. */
@Composable
fun MusicPage(ctx: Ctx, colours: List<Color>, focus: FocusRequester? = null) {
    Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        HubCard(Modifier.weight(1.55f).fillMaxHeight()) { Ripples(ctx, colours, Modifier.weight(1f)) }
        MusicCard(ctx, Modifier.weight(1f).fillMaxHeight(), focus = focus)
    }
}

/**
 * How loud the TV's own sound is right now, 0..1, from Android's Visualizer on the output mix (session 0): what's
 * playing, never the microphone. Smoothed hard (quick-ish rise, slow fall) so what follows it swells, never flickers.
 * Needs RECORD_AUDIO (granted over adb by tv-app/deploy); without it, or on a TV that gives silence, it stays null and
 * the page keeps time from the Mac's tempo instead.
 */
@Composable
private fun rememberAudioLevel(active: Boolean): androidx.compose.runtime.State<Float?> {
    val context = LocalContext.current
    val level = remember { androidx.compose.runtime.mutableStateOf<Float?>(null) }
    androidx.compose.runtime.DisposableEffect(active) {
        val granted = context.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED
        val viz = if (!active || !granted) null else runCatching {
            android.media.audiofx.Visualizer(0).apply {
                captureSize = android.media.audiofx.Visualizer.getCaptureSizeRange()[0].coerceAtLeast(256)
                var smooth = 0f
                var heard = false
                setDataCaptureListener(object : android.media.audiofx.Visualizer.OnDataCaptureListener {
                    override fun onWaveFormDataCapture(v: android.media.audiofx.Visualizer, wave: ByteArray, rate: Int) {
                        var sum = 0.0
                        for (b in wave) { val x = (b.toInt() and 0xFF) - 128; sum += x * x }
                        val rms = (kotlin.math.sqrt(sum / wave.size) / 64).toFloat().coerceIn(0f, 1f)
                        smooth += (rms - smooth) * if (rms > smooth) .35f else .06f
                        if (rms > .01f) heard = true
                        level.value = if (heard) smooth else null // all silence so far: this TV may not share its sound
                    }
                    override fun onFftDataCapture(v: android.media.audiofx.Visualizer, fft: ByteArray, rate: Int) = Unit
                }, android.media.audiofx.Visualizer.getMaxCaptureRate() / 2, true, false)
                enabled = true
            }
        }.getOrNull()
        onDispose { viz?.run { enabled = false; release() }; level.value = null }
    }
    return level
}

/** Beats per ring: one ring leaves the cover each bar (four beats), so it moves with the music but never flickers. */
private const val BEATS_PER_RING = 4
private const val RINGS = 3
private const val RESTING_BPM = 72.0 // while the beat is still being found

/**
 * Calm by design: thin, translucent rings that each take three bars to fade out, and a cover that breathes by 1.5% once
 * a bar. No flashing, no bars jumping. Still (and dimmer) when nothing's playing.
 */
@Composable
private fun Ripples(ctx: Ctx, colours: List<Color>, modifier: Modifier = Modifier) {
    val now = ctx.s[Ids.NOW]
    val playing = now?.str("player_state") == "playing" || (ctx.on(Ids.SYNC) && ctx.st(Ids.MODE) != "tv")
    val bpm = ctx.s[Ids.TEMPO]?.number?.takeIf { it in 40.0..220.0 }
    val period by rememberUpdatedState(60.0 / (bpm ?: RESTING_BPM) * BEATS_PER_RING) // seconds per ring
    var phase by remember { mutableFloatStateOf(0f) } // in rings; grows while playing
    LaunchedEffect(playing) {
        if (!playing) return@LaunchedEffect
        var last = 0L
        while (true) withFrameNanos { t ->
            if (last != 0L) phase += ((t - last) / 1e9 / period).toFloat()
            last = t
        }
    }
    val presence by animateFloatAsState(if (playing) 1f else .35f, tween(1200), label = "presence")
    val audio by rememberAudioLevel(playing)
    val parts = (now?.state ?: "").split(" — ")
    val title = parts.getOrNull(0).orEmpty().takeUnless { it.isBlank() || it == "Nothing playing" }
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val inner = 124.dp.toPx() // just outside the cover's corners
                val outer = size.minDimension / 2
                // a faint halo under the cover, in the lamps' colour
                // (it swells with the TV's sound when that's available)
                val halo = audio?.let { .12f + .22f * it } ?: .22f
                drawCircle(Brush.radialGradient(listOf(colours[0].copy(alpha = halo * presence), Color.Transparent), center, outer), outer)
                for (i in 0 until RINGS) {
                    val p = ((phase + i.toFloat() / RINGS) % 1f + 1f) % 1f // 0 at the cover, 1 at the edge
                    val fade = (1 - p) * (1 - p)
                    drawCircle(colours[i % colours.size].copy(alpha = .38f * fade * presence), inner + (outer - inner) * p,
                        style = Stroke((2.5f - 1.5f * p).dp.toPx()))
                }
            }
            val breathe = 1f + presence * (audio?.let { .025f * it } ?: (.015f * (1 - cos(2 * PI * (phase * RINGS % 1f)).toFloat()) / 2))
            val url = artUrl(now?.str("entity_picture"))
            Box(Modifier.size(170.dp).graphicsLayer { scaleX = breathe; scaleY = breathe; alpha = .5f + .5f * presence }
                .clip(RoundedCornerShape(22.dp)).background(Color.White.copy(alpha = .06f)), contentAlignment = Alignment.Center) {
                if (url != null) AsyncImage(ImageRequest.Builder(LocalContext.current).data(url).decoderFactory(SvgDecoder.Factory()).crossfade(true).build(),
                    contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                else HubIcon(HubIcons.music, Hub.ink3, 40.dp)
            }
        }
        Text(when {
            !playing -> title?.let { "$it · paused" } ?: "Nothing playing"
            bpm != null -> "${bpm.toInt()} BPM" + if (audio != null) " · listening to the TV" else ""
            audio != null -> "Listening to the TV"
            else -> "Finding the beat…"
        }, style = Hub.text(9.sp, Hub.ink3, family = Hub.mono), modifier = Modifier.padding(top = 6.dp))
    }
}
