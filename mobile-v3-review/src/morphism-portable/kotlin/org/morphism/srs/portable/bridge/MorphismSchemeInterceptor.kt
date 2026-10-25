package org.morphism.srs.portable.bridge

import android.content.Context
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import java.io.ByteArrayInputStream
import java.io.File

class MorphismSchemeInterceptor(private val context: Context): WebViewClient() {
    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
        val uri = request.url
        return uri?.scheme != "morphism"
    }

    override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
        val uri = request.url ?: return null
        if (uri.scheme != "morphism") return null
        val path = uri.path.orEmpty().removePrefix("/")
        val ext = path.substringAfterLast('.', "").lowercase()
        val mime = when (ext) {
            "html" -> "text/html"
            "js" -> "text/javascript"
            "css" -> "text/css"
            "json" -> "application/json"
            "svg" -> "image/svg+xml"
            "png" -> "image/png"
            "jpg", "jpeg" -> "image/jpeg"
            "gif" -> "image/gif"
            "webp" -> "image/webp"
            "woff" -> "font/woff"
            "woff2" -> "font/woff2"
            "ttf" -> "font/ttf"
            else -> "application/octet-stream"
        }
        val isText = mime.startsWith("text/") || mime == "application/json" || mime == "image/svg+xml"
        val encoding = if (isText) "UTF-8" else null
        val headers = mapOf(
            "Access-Control-Allow-Origin" to "*",
            "Access-Control-Allow-Methods" to "GET, OPTIONS",
            "Access-Control-Allow-Headers" to "*"
        )
        try {
            require(path.split('/').none { it == ".." || it == "." } && '\\' !in path)
            val stream = when (uri.host) {
                "app" -> {
                    val assetPath = if (path.isEmpty() || path == "index.html") "web/index.html" else "web/$path"
                    context.assets.open(assetPath)
                }
                "media" -> {
                    require(path.matches(Regex("[0-9a-f]{64}\\.[a-zA-Z0-9]+")))
                    File(context.filesDir, "media/$path").inputStream()
                }
                else -> throw IllegalArgumentException()
            }
            return WebResourceResponse(mime, encoding, 200, "OK", headers, stream)
        } catch (_: Exception) {
            return WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", headers, ByteArrayInputStream(byteArrayOf()))
        }
    }
}
