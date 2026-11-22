package com.sid.home.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sid.home.R
import com.sid.home.ha.Entity
import kotlin.math.ln
import kotlin.math.pow

/** The Hub's design tokens (frontend/hub/styles.css :root), so the TV app is the same product. */
object Hub {
    val bg = Color(0xFF07070B)
    val ink = Color(0xFFF4F1EA)
    val ink2 = ink.copy(alpha = 0.68f)
    val ink3 = ink.copy(alpha = 0.42f)
    val line = Color.White.copy(alpha = 0.08f)
    val line2 = Color.White.copy(alpha = 0.14f)
    val glass = Color(0xFF12121A).copy(alpha = 0.72f) // a touch more solid than the web's: no blur on the TV
    val glassHi = Color.White.copy(alpha = 0.045f)
    val accent = Color(0xFFFFB86B)
    val ok = Color(0xFF7EE2A8)
    val warn = Color(0xFFFFCF70)
    val bad = Color(0xFFFF7A7A)
    val up = Color(0xFF5EE6A8)
    val down = Color(0xFFFF7A8A)
    val radius = 22.dp
    val radiusSm = 13.dp

    @OptIn(ExperimentalTextApi::class)
    private fun inter(w: Int) = Font(R.font.inter, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))
    val serif = FontFamily(Font(R.font.instrument_serif), Font(R.font.instrument_serif_italic, style = FontStyle.Italic))
    val sans = FontFamily(inter(400), inter(500), inter(600), inter(700))
    @OptIn(ExperimentalTextApi::class)
    val mono = FontFamily(Font(R.font.jetbrains_mono, FontWeight(500), variationSettings = FontVariation.Settings(FontVariation.weight(500))))

    fun text(size: TextUnit, color: Color = ink, weight: Int = 400, family: FontFamily = sans, spacing: TextUnit = TextUnit.Unspecified) =
        TextStyle(fontSize = size, color = color, fontWeight = FontWeight(weight), fontFamily = family, letterSpacing = spacing)

    /** The small uppercase labels ("kicker" in the Hub). */
    val kicker = TextStyle(fontSize = 9.sp, color = ink3, fontFamily = sans, fontWeight = FontWeight(500), letterSpacing = 1.4.sp)
}

/** A Hub icon (24-unit stroke drawing, generated into HubIcons from the Hub's own SVGs). */
fun hubIcon(vararg paths: String): ImageVector {
    val b = ImageVector.Builder(defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f)
    for (d in paths) b.addPath(PathParser().parsePathString(d).toNodes(), stroke = SolidColor(Color.White), strokeLineWidth = 1.6f,
        strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round)
    return b.build()
}

@Composable
fun HubIcon(icon: ImageVector, tint: Color = Hub.ink, size: Dp = 16.dp, modifier: Modifier = Modifier) =
    Image(icon, contentDescription = null, colorFilter = ColorFilter.tint(tint), modifier = modifier.size(size))

// ── colour helpers, as in the Hub ──
fun kelvinToRgb(k: Double): Triple<Int, Int, Int> {
    val t = k.coerceIn(1000.0, 40000.0) / 100
    val r = if (t <= 66) 255.0 else 329.698727446 * (t - 60).pow(-0.1332047592)
    val g = if (t <= 66) 99.4708025861 * ln(t) - 161.1195681661 else 288.1221695283 * (t - 60).pow(-0.0755148492)
    val b = if (t >= 66) 255.0 else if (t <= 19) 0.0 else 138.5177312231 * ln(t - 10) - 305.0447927307
    fun c(v: Double) = v.coerceIn(0.0, 255.0).toInt()
    return Triple(c(r), c(g), c(b))
}

/** A light's colour right now (its RGB, or its white temperature), as a Compose colour. */
fun lightColor(e: Entity?): Color {
    val rgb = e?.ints("rgb_color")
    if (rgb != null && rgb.size == 3) return Color(rgb[0], rgb[1], rgb[2])
    val k = e?.num("color_temp_kelvin")
    val (r, g, b) = if (k != null) kelvinToRgb(k) else Triple(255, 196, 140)
    return Color(r, g, b)
}

fun hex(s: String): Color = runCatching { Color(android.graphics.Color.parseColor(s)) }.getOrDefault(Hub.accent)

fun pctOf(e: Entity?): Int = (((e?.num("brightness") ?: 0.0) / 255.0) * 100).toInt()
