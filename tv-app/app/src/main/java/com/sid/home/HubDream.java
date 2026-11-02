package com.sid.home;

import android.service.dreams.DreamService;
import android.webkit.WebView;

/**
 * The Hub as the TV's screensaver: its ambient mode (a big clock, what's playing, the bulbs, the weather and the next
 * event, drifting slowly so nothing burns in). Google TV hides third-party screensavers in its settings, so it's
 * switched on over adb: see tv-app/screensaver. Any button press wakes the TV as usual.
 */
public class HubDream extends DreamService {
    private WebView web;

    @Override
    public void onAttachedToWindow() {
        super.onAttachedToWindow();
        setInteractive(false); // a key press ends the screensaver, like any other
        setFullscreen(true);
        setScreenBright(true);
        web = new WebView(this);
        Hub.configure(web, "ambient=1");
        setContentView(web);
        web.loadUrl(Hub.url("ambient=1"));
    }

    @Override
    public void onDetachedFromWindow() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDetachedFromWindow();
    }
}
