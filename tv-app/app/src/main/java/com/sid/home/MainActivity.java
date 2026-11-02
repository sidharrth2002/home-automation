package com.sid.home;

import android.app.Activity;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

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
        // It's a dashboard: keep the screen awake while it's the app in front.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        // Debug builds can be inspected from the Mac (chrome://inspect, or adb forward to the devtools socket).
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true); // the Hub keeps its Home Assistant login in localStorage
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUseWideViewPort(true); // honour the Hub's TV viewport
        s.setLoadWithOverviewMode(true);
        s.setUserAgentString(s.getUserAgentString() + " HomeHubTV/1");
        web.setBackgroundColor(0xFF07070B);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) showOffline();
            }
        });
        setContentView(web);
        web.requestFocus();
        if (saved == null) web.loadUrl(BuildConfig.HUB_URL);
        else web.restoreState(saved);
    }

    /** The Mac is off or the Hub isn't running: say so, and keep retrying. */
    private void showOffline() {
        String html = "<html><body style='margin:0;height:100vh;display:grid;place-items:center;background:#07070b;"
                + "color:#e8e8f0;font:28px -apple-system,Roboto,sans-serif;text-align:center'><div>"
                + "<div style='font-size:44px;margin-bottom:16px'>Can't reach the Hub</div>"
                + "<div style='opacity:.6'>Is the Mac on and <code>./home up</code> running? Trying again…</div></div>"
                + "<script>setTimeout(function(){location.href='" + BuildConfig.HUB_URL + "'},10000)</script></body></html>";
        web.loadDataWithBaseURL(BuildConfig.HUB_URL, html, "text/html", "utf-8", null);
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
