package com.sid.home

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.android.resources.Density
import com.android.resources.ScreenOrientation
import com.android.resources.UiMode
import com.sid.home.ha.Demo
import com.sid.home.ha.HomeState
import com.sid.home.ui.Ctx
import com.sid.home.ui.HomeScreen
import org.junit.Rule
import org.junit.Test
import java.io.File
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.ui.unit.dp

/**
 * The native screens rendered with the Hub's demo household (assets/demo.json), at a 1080p TV's size, without a TV:
 *   ./gradlew :app:recordPaparazziDebug   (pictures in app/src/test/snapshots/images)
 *   ./gradlew :app:verifyPaparazziDebug   (fails if a screen changed)
 */
class ScreensTest {
    @get:Rule
    val paparazzi = Paparazzi(
        deviceConfig = DeviceConfig(screenWidth = 1920, screenHeight = 1080, xdpi = 320, ydpi = 320, density = Density.XHIGH,
            orientation = ScreenOrientation.LANDSCAPE, uiMode = UiMode.TELEVISION),
        maxPercentDifference = 0.5,
    )

    private fun demo() = HomeState().also { Demo.load(it, File("src/main/assets/demo.json").readText()) }

    /** The cards below the fold, each on its own (the home screen scrolls; a snapshot is one screen). */
    @Test
    fun money() {
        val home = demo()
        paparazzi.snapshot {
            androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.background(com.sid.home.ui.Hub.bg).padding(24.dp)) {
                com.sid.home.ui.MoneyCard(Ctx(home.entities.value, Demo) {}) {}
            }
        }
    }

    @Test
    fun deskAndHealth() {
        val home = demo()
        paparazzi.snapshot {
            androidx.compose.foundation.layout.Row(androidx.compose.ui.Modifier.background(com.sid.home.ui.Hub.bg).padding(24.dp)) {
                com.sid.home.ui.DeskCard(Ctx(home.entities.value, Demo) {}, androidx.compose.ui.Modifier.weight(1f))
                androidx.compose.foundation.layout.Spacer(androidx.compose.ui.Modifier.width(14.dp))
                com.sid.home.ui.HealthCard(Ctx(home.entities.value, Demo) {}, true, 2, androidx.compose.ui.Modifier.weight(1.4f))
            }
        }
    }

    @Test
    fun home() {
        val home = demo()
        paparazzi.snapshot { HomeScreen(Ctx(home.entities.value, Demo) {}, connected = true, events = home.events.value) }
    }

    @Test
    fun music() {
        val home = demo()
        paparazzi.snapshot { HomeScreen(Ctx(home.entities.value, Demo) {}, connected = true, start = com.sid.home.ui.Page.MUSIC) }
    }

    @Test
    fun lights() {
        val home = demo()
        paparazzi.snapshot { HomeScreen(Ctx(home.entities.value, Demo) {}, connected = true, start = com.sid.home.ui.Page.LIGHTS) }
    }
}
