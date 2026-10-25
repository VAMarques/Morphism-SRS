package org.morphism.srs.portable.sync

import org.json.JSONArray
import org.json.JSONObject
import org.morphism.srs.portable.db.PortableDatabase
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.UUID

class DeltaSyncEngine(private val store: PortableDatabase, private val media: MediaSyncStore) {
    fun sync(rawUrl: String): JSONObject {
        val uri=URI(rawUrl)
        require(uri.scheme=="morphism-sync" && uri.host!=null && uri.port in 1..65535 && uri.userInfo==null) { "Escanea un QR v3 del PC" }
        val fields=uri.rawFragment.orEmpty().split('&').associate { val parts=it.split('=',limit=2); parts[0] to java.net.URLDecoder.decode(parts.getOrElse(1){""},"UTF-8") }
        val key=android.util.Base64.decode(fields["key"].orEmpty(),android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING)
        require(key.size==32) { "Clave de sesión inválida" }
        val expectedUuid=fields["uuid"].orEmpty(); val expectedProfile=fields["profile"] ?: expectedUuid
        require(expectedUuid.isNotBlank() && expectedProfile.isNotBlank()) { "Falta la identidad de la colección" }
        val paired=store.meta("sync_pc_db_uuid"); val profile=store.meta("sync_profile_id")
        require(paired.isBlank() || paired==expectedUuid && (profile.isBlank() || profile==expectedProfile)) { "Este móvil pertenece a otra colección (${store.meta("sync_profile_name")}). No se enviaron repasos." }
        val base="http://${uri.rawAuthority}"
        fun request(path: String, body: JSONObject?=null): ByteArray {
            val aad="${if(body==null) "GET" else "POST"} $path".toByteArray(Charsets.UTF_8)
            val proof=SyncCrypto.seal(key,byteArrayOf(),aad)
            val connection=URL(base+path).openConnection() as HttpURLConnection
            connection.connectTimeout=15000; connection.readTimeout=60000; connection.instanceFollowRedirects=false
            connection.setRequestProperty("X-Morphism-Auth",android.util.Base64.encodeToString(proof,android.util.Base64.URL_SAFE or android.util.Base64.NO_WRAP or android.util.Base64.NO_PADDING))
            try {
                if(body!=null) { connection.requestMethod="POST"; connection.doOutput=true
                    connection.setRequestProperty("Content-Type","application/vnd.morphism.encrypted")
                    connection.outputStream.use { it.write(SyncCrypto.seal(key,body.toString().toByteArray(Charsets.UTF_8),aad+" body ".toByteArray()+proof)) } }
                check(connection.responseCode==200) { "PC HTTP ${connection.responseCode}. Reabre el QR si la sesión caducó." }
                val bytes=connection.inputStream.use { input ->
                    val output=java.io.ByteArrayOutputStream(); val buffer=ByteArray(65536); var total=0
                    while(true) { val n=input.read(buffer); if(n<0) break; total+=n; require(total<=64*1024*1024) { "Respuesta demasiado grande" }; output.write(buffer,0,n) }; output.toByteArray()
                }
                return SyncCrypto.open(key,bytes,aad+" response ".toByteArray()+proof)
            } finally { connection.disconnect() }
        }
        val ping=JSONObject(String(request("/api/v3/sync/ping"),Charsets.UTF_8))
        val pcUuid=ping.getString("db_uuid"); val pcProfile=ping.getString("profile_id")
        require(pcUuid==expectedUuid && pcProfile==expectedProfile && ping.getInt("protocol")==3) { "El servidor no corresponde al QR" }
        val device=store.meta("sync_device_id").ifBlank { UUID.randomUUID().toString().also { store.setMeta("sync_device_id",it) } }
        if(paired.isNotBlank()) {
            do {
            val pending=store.rows("""SELECT l.*,c.uuid card_uuid,o.seq local_id FROM portable_outbox o
                JOIN review_logs l ON l.uuid=o.log_uuid JOIN cards c ON c.id=l.card_id ORDER BY o.seq LIMIT 250""")
            val undoneRows=store.rows("SELECT uuid FROM portable_undone LIMIT 250"); val undone=JSONArray()
            for(i in 0 until undoneRows.length()) undone.put(undoneRows.getJSONObject(i).getString("uuid"))
            val response=JSONObject(String(request("/api/v3/sync/push_delta",JSONObject().put("db_uuid",paired)
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
            } while(store.rows("SELECT 1 FROM portable_outbox LIMIT 1").length()>0 || store.rows("SELECT 1 FROM portable_undone LIMIT 1").length()>0)
        }
        fun downloadSnapshot() {
            store.installSnapshot(request("/api/v3/sync/snapshot"),pcUuid,pcProfile) { manifest -> media.synchronize(manifest) { request(it) } }
        }
        if(paired.isBlank()) downloadSnapshot()
        val since=store.meta("sync_last_pc_seq","0").toLong()
        val delta=JSONObject(String(request("/api/v3/sync/pull_delta?since_seq=$since"),Charsets.UTF_8))
        require(delta.getString("db_uuid")==pcUuid)
        if(delta.optBoolean("snapshot_required")) { downloadSnapshot(); store.setMeta("sync_profile_name",ping.getString("profile_name")); store.setMeta("sync_last_url",rawUrl); return JSONObject().put("ok",true).put("current_seq",store.meta("sync_last_pc_seq")) }
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
            db.execSQL("INSERT OR IGNORE INTO card_schedules(card_id) SELECT id FROM cards")
            store.setMeta("sync_profile_id",pcProfile)
            store.setMeta("sync_profile_name",ping.getString("profile_name"))
            store.setMeta("sync_pc_db_uuid",pcUuid)
            store.setMeta("global_fsrs_weights",delta.opt("global_fsrs_weights") ?: JSONObject.NULL)
            store.setMeta("sync_last_pc_seq",delta.getLong("current_seq"))
            store.setMeta("sync_last_url",rawUrl)
        }
        return JSONObject().put("ok",true).put("current_seq",delta.getLong("current_seq"))
    }
}
