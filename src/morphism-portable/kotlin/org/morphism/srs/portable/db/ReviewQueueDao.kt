package org.morphism.srs.portable.db

import org.json.JSONArray
import org.json.JSONObject
import org.morphism.srs.portable.domain.FsrsV5Scheduler
import java.time.Instant
import java.util.UUID

class ReviewQueueDao(private val store: PortableDatabase, private val graph: CourseGraphDao) {
    fun buildDueQueue(courseId: Int, noteId: Int = 0): JSONArray {
        store.writableDatabase.execSQL("INSERT OR IGNORE INTO card_schedules(card_id) SELECT id FROM cards")
        val data = graph.getCourseGraphJson(courseId)
        val nodes = data.getJSONArray("nodes")
        val ids = (0 until nodes.length()).map { nodes.getJSONObject(it).getInt("id") }
        val degree = ids.associateWith { 0 }.toMutableMap()
        val adj = ids.associateWith { mutableListOf<Int>() }
        val edges = data.getJSONArray("edges")
        for(i in 0 until edges.length()) {
            val e=edges.getJSONObject(i); val a=e.getInt("source_note_id"); val b=e.getInt("target_note_id")
            if(a in degree && b in degree) { adj.getValue(a).add(b); degree[b]=degree.getValue(b)+1 }
        }
        val queue=java.util.ArrayDeque(ids.filter { degree[it]==0 }); val ordered=mutableListOf<Int>()
        while(queue.isNotEmpty()) { val id=queue.removeFirst(); ordered.add(id)
            adj.getValue(id).forEach { degree[it]=degree.getValue(it)-1; if(degree[it]==0) queue.add(it) } }
        ordered.addAll(ids.filter { it !in ordered })
        val cards=data.getJSONArray("cards"); val now=Instant.now(); val result=JSONArray()
        ordered.filter { noteId==0 || it==noteId }.forEach { id ->
            val n=(0 until nodes.length()).map { nodes.getJSONObject(it) }.first { it.getInt("id")==id }
            val retention=if(n.isNull("desired_retention")) graph.retention(courseId) else n.getDouble("desired_retention")
            for(i in 0 until cards.length()) { val c=cards.getJSONObject(i)
                if(c.getInt("note_id")==id && (CourseGraphDao.isDue(c,retention,now) || (noteId != 0 && c.optInt("state") == 0))) result.put(c.getInt("id")) }
        }
        if (result.length() == 0 && noteId != 0) {
            for (i in 0 until cards.length()) {
                val c = cards.getJSONObject(i)
                if (c.getInt("note_id") == noteId && c.optInt("is_suspended", 0) == 0 && c.optInt("is_buried", 0) == 0) {
                    result.put(c.getInt("id"))
                }
            }
        }
        return result
    }
    private fun scheduler(courseId: Int, note: JSONObject): FsrsV5Scheduler {
        // A shared card has one canonical schedule, matching the desktop note owner.
        val owner=if(note.isNull("course_id")) 0 else note.getInt("course_id")
        val config=store.rows("""WITH RECURSIVE ancestors(id,parent_id,weights,depth) AS (
            SELECT f.id,f.parent_id,f.fsrs_weights_json,0 FROM courses c JOIN course_folders f ON f.id=c.folder_id WHERE c.id=?
            UNION ALL SELECT f.id,f.parent_id,f.fsrs_weights_json,a.depth+1 FROM course_folders f JOIN ancestors a ON f.id=a.parent_id WHERE a.depth<32)
            SELECT weights FROM ancestors WHERE weights IS NOT NULL ORDER BY depth LIMIT 1""",owner).optJSONObject(0)
        val raw=config?.optString("weights", "")?.takeIf { it.isNotBlank() && it!="null" } ?: store.meta("global_fsrs_weights")
        val weights=raw.takeIf { it.isNotBlank() && it!="null" }?.let { JSONArray(it) }
        val w=if(weights!=null && weights.length() in listOf(17,19)) DoubleArray(19) { if(it<weights.length()) weights.getDouble(it) else FsrsV5Scheduler.DEFAULT_WEIGHTS[it] } else FsrsV5Scheduler.DEFAULT_WEIGHTS
        return FsrsV5Scheduler(if(note.isNull("desired_retention")) graph.retention(owner) else note.getDouble("desired_retention"),w)
    }
    fun getCardPromptContextJson(cardId: Int, courseId: Int): JSONObject {
        val card=store.rows("SELECT * FROM cards WHERE id=?",cardId).getJSONObject(0)
        require(store.rows("SELECT 1 FROM course_notes WHERE course_id=? AND note_id=?",courseId,card.getInt("note_id")).length()>0)
        val note=store.rows("SELECT * FROM notes WHERE id=?",card.getInt("note_id")).getJSONObject(0)
        val siblings=store.rows("SELECT * FROM cards WHERE note_id=? ORDER BY step_order,id",card.getInt("note_id"))
        val mode=note.getString("review_mode"); val conditioning=JSONArray(); var after=false
        for(i in 0 until siblings.length()) { val s=siblings.getJSONObject(i)
            if(s.getInt("id")==cardId) { after=true; continue }
            if(mode=="cloze" || mode=="serial" && !after) conditioning.put(s.put("position",if(after) "after" else "before")) }
        store.writableDatabase.execSQL("INSERT OR IGNORE INTO card_schedules(card_id) SELECT id FROM cards WHERE id=?",arrayOf(cardId))
        val schedule=store.rows("SELECT * FROM card_schedules WHERE card_id=?",cardId).getJSONObject(0)
        val intervals=JSONObject(); val now=Instant.now(); val engine=scheduler(courseId,note)
        for(rating in 1..4) intervals.put(rating.toString(),"${engine.rate(CourseGraphDao.schedule(schedule),rating,now).days}d")
        return JSONObject().put("card",card).put("note",note).put("review_mode",mode).put("conditioning_siblings",conditioning).put("intervals_preview",intervals)
    }
    fun submitRating(cardId: Int, courseId: Int, rating: Int, durationMs: Int): JSONObject = store.transaction { db ->
        require(durationMs>=0)
        val ctx=getCardPromptContextJson(cardId,courseId); val card=ctx.getJSONObject("card")
        val previous=store.rows("SELECT * FROM card_schedules WHERE card_id=?",cardId).getJSONObject(0)
        require(previous.getInt("is_suspended")==0 && previous.getInt("is_buried")==0)
        val now=Instant.now(); val result=scheduler(courseId,ctx.getJSONObject("note")).rate(CourseGraphDao.schedule(previous),rating,now)
        val next=JSONObject(previous.toString()).put("state",2).put("step",JSONObject.NULL).put("stability",result.stability).put("difficulty",result.difficulty)
            .put("due_at",now.plusSeconds(result.days*86400L).toString()).put("last_review_at",now.toString())
            .put("reps",result.reps).put("lapses",result.lapses).put("scheduled_days",result.days).put("elapsed_days",Math.rint(result.elapsed).toInt())
        val uuid=UUID.randomUUID().toString()
        val id=store.rows("SELECT min(coalesce((SELECT min(id) FROM review_logs),0),0)-1 id").getJSONObject(0).getLong("id")
        val log=JSONObject().put("id",id).put("uuid",uuid).put("card_id",cardId).put("rating",rating).put("reviewed_at",now.toString()).put("duration_ms",durationMs)
            .put("elapsed_days",result.elapsed).put("scheduled_days",result.days)
        listOf("state","step","stability","difficulty","due_at").forEach { log.put("prev_$it",previous.get(it)).put("new_$it",next.get(it)) }
        log.put("prev_last_review_at",previous.get("last_review_at"))
        store.upsert(db,"card_schedules",next,listOf("card_id")); store.upsert(db,"review_logs",log,listOf("id"))
        db.execSQL("INSERT INTO portable_outbox(log_uuid) VALUES (?)",arrayOf(uuid))
        db.execSQL("INSERT INTO portable_undo VALUES (?,?,?)",arrayOf(uuid,previous.toString(),card.getString("uuid")))

        // Gamification stats update (Streak and XP decoupled from review logs)
        db.execSQL("CREATE TABLE IF NOT EXISTS gamification_stats (id INTEGER PRIMARY KEY CHECK (id = 1), streak_count INTEGER NOT NULL DEFAULT 0, total_xp REAL NOT NULL DEFAULT 0.0, last_login_at TEXT, updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
        db.execSQL("INSERT OR IGNORE INTO gamification_stats (id, streak_count, total_xp, last_login_at) VALUES (1, 0, 0.0, NULL)")
        val gRow = store.rows("SELECT streak_count, total_xp, last_login_at FROM gamification_stats WHERE id = 1").optJSONObject(0)
        val curStreak = gRow?.optInt("streak_count", 0) ?: 0
        val lastLoginRaw = gRow?.optString("last_login_at", "")?.takeIf { it.isNotBlank() && it != "null" }
        val nowStr = now.toString()
        var newStreak = 1
        var newLoginAt = nowStr
        if (lastLoginRaw == null) {
            newStreak = 1
            newLoginAt = nowStr
        } else {
            val elapsedHours = try {
                val lastInstant = Instant.parse(lastLoginRaw)
                java.time.Duration.between(lastInstant, now).toMillis() / 3600000.0
            } catch (_: Exception) { 999.0 }
            if (elapsedHours < 18.0) {
                newStreak = maxOf(1, curStreak)
                newLoginAt = lastLoginRaw
            } else if (elapsedHours <= 32.0) {
                newStreak = curStreak + 1
                newLoginAt = nowStr
            } else {
                newStreak = 1
                newLoginAt = nowStr
            }
        }
        db.execSQL(
            "UPDATE gamification_stats SET streak_count = ?, total_xp = total_xp + 1.0, last_login_at = ?, updated_at = ? WHERE id = 1",
            arrayOf(newStreak, newLoginAt, nowStr)
        )

        next
    }
    fun undoLastRating(): Boolean = store.transaction { db ->
        val item=store.rows("SELECT rowid, * FROM portable_undo ORDER BY rowid DESC LIMIT 1").optJSONObject(0)
        if(item==null) false else {
            val uuid=item.getString("uuid")
            val card=store.rows("SELECT id FROM cards WHERE uuid=?",item.getString("card_uuid")).optJSONObject(0)
            if(card!=null) {
                val cardId=card.getInt("id")
                val last=store.rows("SELECT uuid FROM review_logs WHERE card_id=? ORDER BY julianday(reviewed_at) DESC,uuid DESC LIMIT 1",cardId).optJSONObject(0)
                require(last?.getString("uuid")==uuid) { "La tarjeta recibió otro repaso; inicia una sesión nueva." }
                val log=store.rows("SELECT id FROM review_logs WHERE uuid=?",uuid).getJSONObject(0)
                var restored=JSONObject(item.getString("schedule_json")).put("card_id",cardId)
                if(log.getLong("id")>0) {
                    // After synchronization, earlier concurrent reviews may have
                    // changed the baseline. Replay the surviving canonical history.
                    val cardRow=store.rows("SELECT * FROM cards WHERE id=?",cardId).getJSONObject(0)
                    val note=store.rows("SELECT * FROM notes WHERE id=?",cardRow.getInt("note_id")).getJSONObject(0)
                    val engine=scheduler(0,note)
                    val known=store.rows("SELECT * FROM review_logs WHERE card_id=? ORDER BY julianday(reviewed_at),uuid",cardId)
                    val first=known.getJSONObject(0)
                    val current=store.rows("SELECT * FROM card_schedules WHERE card_id=?",cardId).getJSONObject(0)
                    var historyLapses=0
                    for(i in 0 until known.length()) { val e=known.getJSONObject(i); if(e.getInt("rating")==1 && e.getInt("prev_state")==2) historyLapses++ }
                    listOf("state","step","stability","difficulty","due_at","last_review_at").forEach {
                        restored.put(it,first.get("prev_$it")) }
                    if(restored.isNull("due_at")) restored.put("due_at",cardRow.getString("created_at"))
                    restored.put("reps",maxOf(0,current.getInt("reps")-known.length()))
                        .put("lapses",maxOf(0,current.getInt("lapses")-historyLapses)).put("elapsed_days",0)
                    val history=store.rows("SELECT * FROM review_logs WHERE card_id=? AND uuid<>? ORDER BY julianday(reviewed_at),uuid",cardId,uuid)
                    for(i in 0 until history.length()) {
                        val event=history.getJSONObject(i); val at=Instant.parse(event.getString("reviewed_at"))
                        val r=engine.rate(CourseGraphDao.schedule(restored),event.getInt("rating"),at)
                        restored.put("state",2).put("step",JSONObject.NULL).put("stability",r.stability).put("difficulty",r.difficulty)
                            .put("last_review_at",at.toString()).put("due_at",at.plusSeconds(r.days*86400L).toString())
                            .put("reps",r.reps).put("lapses",r.lapses).put("scheduled_days",r.days).put("elapsed_days",Math.rint(r.elapsed).toInt())
                    }
                }
                store.upsert(db,"card_schedules",restored,listOf("card_id"))
            }
            // Always enqueue a tombstone, including when a push acknowledgement was lost.
            db.execSQL("INSERT OR IGNORE INTO portable_undone VALUES (?)",arrayOf(uuid))
            db.delete("review_logs","uuid=?",arrayOf(uuid)); db.delete("portable_outbox","log_uuid=?",arrayOf(uuid))
            db.delete("portable_undo","uuid=?",arrayOf(uuid)); true
        }
    }
    fun lastUndoCard(): Int = store.rows("""SELECT c.id FROM portable_undo u JOIN cards c ON c.uuid=u.card_uuid
        WHERE u.rowid=(SELECT max(rowid) FROM portable_undo)
        AND u.uuid=(SELECT uuid FROM review_logs WHERE card_id=c.id ORDER BY julianday(reviewed_at) DESC,uuid DESC LIMIT 1)
        LIMIT 1""").optJSONObject(0)?.getInt("id") ?: 0
    fun stats(courseId: Int): JSONObject {
        val result=store.rows("""SELECT count(*) total_cards,
            sum(CASE WHEN s.is_suspended=0 AND s.is_buried=0 AND (s.state=0 OR julianday(s.due_at)<=julianday('now')) THEN 1 ELSE 0 END) due_today
            FROM cards c JOIN course_notes cn ON cn.note_id=c.note_id JOIN card_schedules s ON s.card_id=c.id WHERE cn.course_id=?""",courseId).getJSONObject(0)
        val gRow = store.rows("SELECT streak_count, total_xp FROM gamification_stats WHERE id = 1").optJSONObject(0)
        val streak = gRow?.optInt("streak_count", 0) ?: 0
        val xp = gRow?.optDouble("total_xp", 0.0) ?: 0.0
        return result.put("retention",graph.retention(courseId)).put("streak_count",streak).put("total_xp",xp).put("states",store.rows("""SELECT s.state,count(*) count FROM card_schedules s JOIN cards c ON c.id=s.card_id
            JOIN course_notes cn ON cn.note_id=c.note_id WHERE cn.course_id=? GROUP BY s.state""",courseId))
            .put("heatmap",store.rows("""SELECT date(l.reviewed_at) day,count(*) count FROM review_logs l JOIN cards c ON c.id=l.card_id
            JOIN course_notes cn ON cn.note_id=c.note_id WHERE cn.course_id=? AND julianday(l.reviewed_at)>=julianday('now','-28 days') GROUP BY day""",courseId))
    }
}
