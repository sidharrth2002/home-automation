package com.sid.home.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Border
import androidx.tv.material3.ClickableSurfaceDefaults
import androidx.tv.material3.Surface
import androidx.tv.material3.Text
import kotlinx.coroutines.delay

/** A Hub card: dark glass with a hairline border and a title row. */
@Composable
fun HubCard(modifier: Modifier = Modifier, padding: Dp = 18.dp, content: @Composable ColumnScope.() -> Unit) =
    Column(modifier.clip(RoundedCornerShape(Hub.radius)).background(Hub.glass).border(1.dp, Hub.line, RoundedCornerShape(Hub.radius))
        .padding(padding), content = content)

@Composable
fun CardHead(title: String, icon: ImageVector, right: @Composable RowScope.() -> Unit = {}) =
    Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        HubIcon(icon, Hub.ink2, 13.dp)
        Spacer(Modifier.width(7.dp))
        Text(title, style = Hub.text(12.sp, weight = 500))
        Spacer(Modifier.weight(1f))
        right()
    }

@Composable
fun Kicker(text: String, color: Color = Hub.ink3, modifier: Modifier = Modifier) =
    Text(text.uppercase(), style = Hub.kicker.copy(color = color), modifier = modifier, maxLines = 1, overflow = TextOverflow.Ellipsis)

/** The Hub's pill chips (presence, weather, outside light). */
@Composable
fun Chip(content: @Composable RowScope.() -> Unit) =
    Row(Modifier.clip(CircleShape).background(Color.White.copy(alpha = .06f)).border(1.dp, Hub.line, CircleShape)
        .padding(horizontal = 9.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp), content = content)

/** Something you can focus and press with the remote: lifts and rings when focused, like Google TV's own tiles. */
@Composable
fun Pressable(
    onClick: () -> Unit, modifier: Modifier = Modifier, shape: Shape = RoundedCornerShape(Hub.radiusSm),
    color: Color = Color.Transparent, focusedColor: Color = Color.White.copy(alpha = .12f), scale: Float = 1.06f,
    glow: Color = Color.White, content: @Composable () -> Unit,
) = Surface(
    onClick = onClick, modifier = modifier,
    shape = ClickableSurfaceDefaults.shape(shape),
    colors = ClickableSurfaceDefaults.colors(containerColor = color, focusedContainerColor = focusedColor,
        pressedContainerColor = focusedColor),
    scale = ClickableSurfaceDefaults.scale(focusedScale = scale),
    border = ClickableSurfaceDefaults.border(focusedBorder = Border(BorderStroke(2.dp, glow.copy(alpha = .85f)), shape = shape)),
) { content() }

/** The Hub's segmented control: one option pressed. */
@Composable
fun Segmented(options: List<String>, selected: String?, label: (String) -> String = { it }, onSelect: (String) -> Unit, modifier: Modifier = Modifier) =
    Row(modifier.clip(RoundedCornerShape(12.dp)).background(Color.White.copy(alpha = .05f)).border(1.dp, Hub.line, RoundedCornerShape(12.dp))
        .padding(3.dp), horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        for (o in options) {
            val on = o == selected
            Pressable(onClick = { onSelect(o) }, modifier = Modifier.weight(1f), shape = RoundedCornerShape(9.dp),
                color = if (on) Hub.ink else Color.Transparent, focusedColor = if (on) Hub.ink else Color.White.copy(alpha = .16f), scale = 1.04f) {
                Box(Modifier.fillMaxWidth().padding(vertical = 6.dp), contentAlignment = Alignment.Center) {
                    Text(label(o).replaceFirstChar { it.uppercase() }, style = Hub.text(10.sp, if (on) Hub.bg else Hub.ink2, 500), maxLines = 1)
                }
            }
        }
    }

/**
 * A slider for the remote: focus it, then left and right move it in steps. The value is sent once the presses stop
 * (so holding an arrow doesn't flood Home Assistant), and live updates don't fight the person pressing.
 */
@Composable
fun RemoteSlider(
    value: Float, onCommit: (Float) -> Unit, modifier: Modifier = Modifier, range: ClosedFloatingPointRange<Float> = 1f..100f,
    step: Float = 5f, fill: Color = Hub.accent, enabled: Boolean = true,
) {
    var local by remember { mutableFloatStateOf(value) }
    var touched by remember { mutableStateOf(0L) }
    var focused by remember { mutableStateOf(false) }
    LaunchedEffect(value) { if (System.currentTimeMillis() - touched > 1500) local = value }
    LaunchedEffect(touched) {
        if (touched == 0L) return@LaunchedEffect
        delay(350)
        onCommit(local)
    }
    val p = ((local - range.start) / (range.endInclusive - range.start)).coerceIn(0f, 1f)
    Surface(
        onClick = {}, enabled = enabled,
        modifier = modifier.height(22.dp).onFocusChanged { focused = it.isFocused }.onPreviewKeyEvent {
            if (it.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
            val d = when (it.key) { Key.DirectionLeft -> -step; Key.DirectionRight -> step; else -> return@onPreviewKeyEvent false }
            val next = (local + d).coerceIn(range.start, range.endInclusive)
            if (next == local) return@onPreviewKeyEvent (d > 0 && local >= range.endInclusive) || (d < 0 && local <= range.start)
            local = next; touched = System.currentTimeMillis(); true
        },
        shape = ClickableSurfaceDefaults.shape(CircleShape),
        colors = ClickableSurfaceDefaults.colors(containerColor = Color.Transparent, focusedContainerColor = Color.White.copy(alpha = .06f),
            disabledContainerColor = Color.Transparent),
        scale = ClickableSurfaceDefaults.scale(focusedScale = 1.0f),
        border = ClickableSurfaceDefaults.border(focusedBorder = Border(BorderStroke(1.5.dp, Hub.ink.copy(alpha = .6f)), shape = CircleShape)),
    ) {
        Box(Modifier.fillMaxWidth().fillMaxHeight().padding(horizontal = 8.dp), contentAlignment = Alignment.CenterStart) {
            Box(Modifier.fillMaxWidth().height(4.dp).clip(CircleShape).background(Color.White.copy(alpha = .1f)))
            Box(Modifier.fillMaxWidth(p).height(4.dp).clip(CircleShape).background(if (enabled) fill else Hub.ink3))
            Box(Modifier.fillMaxWidth(p.coerceAtLeast(.001f)), contentAlignment = Alignment.CenterEnd) {
                Box(Modifier.size(if (focused) 14.dp else 11.dp).clip(CircleShape).background(if (enabled) Color.White else Hub.ink3))
            }
        }
    }
}


val NoPadding = PaddingValues(0.dp)
