package org.morphism.srs.portable.bridge

import android.content.Context
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject
import org.morphism.srs.portable.db.*
import org.morphism.srs.portable.sync.*
import java.util.concurrent.Executors

class MorphismJsBridge(private val context: Context, private val web: WebView) {
    private val store=PortableDatabase(context)
    private val graph=CourseGraphDao(store)
    private val review=ReviewQueueDao(store,graph)
    private val sync=DeltaSyncEngine(store,MediaSyncStore(context))
    private val worker=Executors.newSingleThreadExecutor()
    @Volatile private var syncing=false
    private val guard=Any()
    private fun result(block: () -> Any?): String = synchronized(guard) {
        try { check(!syncing) { "Sincronización en curso" }; JSONObject().put("ok",true).put("data",block()).toString() }
        catch(e: Exception) { JSONObject().put("ok",false).put("error",e.message).toString() }
    }
    @JavascriptInterface fun listCoursesJson()=result { graph.listCoursesJson() }
    @JavascriptInterface fun getCourseGraphJson(courseId: Int)=result { graph.getCourseGraphJson(courseId) }
    @JavascriptInterface fun buildDueQueue(courseId: Int,noteId: Int)=result { review.buildDueQueue(courseId,noteId) }
    @JavascriptInterface fun getCardPromptContextJson(cardId: Int,courseId: Int)=result { review.getCardPromptContextJson(cardId,courseId) }
    @JavascriptInterface fun submitRating(cardId: Int,courseId: Int,rating: Int,durationMs: Int)=result { review.submitRating(cardId,courseId,rating,durationMs) }
    @JavascriptInterface fun undoLastRating()=result { review.undoLastRating() }
    @JavascriptInterface fun lastUndoCard()=result { review.lastUndoCard() }
    @JavascriptInterface fun updateNodePosition(courseId: Int,noteId: Int,x: Double,y: Double)=result { graph.updateNodePosition(courseId,noteId,x,y); true }
    @JavascriptInterface fun stats(courseId: Int)=result { review.stats(courseId) }
    @JavascriptInterface fun getSetting(key: String)=result { require(key in SETTINGS); store.meta(key) }
    @JavascriptInterface fun setSetting(key: String,value: String)=result { require(key in SETTINGS && key!="sync_last_url"); store.setMeta(key,value); true }
    @JavascriptInterface fun themes()=result { org.json.JSONArray().also { list -> context.assets.list("web/themes").orEmpty().filter { it.endsWith(".json") }.sorted().forEach {
        list.put(JSONObject(context.assets.open("web/themes/$it").bufferedReader().use { reader -> reader.readText() })) } } }
    @JavascriptInterface fun synchronize(url: String) {
        synchronized(guard) { if(syncing) return; syncing=true }
        worker.execute {
            val response=try { sync.sync(url) } catch(e: Exception) { JSONObject().put("ok",false).put("error",e.message) }
            synchronized(guard) { syncing=false }
            web.post { web.evaluateJavascript("window.onPortableSyncResult(${response});",null) }
        }
    }
    fun close() { worker.execute { store.close() }; worker.shutdown() }
    companion object { val SETTINGS=setOf("active_course_id","active_theme_id","sync_last_url") }
}
