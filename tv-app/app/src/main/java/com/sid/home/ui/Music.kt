package com.sid.home.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import coil.compose.AsyncImage
import coil.decode.SvgDecoder
import coil.request.ImageRequest
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/** The Music page: light that moves with the song (an aurora, ribbons of sound, a little drifting dust), and the music card. */
@Composable
fun MusicPage(ctx: Ctx, colours: List<Color>, focus: FocusRequester? = null) {
    Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Box(Modifier.weight(1.55f).fillMaxHeight().clip(RoundedCornerShape(Hub.radius)).background(Color(0xFF07070C))) {
            SoundLight(ctx, colours)
        }
        MusicCard(ctx, Modifier.weight(1f).fillMaxHeight(), focus = focus)
    }
}

/** How the music feels right now, each 0..1: low end, middle, top end. */
private class Bands(val bass: Float, val mid: Float, val high: Float)

/**
 * The TV's own sound (Android's Visualizer on the output mix, session 0: what's playing, never the microphone), as
 * three bands. Each band has its own slow automatic gain, so quiet and loud songs both fill the range. Needs
 * RECORD_AUDIO (tv-app/deploy grants it); without it, or on a TV that only gives silence, it stays null and the page
 * keeps time from the Mac's tempo instead.
 */
@Composable
private fun rememberBands(active: Boolean): androidx.compose.runtime.State<Bands?> {
    val context = LocalContext.current
    val bands = remember { androidx.compose.runtime.mutableStateOf<Bands?>(null) }
    DisposableEffect(active) {
        val granted = context.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED
        val viz = if (!active || !granted) null else runCatching {
            android.media.audiofx.Visualizer(0).apply {
                captureSize = android.media.audiofx.Visualizer.getCaptureSizeRange()[1].coerceAtMost(1024)
                val gain = floatArrayOf(4f, 4f, 4f)
                var heard = false
                setDataCaptureListener(object : android.media.audiofx.Visualizer.OnDataCaptureListener {
                    override fun onWaveFormDataCapture(v: android.media.audiofx.Visualizer, wave: ByteArray, rate: Int) = Unit
                    override fun onFftDataCapture(v: android.media.audiofx.Visualizer, fft: ByteArray, rate: Int) {
                        val n = fft.size
                        val hzPerBin = rate / 1000f / n
                        fun band(i: Int, lo: Float, hi: Float): Float {
                            var sum = 0f; var count = 0
                            for (k in max(1, (lo / hzPerBin).toInt())..min(n / 2 - 1, (hi / hzPerBin).toInt())) {
                                sum += hypot(fft[2 * k].toFloat(), fft[2 * k + 1].toFloat()); count++
                            }
                            val m = if (count == 0) 0f else sum / count
                            gain[i] = max(max(m, 2f), gain[i] * .997f) // remembers the song's loudest for ~10 s
                            return (m / gain[i]).coerceIn(0f, 1f)
                        }
                        val b = Bands(band(0, 30f, 160f), band(1, 160f, 2000f), band(2, 2000f, 9000f))
                        if (!heard && b.bass + b.mid + b.high > .05f && gain.any { it > 2.5f }) {
                            heard = true; android.util.Log.i("Music", "Visualizer: hearing the TV")
                        }
                        bands.value = if (heard) b else null
                    }
                }, android.media.audiofx.Visualizer.getMaxCaptureRate(), false, true)
                enabled = true
                android.util.Log.i("Music", "Visualizer on (capture $captureSize)")
            }
        }.onFailure { android.util.Log.w("Music", "no Visualizer: $it") }.getOrNull()
        onDispose { viz?.run { enabled = false; release() }; bands.value = null }
    }
    return bands
}

private const val RESTING_BPM = 72.0 // while the beat is still being found
private const val RIBBONS = 5
private const val MOTES = 34

/**
 * Light that moves with the music, calm by design: everything is translucent and slow, colours blend rather than
 * flash, and the beat is a swell, never a strobe. Bass breathes the aurora, the middle shapes the ribbons, the top
 * end makes the dust glint. Without the TV's sound, a soft swell on each beat of the Mac's tempo drives it. When the
 * music stops, it slows to a drift and dims.
 */
