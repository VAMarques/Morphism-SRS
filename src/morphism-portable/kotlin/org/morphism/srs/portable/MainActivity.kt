package org.morphism.srs.portable

import android.app.Activity
import android.os.Bundle
import android.graphics.Color
import android.view.Window
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.util.Log
import org.morphism.srs.portable.bridge.*

class MainActivity: Activity() {
    private lateinit var web: WebView
    private lateinit var bridge: MorphismJsBridge
    override fun onCreate(state: Bundle?) {
        requestWindowFeature(Window.FEATURE_NO_TITLE)
        super.onCreate(state)
        window.statusBarColor = Color.BLACK
        window.navigationBarColor = Color.BLACK
        web = WebView(this)
        web.setBackgroundColor(Color.BLACK)
        setContentView(web)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            builtInZoomControls = false
            displayZoomControls = false
            textZoom = 100
        }
        web.overScrollMode = WebView.OVER_SCROLL_NEVER
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(msg: ConsoleMessage): Boolean {
                Log.d("MorphismWeb", "${msg.message()} (${msg.sourceId()}:${msg.lineNumber()})")
                return true
            }
        }
        bridge = MorphismJsBridge(this, web)
        web.addJavascriptInterface(bridge, "MorphismNative")
        web.webViewClient = MorphismSchemeInterceptor(this)
        val html = assets.open("web/index.html").bufferedReader().use { it.readText() }
        web.loadDataWithBaseURL("morphism://app/index.html", html, "text/html", "UTF-8", null)
    }
    @Deprecated("Android legacy Back callback")
    override fun onBackPressed() {
        web.evaluateJavascript("window.onPortableBackPressed ? window.onPortableBackPressed() : false") { handled ->
            if (handled != "true") finish()
        }
    }
    override fun onPause() { web.onPause(); super.onPause() }
    override fun onResume() { super.onResume(); web.onResume() }
    override fun onDestroy() {
        web.removeJavascriptInterface("MorphismNative")
        bridge.close()
        web.destroy()
        super.onDestroy()
    }
}
