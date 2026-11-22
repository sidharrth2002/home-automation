package com.sid.home

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent

/**
 * Makes the remote's Home button open the Hub app. Google TV sends Home to its own launcher whatever the home role
 * says (and guards that launcher if it's disabled), so this catches the key itself, like remapping apps do. It only
 * filters key events: it never reads what's on screen. Switched on and off with tv-app/home.
 */
class HomeButtonService : AccessibilityService() {
    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode != KeyEvent.KEYCODE_HOME) return false
        if (event.action == KeyEvent.ACTION_UP && !event.isCanceled) {
            startActivity(Intent(this, HomeActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
        }
        return true // the press is ours, down and up
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit
    override fun onInterrupt() = Unit
}
