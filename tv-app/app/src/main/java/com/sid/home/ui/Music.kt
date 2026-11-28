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
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.graphics.drawscope.withTransform
import kotlinx.coroutines.flow.first
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
        Column(Modifier.weight(1.55f).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Box(Modifier.weight(1f).fillMaxSize().clip(RoundedCornerShape(Hub.radius)).background(Color(0xFF07070C))) {
                SoundLight(ctx, colours)
            }
            SleepStrip(ctx)  // fall asleep to a playlist (the sleep timer); not there without playlists
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
/** Frames drawn per frame offered (60 Hz): every other one. Steady 30 fps reads smoother than a 60 this TV can't hold. */
private const val EVERY = 2
/** The radius the aurora's gradients are made at once; each light is scaled from it as it swells. */
private const val UNIT_R = 1000f

/**
 * Light that moves with the music, calm by design: everything is translucent and slow, colours blend rather than
 * flash, and the beat is a swell, never a strobe. Bass breathes the aurora, the middle shapes the ribbons, the top
 * end makes the dust glint. Without the TV's sound, a soft swell on each beat of the Mac's tempo drives it. When the
 * music stops, it slows to a drift and dims.
 *
 * Cost, on a TV's weak GPU and CPU: it draws at a steady 30 fps (the motion is slow), nothing recomposes per frame
 * (the clock and bands live in draw-only state; the Visualizer's bands are read by the frame loop, not composition),
 * the gradients are made once per palette (moved and scaled by the canvas, not rebuilt each frame), and it stops
 * while the screensaver covers it.
 */
@Composable
private fun SoundLight(ctx: Ctx, colours: List<Color>) {
    val now = ctx.s[Ids.NOW]
    val playing = now?.str("player_state") == "playing" || (ctx.on(Ids.SYNC) && ctx.st(Ids.MODE) != "tv")
    val bpm = ctx.s[Ids.TEMPO]?.number?.takeIf { it in 40.0..220.0 }
    val covered = LocalCovered.current
    val bands = rememberBands(playing && !covered.value)
    val hearing by remember { androidx.compose.runtime.derivedStateOf { bands.value != null } }
    val beatS by rememberUpdatedState((60.0 / (bpm ?: RESTING_BPM)).toFloat())
    val presence by animateFloatAsState(if (playing) 1f else .3f, tween(1500), label = "presence")
    val speed by rememberUpdatedState(if (playing) 1f else .25f)

    // what the canvas draws, written together every EVERY frames: one redraw, no recomposition
    val time = remember { mutableFloatStateOf(0f) }
    val bass = remember { mutableFloatStateOf(.3f) }
    val mid = remember { mutableFloatStateOf(.3f) }
    val high = remember { mutableFloatStateOf(.2f) }
    LaunchedEffect(Unit) {
        var last = 0L
        var beat = 0f
        var n = 0
        var t = 0f; var lb = bass.floatValue; var lm = mid.floatValue; var lh = high.floatValue
        while (true) {
            if (covered.value) { snapshotFlow { covered.value }.first { !it }; last = 0L }
            withFrameNanos { ns ->
                val dt = if (last == 0L) 0f else ((ns - last) / 1e9f).coerceAtMost(.1f)
                last = ns
                t += dt * speed
                beat = (beat + dt / beatS) % 1f
                val b = bands.value
                // no sound to hear: a soft swell on each beat (rises fast, falls over the beat), the rest breathing slowly
                val env = exp(-3.2f * beat)
                val tb = b?.bass ?: (.22f + .38f * env)
                val tm = b?.mid ?: (.32f + .12f * sin(t * .7f))
                val th = b?.high ?: (.18f + .1f * env)
                fun ease(v: Float, target: Float, up: Float, down: Float) = v + (target - v) * min(1f, dt * if (target > v) up else down)
                lb = ease(lb, tb, 9f, 2.2f); lm = ease(lm, tm, 5f, 1.6f); lh = ease(lh, th, 8f, 2.5f)
                if (++n % EVERY == 0) { time.floatValue = t; bass.floatValue = lb; mid.floatValue = lm; high.floatValue = lh }
            }
        }
    }

    val cols = colours.ifEmpty { listOf(Hub.accent) }
    val art = remember(cols) { Art(cols) }
    Box(Modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            val t = time.floatValue
            aurora(art, t, bass.floatValue, presence)
            ribbons(art, t, bass.floatValue, mid.floatValue, presence)
            motes(cols, t, high.floatValue, presence)
        }
        NowLabel(ctx, playing, bpm, hearing, Modifier.align(Alignment.BottomStart).padding(22.dp))
    }
}