@Composable
private fun SoundLight(ctx: Ctx, colours: List<Color>) {
    val now = ctx.s[Ids.NOW]
    val playing = now?.str("player_state") == "playing" || (ctx.on(Ids.SYNC) && ctx.st(Ids.MODE) != "tv")
    val bpm = ctx.s[Ids.TEMPO]?.number?.takeIf { it in 40.0..220.0 }
    val heard by rememberBands(playing)
    val latest by rememberUpdatedState(heard)
    val beatS by rememberUpdatedState((60.0 / (bpm ?: RESTING_BPM)).toFloat())
    val presence by animateFloatAsState(if (playing) 1f else .3f, tween(1500), label = "presence")
    val speed by rememberUpdatedState(if (playing) 1f else .25f)

    // the clock and the smoothed bands live in draw-only state: the canvas redraws each frame, nothing recomposes
    val time = remember { mutableFloatStateOf(0f) }
    val bass = remember { mutableFloatStateOf(.3f) }
    val mid = remember { mutableFloatStateOf(.3f) }
    val high = remember { mutableFloatStateOf(.2f) }
    LaunchedEffect(Unit) {
        var last = 0L
        var beat = 0f
        while (true) withFrameNanos { t ->
            val dt = if (last == 0L) 0f else ((t - last) / 1e9f).coerceAtMost(.1f)
            last = t
            time.floatValue += dt * speed
            beat = (beat + dt / beatS) % 1f
            val b = latest
            // no sound to hear: a soft swell on each beat (rises fast, falls over the beat), the rest breathing slowly
            val env = exp(-3.2f * beat)
            val tb = b?.bass ?: (.22f + .38f * env)
            val tm = b?.mid ?: (.32f + .12f * sin(time.floatValue * .7f))
            val th = b?.high ?: (.18f + .1f * env)
            fun ease(s: androidx.compose.runtime.MutableFloatState, target: Float, up: Float, down: Float) {
                s.floatValue += (target - s.floatValue) * min(1f, dt * if (target > s.floatValue) up else down)
            }
            ease(bass, tb, 9f, 2.2f); ease(mid, tm, 5f, 1.6f); ease(high, th, 8f, 2.5f)
        }
    }

    val cols = colours.ifEmpty { listOf(Hub.accent) }
    val ribbon = remember { Path() }
    Box(Modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            val t = time.floatValue
            aurora(cols, t, bass.floatValue, presence)
            ribbons(ribbon, cols, t, bass.floatValue, mid.floatValue, presence)
            motes(cols, t, high.floatValue, presence)
        }
        NowLabel(ctx, playing, bpm, heard != null, Modifier.align(Alignment.BottomStart).padding(22.dp))
    }
}

/** Four big soft lights drifting on slow, never-repeating paths, blended additively; the bass swells them. */
private fun DrawScope.aurora(cols: List<Color>, t: Float, bass: Float, presence: Float) {
    val dim = size.minDimension
    for (i in 0 until 4) {
        val c = cols[i % cols.size]
        val x = size.width * (.5f + .34f * sin(t * .061f * (i + 1) + i * 1.7f))
        val y = size.height * (.46f + .26f * sin(t * .047f * (i + 2) + i * 2.3f + 1f))
        val r = dim * (.42f + .08f * (i % 2)) * (1f + .22f * bass)
        drawCircle(Brush.radialGradient(listOf(c.copy(alpha = .30f * presence), c.copy(alpha = .08f * presence), Color.Transparent),
            Offset(x, y), r), r, Offset(x, y), blendMode = BlendMode.Plus)
    }
}

