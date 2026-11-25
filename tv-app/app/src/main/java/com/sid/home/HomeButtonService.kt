package com.sid.home

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import java.io.File

/**
 * Whether Google TV's own home may stay up: when chosen from the Hub's Google TV tile (until the Hub is back), or for a
 * while after the Hub crashed (so a Hub that crashes on launch can't trap the TV in a loop of reopening it).
 * The service runs in its own process (a crash in the Hub can't take the Home button down with it), so these are
 * small files both processes read, not fields.
 */
object HomeRedirect {
    const val GOOGLE_TV = "com.google.android.apps.tv.launcherx"
    private const val CHOSEN_FOR_MS = 30 * 60_000L
    private const val SETTINGS_FOR_MS = 10 * 60_000L
    private const val AFTER_CRASH_MS = 10 * 60_000L
    private const val CHOSEN = "google-tv-chosen-until"
    private const val CRASHED = "hub-crashed-until"

    private fun file(c: Context, name: String) = File(c.filesDir, name)
    private fun until(c: Context, name: String) = runCatching { file(c, name).readText().toLong() }.getOrDefault(0L)
    private fun hold(c: Context, name: String, ms: Long) { runCatching { file(c, name).writeText((System.currentTimeMillis() + ms).toString()) } }

    fun chooseGoogleTv(c: Context) = hold(c, CHOSEN, CHOSEN_FOR_MS)

    /**
     * The TV's settings, opened from the Hub. Google TV draws them as a side panel that belongs to its launcher, so
     * without this the service saw that launcher come up and put the Hub straight back over the panel.
     */
    fun openSettings(c: Context, action: String = android.provider.Settings.ACTION_SETTINGS): Boolean {
        hold(c, CHOSEN, SETTINGS_FOR_MS)
        return runCatching { c.startActivity(Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess
    }
    fun backInHub(c: Context) { file(c, CHOSEN).delete() }
    fun hubCrashed(c: Context) = hold(c, CRASHED, AFTER_CRASH_MS)
    fun leaveGoogleTv(c: Context) = System.currentTimeMillis().let { it < until(c, CHOSEN) || it < until(c, CRASHED) }

    fun openHub(context: Context) = context.startActivity(Intent(context, HomeActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
}

/**
 * Makes the Hub the TV's home. Google TV sends the Home button to its own launcher whatever the home role says (and
 * guards that launcher if it's disabled), so this catches the Home key, and opens the Hub whenever Google TV's home
 * comes up uninvited: at power-on, on waking, or after backing out of an app. It only sees key events and window
 * changes from Google TV's launcher (see res/xml/home_button.xml), never what's on screen. tv-app/home on|off.
 */
class HomeButtonService : AccessibilityService() {
    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode != KeyEvent.KEYCODE_HOME) return false
        if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) HomeRedirect.openHub(this)
        return true // the press is ours, down and up
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED && event.packageName == HomeRedirect.GOOGLE_TV
            && !HomeRedirect.leaveGoogleTv(this)) HomeRedirect.openHub(this)
    }

    override fun onInterrupt() = Unit
}