/** The brushes and the ribbon's path, made once per palette and reused every frame. */
private class Art(val cols: List<Color>) {
    val lights = List(4) { i -> val c = cols[i % cols.size]
        Brush.radialGradient(listOf(c.copy(alpha = .30f), c.copy(alpha = .08f), Color.Transparent), Offset.Zero, UNIT_R) }
    val ribbons = List(RIBBONS) { j -> val a = cols[j % cols.size].copy(alpha = .62f - j * .08f); val b = cols[(j + 1) % cols.size].copy(alpha = .62f - j * .08f)
        Brush.horizontalGradient(listOf(Color.Transparent, a, b, Color.Transparent)) }
    val path = Path()
    /** The ribbons' taper at each point across the width, worked out once per width. */
    var taperW = -1f
    var taper = FloatArray(0)
}

/** Four big soft lights drifting on slow, never-repeating paths, blended additively; the bass swells them. */
private fun DrawScope.aurora(art: Art, t: Float, bass: Float, presence: Float) {
    val dim = size.minDimension
    for (i in 0 until 4) {
        val x = size.width * (.5f + .34f * sin(t * .061f * (i + 1) + i * 1.7f))
        val y = size.height * (.46f + .26f * sin(t * .047f * (i + 2) + i * 2.3f + 1f))
        val r = dim * (.42f + .08f * (i % 2)) * (1f + .22f * bass)
        val k = r / UNIT_R
        withTransform({ translate(x, y); scale(k, k, Offset.Zero) }) {
            drawCircle(art.lights[i], UNIT_R, Offset.Zero, alpha = presence, blendMode = BlendMode.Plus)
        }
    }
}

/** Silky waves across the middle: two sines each, tapered at the ends; the middle of the sound sets their height. */
private fun DrawScope.ribbons(art: Art, t: Float, bass: Float, mid: Float, presence: Float) {
    val w = size.width
    val cy = size.height * .5f
    val step = 8.dp.toPx()
    val points = (w / step).toInt() + 2
    if (art.taperW != w) {
        art.taperW = w
        // (sin(π) in floats is a hair below 0, and a negative to the 1.6 is NaN, which would void the whole path)
        art.taper = FloatArray(points) { sin(PI.toFloat() * (it * step / w).coerceIn(0f, 1f)).coerceAtLeast(0f).pow(1.6f) }
    }
    val path = art.path
    val glow = Stroke(10.dp.toPx(), cap = StrokeCap.Round)
    for (j in 0 until RIBBONS) {
        val amp = size.height * (.05f + .2f * mid * (1f - j * .13f) + .06f * bass) * presence
        val k1 = (1.6f + j * .45f) * 2 * PI.toFloat() / w
        val k2 = (3.1f + j * .7f) * 2 * PI.toFloat() / w
        val p1 = t * (.55f + .12f * j) + j * 1.3f
        val p2 = -t * (.8f + .1f * j) + j * 2.1f
        path.reset()
        for (i in 0 until points) {
            val x = i * step
            val y = cy + amp * art.taper[i] * (.62f * sin(x * k1 + p1) + .38f * sin(x * k2 + p2))
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        // a wide faint pass for the glow, then the thin line itself
        drawPath(path, art.ribbons[j], alpha = .16f * presence, style = glow, blendMode = BlendMode.Plus)
        drawPath(path, art.ribbons[j], alpha = presence, style = Stroke((2.2f - j * .25f).dp.toPx(), cap = StrokeCap.Round), blendMode = BlendMode.Plus)
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
