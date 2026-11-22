package com.sid.home

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import com.sid.home.ha.Actions
import com.sid.home.ha.Demo
import com.sid.home.ha.HaClient
import com.sid.home.ha.HomeState
import com.sid.home.ui.Ctx
import com.sid.home.ui.Hub
import com.sid.home.ui.HomeScreen
import kotlinx.coroutines.delay

/**
 * The app's one connection to Home Assistant, shared by the home screen and the screensaver. With no token baked in
 * (a build without ./deploy), or launched with --ez demo true, it shows the Hub's demo household instead.
 */
object HomeApp {
    val state = HomeState()
    private var actions: Actions? = null

    fun start(context: Context, demo: Boolean): Actions {
        actions?.let { return it }
        val a: Actions = if (demo || BuildConfig.HA_TOKEN.isEmpty()) {
            Demo.load(state, context.assets.open("demo.json").bufferedReader().readText()); Demo
        } else HaClient(BuildConfig.HA_URL, BuildConfig.HA_TOKEN, state).also { it.start(); it.refreshCalendarsLater() }
        actions = a
        return a
    }
}

/** The TV's home screen, native: the Hub's cards in Compose, moved through with the remote. */
class HomeActivity : ComponentActivity() {
    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val actions = HomeApp.start(this, intent.getBooleanExtra("demo", false))
        setContent { HomeRoot(actions) }
    }

    override fun onResume() {
        super.onResume()
        HomeRedirect.backInHub() // Google TV's home is only kept when chosen, until the Hub is back
    }
}

@Composable
fun HomeRoot(actions: Actions) {
    val s by HomeApp.state.entities.collectAsState()
    val connected by HomeApp.state.connected.collectAsState()
    val events by HomeApp.state.events.collectAsState()
    var toast by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(toast) { if (toast != null) { delay(3200); toast = null } }
    Demo.onCall = { toast = it }
    Box {
        HomeScreen(Ctx(s, actions) { toast = it }, connected, events)
        AnimatedVisibility(toast != null, Modifier.align(Alignment.BottomCenter).padding(bottom = 28.dp), enter = fadeIn(), exit = fadeOut()) {
            Text(toast.orEmpty(), style = Hub.text(12.sp, weight = 500),
                modifier = Modifier.clip(CircleShape).background(Color(0xEE16161F)).padding(horizontal = 18.dp, vertical = 9.dp))
        }
    }
}
