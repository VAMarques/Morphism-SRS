package org.morphism.srs.portable.bridge

import android.content.Context
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject
import org.morphism.srs.portable.db.*
import org.morphism.srs.portable.sync.*
import java.util.concurrent.Executors

class MorphismJsBridge(private val context: Context, private val web: WebView) {
    private val profiles=context.getSharedPreferences("portable_profiles",Context.MODE_PRIVATE)
    private var store=PortableDatabase(context,profiles.getString("active_db","morphism_portable.db")!!)
    private var graph=CourseGraphDao(store)
    private var review=ReviewQueueDao(store,graph)
    private var sync=DeltaSyncEngine(store,MediaSyncStore(context))
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
    @JavascriptInterface fun setSetting(key: String,value: String)=result { require(key in setOf("active_course_id","active_theme_id")); store.setMeta(key,value); true }
    @JavascriptInterface fun themes()=result { org.json.JSONArray().also { list -> context.assets.list("web/themes").orEmpty().filter { it.endsWith(".json") }.sorted().forEach {
        list.put(JSONObject(context.assets.open("web/themes/$it").bufferedReader().use { reader -> reader.readText() })) } } }
    @JavascriptInterface fun synchronize(url: String) {
        synchronized(guard) { if(syncing) return; syncing=true }
        worker.execute {
            try {
                val uri=java.net.URI(url)
                val fields=uri.rawFragment.orEmpty().split('&').associate { val p=it.split('=',limit=2); p[0] to java.net.URLDecoder.decode(p.getOrElse(1){""},"UTF-8") }
                val target=fields["uuid"].orEmpty()
                java.util.UUID.fromString(target)
                val current=store.meta("sync_pc_db_uuid")
                val currentName=store.meta("sync_profile_name")
                if(current.isNotBlank() && current!=target) {
                    web.post {
                        android.app.AlertDialog.Builder(context).setTitle("Cambiar de perfil")
                            .setMessage("Este QR pertenece a ${fields["user"]?.take(80) ?: target.take(8)}. Se abrirá una colección independiente. Los repasos pendientes de ${currentName} se conservarán en su perfil.")
                            .setPositiveButton("Abrir perfil") { _,_ -> worker.execute { finishSync(url,target) } }
                            .setNegativeButton("Cancelar") { _,_ -> report(JSONObject().put("ok",false).put("error","Cambio de perfil cancelado")) }
                            .setOnCancelListener { report(JSONObject().put("ok",false).put("error","Cambio de perfil cancelado")) }.show()
                    }
                } else finishSync(url,null)
            } catch(e: Exception) { report(JSONObject().put("ok",false).put("error",e.message)) }
        }
    }
    private fun finishSync(url: String,target: String?) {
        var candidate: PortableDatabase?=null
        val response=try {
            if(target==null) {
                sync.sync(url).also { profiles.edit().putString("profile:"+store.meta("sync_pc_db_uuid"),store.fileName).apply() }
            } else {
                val next=PortableDatabase(context,profiles.getString("profile:$target","profile-$target.db")!!)
                candidate=next
                val result=DeltaSyncEngine(next,MediaSyncStore(context)).sync(url)
                store.close(); store=next; candidate=null
                graph=CourseGraphDao(store); review=ReviewQueueDao(store,graph); sync=DeltaSyncEngine(store,MediaSyncStore(context))
                profiles.edit().putString("active_db",store.fileName).putString("profile:$target",store.fileName).apply()
                result
            }
        } catch(e: Exception) { JSONObject().put("ok",false).put("error",e.message) }
        finally { candidate?.close() }
        report(response)
    }
    private fun report(response: JSONObject) {
        synchronized(guard) { syncing=false }
        web.post { web.evaluateJavascript("window.onPortableSyncResult(${response});",null) }
    }
    @JavascriptInterface fun scanQr() {
        web.post { (context as android.app.Activity).startActivityForResult(android.content.Intent(context,org.morphism.srs.portable.QrScannerActivity::class.java),70) }
    }
    fun close() { worker.execute { store.close() }; worker.shutdown() }
    companion object { val SETTINGS=setOf("active_course_id","active_theme_id","sync_last_url","sync_profile_name","sync_pc_db_uuid") }
}