/** Silky waves across the middle: two sines each, tapered at the ends; the middle of the sound sets their height. */
private fun DrawScope.ribbons(path: Path, cols: List<Color>, t: Float, bass: Float, mid: Float, presence: Float) {
    val w = size.width
    val cy = size.height * .5f
    val step = 6.dp.toPx()
    for (j in 0 until RIBBONS) {
        val amp = size.height * (.05f + .2f * mid * (1f - j * .13f) + .06f * bass) * presence
        val k1 = (1.6f + j * .45f) * 2 * PI.toFloat() / w
        val k2 = (3.1f + j * .7f) * 2 * PI.toFloat() / w
        path.reset()
        var x = 0f
        while (x <= w + step) {
            // (sin(π) in floats is a hair below 0, and a negative to the 1.6 is NaN, which would void the whole path)
            val taper = sin(PI.toFloat() * (x / w).coerceIn(0f, 1f)).coerceAtLeast(0f).pow(1.6f)
            val y = cy + amp * taper * (.62f * sin(x * k1 + t * (.55f + .12f * j) + j * 1.3f) + .38f * sin(x * k2 - t * (.8f + .1f * j) + j * 2.1f))
            if (x == 0f) path.moveTo(x, y) else path.lineTo(x, y)
            x += step
        }
        val a = cols[j % cols.size]; val b = cols[(j + 1) % cols.size]
        val alpha = (.62f - j * .08f) * presence
        val brush = Brush.horizontalGradient(listOf(Color.Transparent, a.copy(alpha = alpha), b.copy(alpha = alpha), Color.Transparent))
        // a wide faint pass for the glow, then the thin line itself
        drawPath(path, brush, alpha = .16f, style = Stroke(10.dp.toPx(), cap = StrokeCap.Round), blendMode = BlendMode.Plus)
        drawPath(path, brush, style = Stroke((2.2f - j * .25f).dp.toPx(), cap = StrokeCap.Round), blendMode = BlendMode.Plus)
    }
}

/** A little dust rising slowly through the light; it glints with the top end of the sound. */
private fun DrawScope.motes(cols: List<Color>, t: Float, high: Float, presence: Float) {
    for (i in 0 until MOTES) {
        val seed = i * 9301 + 49297
        val bx = (seed % 997) / 997f
        val by = (seed * 7 % 991) / 991f
        val rise = .008f + (i % 5) * .003f
        val y = ((by - t * rise) % 1f + 1f) % 1f
        val x = bx * size.width + sin(t * .3f + i) * 14.dp.toPx()
        val twinkle = (sin(t * (1.1f + i % 3 * .4f) + i * 2.4f) + 1f) / 2f
        val alpha = (.1f + .55f * high * twinkle) * presence * (1f - abs(y - .5f) * 1.4f).coerceIn(0f, 1f)
        drawCircle(cols[i % cols.size].copy(alpha = alpha), (1f + (i % 3) * .6f).dp.toPx(), Offset(x, y * size.height), blendMode = BlendMode.Plus)
    }
}

/** The cover and what's playing, small, in the corner: the light is the point of this page. */
@Composable
private fun NowLabel(ctx: Ctx, playing: Boolean, bpm: Double?, hearing: Boolean, modifier: Modifier) {
    val now = ctx.s[Ids.NOW]
    val parts = (now?.state ?: "").split(" — ")
    val title = parts.getOrNull(0).orEmpty().takeUnless { it.isBlank() || it == "Nothing playing" }
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        val url = artUrl(now?.str("entity_picture"))
        Box(Modifier.size(64.dp).clip(RoundedCornerShape(12.dp)).background(Color.White.copy(alpha = .06f)), contentAlignment = Alignment.Center) {
            if (url != null) AsyncImage(ImageRequest.Builder(LocalContext.current).data(url).decoderFactory(SvgDecoder.Factory()).crossfade(true).build(),
                contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            else HubIcon(HubIcons.music, Hub.ink3, 22.dp)
        }
        Spacer(Modifier.width(14.dp))
        Column {
            Text(title ?: "Nothing playing", style = Hub.text(18.sp, family = Hub.serif), maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(listOfNotNull(parts.getOrNull(1)?.takeIf { title != null }, if (!playing && title != null) "paused" else null,
                bpm?.let { "${it.toInt()} BPM" }, if (hearing) "listening to the TV" else null).joinToString(" · "),
                style = Hub.text(9.sp, Hub.ink3, family = Hub.mono), maxLines = 1)
        }
    }
}
