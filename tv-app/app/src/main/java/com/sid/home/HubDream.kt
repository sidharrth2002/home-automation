package com.sid.home

import android.service.dreams.DreamService
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.ComposeView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.savedstate.SavedStateRegistry
import androidx.savedstate.SavedStateRegistryController
import androidx.savedstate.SavedStateRegistryOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner
import com.sid.home.ha.Actions
import com.sid.home.ui.Ctx
import com.sid.home.ui.LiveEntities
import com.sid.home.ui.Screensaver
import com.sid.home.ui.ambientColours
import com.sid.home.ui.settled
import com.sid.home.ui.sleeping
import kotlinx.coroutines.flow.sample

/**
 * The TV's screensaver: the same native Screensaver as Home's tile (photos or the glow, the time, what's playing, the
 * lights), shared with the app's one Home Assistant connection. It used to be the Hub in a WebView, which grew the
 * app by ~400 MB over a few minutes until the TV's low-memory killer took the app and the Home button service with
 * it. Google TV hides third-party screensavers in its settings, so it's switched on over adb: see tv-app/screensaver.
 * Any button press wakes the TV as usual.
 */
class HubDream : DreamService(), LifecycleOwner, SavedStateRegistryOwner {
    // a DreamService isn't a lifecycle owner, and a ComposeView needs one (and a saved-state registry) to run
    private val life = LifecycleRegistry(this)
    private val saved = SavedStateRegistryController.create(this)
    override val lifecycle: Lifecycle get() = life
    override val savedStateRegistry: SavedStateRegistry get() = saved.savedStateRegistry

    override fun onCreate() {
        super.onCreate()
        saved.performRestore(null)
        life.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        isInteractive = false // a key press ends the screensaver, like any other
        isFullscreen = true
        isScreenBright = true
        val actions = HomeApp.start(this, false)
        window.decorView.setViewTreeLifecycleOwner(this)
        window.decorView.setViewTreeSavedStateRegistryOwner(this)
        setContentView(ComposeView(this).apply { setContent { DreamRoot(actions, ::dim) } })
    }

    /** During a sleep timer: the backlight as low as the window may set it (if the TV honours it), back after. */
    private fun dim(on: Boolean) {
        val w = window ?: return
        w.attributes = w.attributes.apply {
            screenBrightness = if (on) 0.01f else WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        }
    }

    override fun onDreamingStarted() {
        super.onDreamingStarted()
        life.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
    }

    override fun onDreamingStopped() {
        life.handleLifecycleEvent(Lifecycle.Event.ON_STOP)
        super.onDreamingStopped()
    }

    override fun onDestroy() {
        life.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)
        super.onDestroy()
    }
}

@Composable
private fun DreamRoot(actions: Actions, dim: (Boolean) -> Unit) {
    // a screensaver changes slowly: one update a second is plenty
    val live = remember { LiveEntities().apply { update(HomeApp.state.entities.value) } }
    @OptIn(kotlinx.coroutines.FlowPreview::class)
    LaunchedEffect(live) { HomeApp.state.entities.sample(1000).collect { live.update(it) } }
    val ctx = remember { Ctx(live, actions) {} }
    val connected by HomeApp.state.connected.collectAsState()
    val asleep = sleeping(ctx)
    LaunchedEffect(asleep) { dim(asleep) }
    Screensaver(ctx, settled { ambientColours(ctx) }, connected) {}
}
