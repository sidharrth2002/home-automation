package com.sid.home

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent

/** Whether Google TV's own home may stay up: only when chosen from the Hub's Google TV tile, until the Hub is back. */
object HomeRedirect {
    const val GOOGLE_TV = "com.google.android.apps.tv.launcherx"
    private const val CHOSEN_FOR_MS = 30 * 60_000L
    @Volatile private var allowUntil = 0L

    fun chooseGoogleTv() { allowUntil = SystemClock.elapsedRealtime() + CHOSEN_FOR_MS }
    fun backInHub() { allowUntil = 0L }
    val googleTvChosen get() = SystemClock.elapsedRealtime() < allowUntil

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
            && !HomeRedirect.googleTvChosen) HomeRedirect.openHub(this)
    }

    override fun onInterrupt() = Unit
}
