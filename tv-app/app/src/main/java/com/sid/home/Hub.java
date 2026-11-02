package com.sid.home;

import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** What the app and the screensaver share: how the Hub is loaded, and what to show when it can't be reached. */
final class Hub {
    private Hub() {}

    /**
     * The Hub's address with a throwaway query string. Home Assistant serves /local/ with long-lived caching, so a
     * plain load could keep showing an old Hub after an update; its scripts and styles carry content hashes, so those
     * still cache properly. `extra` adds query parameters, e.g. "ambient=1" for the screensaver.
     */
    static String url(String extra) {
        String base = BuildConfig.HUB_URL + (BuildConfig.HUB_URL.contains("?") ? "&" : "?") + "app=" + System.currentTimeMillis();
        return extra == null ? base : base + "&" + extra;
    }

    /** JavaScript and storage on (the Hub keeps its Home Assistant login in localStorage, shared with the screensaver). */
    static void configure(WebView web, String extra) {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUseWideViewPort(true); // honour the Hub's TV viewport
        s.setLoadWithOverviewMode(true);
        s.setUserAgentString(s.getUserAgentString() + " HomeHubTV/1");
        web.setBackgroundColor(0xFF07070B);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) showOffline(view, extra);
            }
        });
    }

    /** The Mac is off or the Hub isn't running: say so (with a clock, so a screensaver is still a screensaver) and retry. */
    static void showOffline(WebView web, String extra) {
        String retry = BuildConfig.HUB_URL + "?app='+Date.now()+'" + (extra == null ? "" : "&" + extra);
        String html = "<html><body style='margin:0;height:100vh;display:grid;place-items:center;background:#07070b;"
                + "color:#e8e8f0;font:28px -apple-system,Roboto,sans-serif;text-align:center'><div>"
                + "<div id=t style='font:200 140px Georgia,serif;opacity:.9'></div>"
                + "<div style='opacity:.55;margin-top:18px'>The Hub isn't reachable. Is the Mac on and <code>./home up</code> running?</div></div>"
                + "<script>function c(){var d=new Date();t.textContent=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)}"
                + "c();setInterval(c,10000);setTimeout(function(){location.href='" + retry + "'},30000)</script></body></html>";
        web.loadDataWithBaseURL(BuildConfig.HUB_URL, html, "text/html", "utf-8", null);
    }
}
