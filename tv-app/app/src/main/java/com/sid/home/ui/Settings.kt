package com.sid.home.ui

import android.content.Intent
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import com.sid.home.BuildConfig
import com.sid.home.ha.data

/** A quiet on/off indicator (not focusable itself: the whole row is the one thing you press). */
@Composable
private fun Toggle(on: Boolean) {
    val track by animateColorAsState(if (on) Hub.accent.copy(alpha = .85f) else Color.White.copy(alpha = .12f), tween(200), label = "track")
    val x by animateDpAsState(if (on) 16.dp else 0.dp, tween(200), label = "knob")
    Box(Modifier.width(36.dp).height(20.dp).clip(CircleShape).background(track).padding(2.dp)) {
        Box(Modifier.offset(x = x).size(16.dp).clip(CircleShape).background(if (on) Hub.bg else Hub.ink2))
    }
}

@Composable
private fun SettingRow(icon: ImageVector, title: String, detail: String, on: Boolean?, onClick: () -> Unit) =
    Pressable(onClick = onClick, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp), color = Hub.glass, scale = 1.01f) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
            HubIcon(icon, Hub.ink2, 16.dp)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = Hub.text(11.5.sp, weight = 500))
                Text(detail, style = Hub.text(8.5.sp, Hub.ink3), maxLines = 1)
            }
            if (on != null) Toggle(on) else Text("Open", style = Hub.text(9.sp, Hub.ink3))
        }
    }

/** Basic settings from the sofa: the home's switches, and this TV's own. */
@Composable
fun SettingsPage(ctx: Ctx, connected: Boolean) {
    val context = LocalContext.current
    fun toggle(id: String) = ctx.act.callService(id.substringBefore('.'), "toggle", data("entity_id" to id))
    val homeButton = runCatching {
        android.provider.Settings.Secure.getString(context.contentResolver, android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
            ?.contains("HomeButtonService") == true
    }.getOrDefault(false)
    val privacy = Privacy.state(context)
    Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Kicker("Home", modifier = Modifier.padding(start = 4.dp, bottom = 2.dp))
            SettingRow(HubIcons.home, "Guest mode", "Landscapes instead of your photos, on the TV and the Hub", ctx.on("input_boolean.guest_photos")) { toggle("input_boolean.guest_photos") }
            SettingRow(HubIcons.music, "Music sync", "The lights follow whatever's playing", ctx.on(Ids.SYNC)) { toggle(Ids.SYNC) }
            SettingRow(HubIcons.tv, "TV glow", "A soft warm light behind the TV while it's on", ctx.on("automation.tv_bias_lighting")) { toggle("automation.tv_bias_lighting") }
            SettingRow(HubIcons.sun, "Desk lamp follows the sky", "Its colour and brightness track the daylight", ctx.on("input_boolean.desk_lamp_adaptive")) { toggle("input_boolean.desk_lamp_adaptive") }
            SettingRow(HubIcons.away, "Everything off when I leave", "When your phone has left the Wi-Fi for a while", ctx.on("automation.away_everything_off")) { toggle("automation.away_everything_off") }
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Kicker("This TV", modifier = Modifier.padding(start = 4.dp, bottom = 2.dp))
            SettingRow(HubIcons.eye, "Hide amounts", "Money stays blurred until you show it", !privacy.value) { Privacy.set(context, !privacy.value) }
            SettingRow(HubIcons.home, "Home button opens the Hub", if (homeButton) "On · turn it off in Accessibility" else "Off · switch on Hub Home button in Accessibility", homeButton) {
                runCatching { context.startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            }
            SettingRow(HubIcons.pulse, "Connection", (if (connected) "Live · " else "Offline · ") + BuildConfig.HA_URL.removePrefix("http://"), null) {}
            Spacer(Modifier.height(2.dp))
            Text("Home app ${com.sid.home.BuildConfig.VERSION_NAME}",
                style = Hub.text(8.sp, Hub.ink3), modifier = Modifier.padding(start = 4.dp))
        }
    }
}
