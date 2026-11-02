package com.sid.home;

import android.app.Activity;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.WebView;

/**
 * The Hub on the TV: a full-screen WebView pointed at the Hub, which notices the "HomeHubTV" user agent and
 * switches to its TV layout (arrow-key navigation, bigger canvas). The Back button closes an open panel in the
 * Hub first, and only then leaves the app.
 */
public class MainActivity extends Activity {
    private WebView web;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        // No keep-screen-on: left idle, the TV drifts into the screensaver, which is the Hub's own ambient screen
        // (HubDream) once tv-app/screensaver has switched it on.

        // Debug builds can be inspected from the Mac (chrome://inspect, or adb forward to the devtools socket).
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web = new WebView(this);
        Hub.configure(web, null);
        setContentView(web);
        web.requestFocus();
        if (saved == null) web.loadUrl(Hub.url(null));
        else web.restoreState(saved);
    }

    /**
     * On Home Assistant's sign-in page (a one-off), the arrows move between fields like Tab does, so you can sign
     * in with the remote. The Hub itself handles the arrows with its own two-dimensional navigation.
     */
    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        String url = web.getUrl();
        if (url != null && url.contains("/auth/")) {
            int code = e.getKeyCode();
            boolean forward = code == KeyEvent.KEYCODE_DPAD_DOWN || code == KeyEvent.KEYCODE_DPAD_RIGHT;
            boolean backward = code == KeyEvent.KEYCODE_DPAD_UP || code == KeyEvent.KEYCODE_DPAD_LEFT;
            if (forward || backward) {
                return web.dispatchKeyEvent(new KeyEvent(e.getDownTime(), e.getEventTime(), e.getAction(),
                        KeyEvent.KEYCODE_TAB, e.getRepeatCount(), backward ? KeyEvent.META_SHIFT_ON : 0));
            }
        }
        return super.dispatchKeyEvent(e);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        web.evaluateJavascript("window.hubBack ? hubBack() : false", handled -> {
            if ("true".equals(handled)) return;
            if (web.canGoBack()) web.goBack();
            else finish();
        });
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }
}
