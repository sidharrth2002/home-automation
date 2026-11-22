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
import kotlinx.coroutines.flow.sample
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
import com.sid.home.ui.LiveEntities
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The app's one connection to Home Assistant, shared by the home screen and the screensaver. With no token baked in
 * (a build without ./deploy), or launched with --ez demo true, it shows the Hub's demo household instead.
 */
object HomeApp {
    val state = HomeState()
    private var actions: Actions? = null

    var notice: ((String) -> Unit)? = null
    var snapshot: com.sid.home.ha.Snapshot? = null
    /** A page asked for from outside (an intent's "page" extra); the home screen shows it, then clears this. */
    val openPage = kotlinx.coroutines.flow.MutableStateFlow<com.sid.home.ui.Page?>(null)
    private val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.IO)

    fun start(context: Context, demo: Boolean): Actions {
        actions?.let { return it }
        // decoded pictures kept in memory: Coil's default is a quarter of the 192 MB heap, on a TV that's short of RAM;
        // 24 MB holds the photo on screen and the next one, the album art and the banners (the rest is on disk)
        coil.Coil.setImageLoader(coil.ImageLoader.Builder(context.applicationContext)
            .memoryCache { coil.memory.MemoryCache.Builder(context.applicationContext).maxSizeBytes(24 * 1024 * 1024).build() }
            .build())
        // Home's app banners, drawn before the page first asks for them (off the main thread)
        scope.launch { for (app in com.sid.home.ui.TV_APPS) com.sid.home.ui.Banners.load(context.applicationContext, app.pkg) }
        val a: Actions = if (demo || BuildConfig.HA_TOKEN.isEmpty()) {
            Demo.load(state, context.assets.open("demo.json").bufferedReader().readText()); Demo
        } else {
            // offline first: the last known state on screen at once, then Home Assistant's when it answers
            val snapshot = com.sid.home.ha.Snapshot(java.io.File(context.filesDir, "home-state.json")).also { this.snapshot = it }
            snapshot.load(state)
            snapshot.keepSaved(state, scope)
            com.sid.home.ui.PhotoCache.keepWarm(context, state, scope)
            HaClient(BuildConfig.HA_URL, BuildConfig.HA_TOKEN, state).also { it.notice = { m -> notice?.invoke(m) }; it.start(); it.refreshCalendarsLater() }
        }
        actions = a
        return a
    }
}

/** The TV's home screen, native: the Hub's cards in Compose, moved through with the remote. */
class HomeActivity : ComponentActivity() {
    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val crash = Thread.getDefaultUncaughtExceptionHandler()
        if (crash !is HubCrash) Thread.setDefaultUncaughtExceptionHandler(HubCrash(applicationContext, crash))
        val actions = HomeApp.start(this, intent.getBooleanExtra("demo", false))
        openPage(intent)
        setContent { HomeRoot(actions) }
    }

    /** Back to the Hub while it's open: the Home button (via HomeButtonService), so it lands on Home with nothing over it. */
    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        HomeApp.openPage.value = pageAsked(intent) ?: com.sid.home.ui.Page.ROOM
    }

    private fun openPage(intent: android.content.Intent) { pageAsked(intent)?.let { HomeApp.openPage.value = it } }

    /** `--es page MUSIC` (adb, for checking a page on the TV): show that page. */
    private fun pageAsked(intent: android.content.Intent) =
        intent.getStringExtra("page")?.let { name -> com.sid.home.ui.Page.entries.find { it.name == name } }

    override fun onStop() {
        super.onStop()
        kotlin.concurrent.thread { HomeApp.snapshot?.flush(HomeApp.state) } // keep what's on screen for next time
    }

    override fun onResume() {
        super.onResume()
        HomeRedirect.backInHub(this) // Google TV's home is only kept when chosen, until the Hub is back
    }
}

/** Notes a crash before the app dies, so the Home button service leaves Google TV up for a while instead of looping. */
private class HubCrash(private val context: Context, private val next: Thread.UncaughtExceptionHandler?) : Thread.UncaughtExceptionHandler {
    override fun uncaughtException(t: Thread, e: Throwable) {
        HomeRedirect.hubCrashed(context)
        next?.uncaughtException(t, e)
    }
}

@Composable
fun HomeRoot(actions: Actions) {
    // at most 5 screen updates a second (during music sync Home Assistant sends lamp changes many times a second),
    // each one only recomposing what read a changed entity (LiveEntities)
    val live = remember { LiveEntities().apply { update(HomeApp.state.entities.value) } }
    @OptIn(kotlinx.coroutines.FlowPreview::class)
    LaunchedEffect(live) { HomeApp.state.entities.sample(200).collect { live.update(it) } }
    var toast by remember { mutableStateOf<String?>(null) }
    // one Ctx for the app's life: cards given it are skipped when nothing they read changed
    val ctx = remember { Ctx(live, actions) { toast = it } }
    val connected by HomeApp.state.connected.collectAsState()
    val events by HomeApp.state.events.collectAsState()
    val savedAt by HomeApp.state.savedAt.collectAsState()
    val pending by HomeApp.state.pending.collectAsState()
    // offline: say since when the screen's state is, and what's waiting to be sent
    val offline = listOfNotNull("Offline",
        savedAt?.let { "last update " + java.time.Instant.ofEpochMilli(it).atZone(java.time.ZoneId.systemDefault()).toLocalTime().toString().take(5) },
        pending.takeIf { it > 0 }?.let { "$it change${if (it > 1) "s" else ""} waiting" }).joinToString(" · ")
    LaunchedEffect(toast) { if (toast != null) { delay(3200); toast = null } }
    Demo.onCall = { toast = it }
    HomeApp.notice = { toast = it }
    Box {
        val asked by HomeApp.openPage.collectAsState()
        HomeScreen(ctx, connected, events, offline = offline, open = asked) { HomeApp.openPage.value = null }
        AnimatedVisibility(toast != null, Modifier.align(Alignment.BottomCenter).padding(bottom = 28.dp), enter = fadeIn(), exit = fadeOut()) {
            Text(toast.orEmpty(), style = Hub.text(12.sp, weight = 500),
                modifier = Modifier.clip(CircleShape).background(Color(0xEE16161F)).padding(horizontal = 18.dp, vertical = 9.dp))
        }
    }
}
