package org.morphism.srs.portable.sync

import org.json.JSONArray
import org.json.JSONObject
import org.morphism.srs.portable.db.PortableDatabase
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLEncoder
import java.util.UUID

class DeltaSyncEngine(private val store: PortableDatabase, private val media: MediaSyncStore) {
    fun sync(rawUrl: String): JSONObject {
        val uri=URI(rawUrl)
        require(uri.scheme in listOf("http","https") && uri.host!=null && uri.userInfo==null) { "URL de sincronización inválida" }
        val token=uri.rawQuery.orEmpty().split('&').firstOrNull { it.startsWith("token=") }?.substringAfter('=')?.let { java.net.URLDecoder.decode(it,"UTF-8") } ?: ""
        require(token.isNotBlank()) { "Falta el token del PC" }
        val base="${uri.scheme}://${uri.rawAuthority}"
        fun request(path: String, body: JSONObject?=null): ByteArray {
            val connection=URL(base+path+(if('?' in path) "&" else "?")+"token="+URLEncoder.encode(token,"UTF-8")).openConnection() as HttpURLConnection
            connection.connectTimeout=15000; connection.readTimeout=60000; connection.instanceFollowRedirects=false
            try {
                if(body!=null) { connection.requestMethod="POST"; connection.doOutput=true
                    connection.setRequestProperty("Content-Type","application/json")
                    connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) } }
                check(connection.responseCode==200) { "PC HTTP ${connection.responseCode}: ${connection.errorStream?.bufferedReader()?.readText().orEmpty().take(300)}" }
                return connection.inputStream.use { it.readBytes() }
            } finally { connection.disconnect() }
        }
        val ping=JSONObject(String(request("/api/v2/sync/ping"),Charsets.UTF_8))
        val pcUuid=ping.getString("db_uuid"); val paired=store.meta("sync_pc_db_uuid")
        require(paired.isBlank() || paired==pcUuid) { "Este móvil está vinculado a otra base de datos del PC." }
        val device=store.meta("sync_device_id").ifBlank { UUID.randomUUID().toString().also { store.setMeta("sync_device_id",it) } }
        if(paired.isNotBlank()) {
            val pending=store.rows("""SELECT l.*,c.uuid card_uuid,o.seq local_id FROM portable_outbox o
                JOIN review_logs l ON l.uuid=o.log_uuid JOIN cards c ON c.id=l.card_id ORDER BY o.seq""")
            val undoneRows=store.rows("SELECT uuid FROM portable_undone"); val undone=JSONArray()
            for(i in 0 until undoneRows.length()) undone.put(undoneRows.getJSONObject(i).getString("uuid"))
            val response=JSONObject(String(request("/api/v2/sync/push_delta",JSONObject().put("db_uuid",paired)
                .put("device_id",device).put("new_review_logs",pending).put("undone_log_uuids",undone)),Charsets.UTF_8))
            store.transaction { db ->
                val seq=response.getLong("max_local_log_id")
                val canonical=response.getJSONObject("log_ids")
                for(i in 0 until pending.length()) {
                    val item=pending.getJSONObject(i); val uuid=item.getString("uuid")
                    val local=store.rows("SELECT * FROM review_logs WHERE uuid=?",uuid).optJSONObject(0)
                    if(local!=null) {
                        if(canonical.has(uuid)) store.upsert(db,"review_logs",local.put("id",canonical.getLong(uuid)),listOf("id"))
                        else db.delete("review_logs","uuid=?",arrayOf(uuid))
                    }
                }
                db.delete("portable_outbox","seq<=?",arrayOf(seq.toString()))
                for(i in 0 until undone.length()) db.delete("portable_undone","uuid=?",arrayOf(undone.getString(i)))
                store.setMeta("sync_last_pushed_log_id",maxOf(seq,store.meta("sync_last_pushed_log_id","0").toLong()))
            }
        }
        val since=store.meta("sync_last_pc_seq","0").toLong()
        val delta=JSONObject(String(request("/api/v2/sync/pull_delta?since_seq=$since"),Charsets.UTF_8))
        require(delta.getString("db_uuid")==pcUuid)
        // Fetch before advancing the cursor. Interrupted media transfer retries safely.
        media.synchronize(delta.getJSONArray("media_manifest")) { request(it) }
        store.transaction { db ->
            db.execSQL("PRAGMA defer_foreign_keys=ON")
            val bootstrap=delta.getString("mode")=="bootstrap"
            if(bootstrap) PortableDatabase.TABLE_KEYS.keys.reversed().forEach { db.delete(it,null,null) }
            else {
                val deletes=delta.getJSONObject("deletes")
                PortableDatabase.TABLE_KEYS.entries.reversed().forEach { (table,keys) ->
                    val rows=deletes.optJSONArray(table) ?: JSONArray()
                    for(i in 0 until rows.length()) {
                        val row=rows.getJSONObject(i)
                        db.delete(table,keys.joinToString(" AND ") { "$it=?" },keys.map { row.get(it).toString() }.toTypedArray())
                    }
                }
            }
            val tables=delta.getJSONObject(if(bootstrap) "tables" else "upserts")
            // Release mutable unique keys before applying their final values.
            // This permits rename swaps and folder reparenting in any row order.
            if(!bootstrap) {
                for(table in listOf("courses","tags","notes","course_folders","edges")) {
                    val rows=tables.optJSONArray(table) ?: JSONArray()
                    for(i in 0 until rows.length()) {
                        val id=rows.getJSONObject(i).getLong("id")
                        when(table) {
                            "courses","tags" -> db.execSQL("UPDATE $table SET name=? WHERE id=?",arrayOf("sync-temp-${UUID.randomUUID()}",id))
                            "notes" -> db.execSQL("UPDATE notes SET external_key=NULL WHERE id=?",arrayOf(id))
                            "course_folders" -> db.execSQL("UPDATE course_folders SET parent_id=NULL WHERE id=?",arrayOf(id))
                            "edges" -> db.execSQL("UPDATE edges SET source_note_id=? WHERE id=?",arrayOf(-id-1000000,id))
                        }
                    }
                }
            }
            PortableDatabase.TABLE_KEYS.forEach { (table,keys) ->
                val rows=tables.optJSONArray(table) ?: JSONArray()
                for(i in 0 until rows.length()) store.upsert(db,table,rows.getJSONObject(i),keys)
            }
            db.rawQuery("PRAGMA foreign_key_check",null).use { check(!it.moveToFirst()) { "Referencias SQL inválidas" } }
            db.delete("sync_oplog",null,null)
            db.execSQL("DELETE FROM portable_undo WHERE card_uuid NOT IN (SELECT uuid FROM cards)")
            store.setMeta("sync_pc_db_uuid",pcUuid)
            store.setMeta("global_fsrs_weights",delta.opt("global_fsrs_weights") ?: JSONObject.NULL)
            store.setMeta("sync_last_pc_seq",delta.getLong("current_seq"))
            store.setMeta("sync_last_url",rawUrl)
        }
        return JSONObject().put("ok",true).put("current_seq",delta.getLong("current_seq"))
    }
}
