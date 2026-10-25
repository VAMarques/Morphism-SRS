package org.morphism.srs.portable.db

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject

class PortableDatabase(context: Context) : SQLiteOpenHelper(context, "morphism_portable.db", null, 1) {
    private val assets = context.assets
    init { setWriteAheadLoggingEnabled(true) }
    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
        db.execSQL("PRAGMA synchronous=NORMAL")
    }
    override fun onCreate(db: SQLiteDatabase) {
        val version = db.rawQuery("SELECT sqlite_version()", null).use { it.moveToFirst(); it.getString(0).split('.').map(String::toInt) }
        val strict = version[0] > 3 || version[1] >= 37
        val statement = StringBuilder()
        var fts5 = true
        val json1 = try { db.rawQuery("SELECT json_object('a',1)",null).use { it.moveToFirst() }; true }
            catch (_: android.database.sqlite.SQLiteException) { false }
        for (line in assets.open("schema_v2.sql").bufferedReader().readLines()) {
            val clean = line.substringBefore("--").trim()
            if (clean.isEmpty()) continue
            statement.append(clean).append('\n')
            val sql = statement.toString().trim()
            val trigger = sql.startsWith("CREATE TRIGGER", true)
            if (!clean.endsWith(';') || (trigger && !clean.endsWith("END;", true))) continue
            // Android builds without FTS5 still use the exact relational tables.
            // Desktop-only full-text indexing is never queried by this companion.
            if ((fts5 || !sql.contains("cards_fts")) && (json1 || !sql.startsWith("CREATE TRIGGER IF NOT EXISTS trg_sync_"))) {
                try { db.execSQL(if (strict) sql else sql.replace(") STRICT;", ");")) }
                catch (e: android.database.sqlite.SQLiteException) {
                    if (sql.startsWith("CREATE VIRTUAL TABLE") && e.message.orEmpty().contains("no such module: fts5")) fts5 = false
                    else throw e
                }
            }
            statement.clear()
        }
        db.execSQL("CREATE TABLE portable_outbox(seq INTEGER PRIMARY KEY AUTOINCREMENT, log_uuid TEXT UNIQUE NOT NULL)")
        db.execSQL("CREATE TABLE portable_undo(uuid TEXT PRIMARY KEY, schedule_json TEXT NOT NULL, card_uuid TEXT NOT NULL)")
        db.execSQL("CREATE TABLE portable_undone(uuid TEXT PRIMARY KEY)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) { error("Unsupported database upgrade") }
    @Synchronized fun <T> transaction(block: (SQLiteDatabase) -> T): T {
        val db = writableDatabase
        db.beginTransaction()
        try { val result = block(db); db.setTransactionSuccessful(); return result }
        finally { db.endTransaction() }
    }
    fun rows(sql: String, vararg args: Any): JSONArray = writableDatabase.rawQuery(sql, args.map { it.toString() }.toTypedArray()).use { c ->
        val result = JSONArray()
        while (c.moveToNext()) {
            val row = JSONObject()
            c.columnNames.forEachIndexed { i, name -> row.put(name, when (c.getType(i)) {
                android.database.Cursor.FIELD_TYPE_NULL -> JSONObject.NULL
                android.database.Cursor.FIELD_TYPE_INTEGER -> c.getLong(i)
                android.database.Cursor.FIELD_TYPE_FLOAT -> c.getDouble(i)
                else -> c.getString(i)
            }) }
            result.put(row)
        }
        result
    }
    fun meta(key: String, fallback: String = ""): String = writableDatabase.rawQuery("SELECT value_json FROM app_meta WHERE key=?", arrayOf(key)).use {
        if (it.moveToFirst()) JSONArray("[${it.getString(0)}]").get(0).toString() else fallback
    }
    fun setMeta(key: String, value: Any) {
        val json=JSONArray().put(value).toString().let { it.substring(1,it.length-1) }
        writableDatabase.execSQL("INSERT OR REPLACE INTO app_meta VALUES (?,?)", arrayOf(key, json))
    }
    fun upsert(db: SQLiteDatabase, table: String, row: JSONObject, keys: List<String>) {
        require(table in TABLE_KEYS)
        val values = ContentValues()
        row.keys().forEach { key ->
            when (val v = row.get(key)) {
                JSONObject.NULL -> values.putNull(key)
                is Int -> values.put(key, v)
                is Long -> values.put(key, v)
                is Double -> values.put(key, v)
                is Boolean -> values.put(key, if (v) 1 else 0)
                else -> values.put(key, v.toString())
            }
        }
        // UPDATE preserves children; SQLite REPLACE would cascade-delete them.
        val where = keys.joinToString(" AND ") { "$it=?" }
        val args = keys.map { row.get(it).toString() }.toTypedArray()
        if (table == "review_logs") db.delete(table, "uuid=? AND id<>?", arrayOf(row.getString("uuid"), row.get("id").toString()))
        if (db.update(table, values, where, args) == 0) db.insertOrThrow(table, null, values)
    }
    companion object {
        val TABLE_KEYS = linkedMapOf("course_folders" to listOf("id"), "courses" to listOf("id"), "notes" to listOf("id"),
            "course_notes" to listOf("course_id", "note_id"), "cards" to listOf("id"), "card_schedules" to listOf("card_id"),
            "edges" to listOf("id"), "tags" to listOf("id"), "note_tags" to listOf("note_id", "tag_id"),
            "review_logs" to listOf("id"), "media_assets" to listOf("sha256_hash"), "scratchbook_pages" to listOf("id"))
    }
}
