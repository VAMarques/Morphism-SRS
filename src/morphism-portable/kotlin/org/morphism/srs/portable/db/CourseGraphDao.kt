package org.morphism.srs.portable.db

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import org.morphism.srs.portable.domain.FsrsV5Scheduler

class CourseGraphDao(val store: PortableDatabase) {
    fun listCoursesJson(): JSONArray = store.rows("""SELECT c.*,count(DISTINCT cn.note_id) node_count,
        count(DISTINCT CASE WHEN s.is_suspended=0 AND s.is_buried=0 AND s.state!=0 AND
        (julianday(s.due_at)<=julianday('now') OR s.state IN (1,3)) THEN ca.id END) due_count
        FROM courses c LEFT JOIN course_notes cn ON cn.course_id=c.id
        LEFT JOIN cards ca ON ca.note_id=cn.note_id LEFT JOIN card_schedules s ON s.card_id=ca.id
        GROUP BY c.id ORDER BY c.display_order,c.id""")
    fun getCourseGraphJson(courseId: Int): JSONObject {
        val nodes = store.rows("""SELECT n.*,cn.pos_x graph_x,cn.pos_y graph_y FROM course_notes cn
            JOIN notes n ON n.id=cn.note_id WHERE cn.course_id=? ORDER BY n.id""",courseId)
        val cards = store.rows("""SELECT c.*,s.* FROM cards c JOIN course_notes cn ON cn.note_id=c.note_id
            JOIN card_schedules s ON s.card_id=c.id WHERE cn.course_id=? ORDER BY c.note_id,c.step_order,c.id""",courseId)
        val retention = retention(courseId)
        val now = Instant.now()
        val groups = (0 until cards.length()).map { cards.getJSONObject(it) }.groupBy { it.getInt("note_id") }
        for (i in 0 until nodes.length()) {
            val n = nodes.getJSONObject(i)
            n.put("pos_x",n.getDouble("graph_x")).put("pos_y",n.getDouble("graph_y"))
            val active = groups[n.getInt("id")].orEmpty().filter { it.getInt("is_suspended")==0 && it.getInt("is_buried")==0 }
            val threshold = if (n.isNull("desired_retention")) retention else n.getDouble("desired_retention")
            n.put("r_min",active.minOfOrNull { retrievability(it,now) } ?: 0.0)
            val newCount = active.count { it.getInt("state")==0 }
            val learningCount = active.count { it.getInt("state")==1 }
            n.put("new_count", newCount)
            n.put("learning_count", learningCount)
            n.put("is_incomplete", newCount > 0 || learningCount > 0)
            n.put("card_count",groups[n.getInt("id")].orEmpty().size)
            n.put("due_count",active.count { isDue(it,threshold,now) })
            n.put("isDue",n.getInt("due_count")>0)
        }
        return JSONObject().put("nodes",nodes).put("cards",cards).put("edges",store.rows("SELECT * FROM edges WHERE course_id=?",courseId))
    }
    fun retention(courseId: Int): Double = store.rows("SELECT desired_retention FROM courses WHERE id=?",courseId).optJSONObject(0)?.getDouble("desired_retention") ?: 0.8
    fun updateNodePosition(courseId: Int, noteId: Int, x: Double, y: Double) {
        require(x.isFinite() && y.isFinite())
        store.writableDatabase.execSQL("UPDATE course_notes SET pos_x=?,pos_y=? WHERE course_id=? AND note_id=?", arrayOf(x,y,courseId,noteId))
    }
    companion object {
        fun schedule(row: JSONObject) = FsrsV5Scheduler.Schedule(
            if(row.isNull("stability")) null else row.getDouble("stability"),
            if(row.isNull("difficulty")) null else row.getDouble("difficulty"),
            if(row.isNull("last_review_at")) null else Instant.parse(row.getString("last_review_at")),
            row.optInt("reps"),row.optInt("lapses"),row.optInt("state"))
        fun retrievability(row: JSONObject, now: Instant) = FsrsV5Scheduler().retrievability(schedule(row),now)
        fun isDue(row: JSONObject, retention: Double, now: Instant) = row.optInt("is_suspended")==0 && row.optInt("is_buried")==0 &&
            row.optInt("state")!=0 && !row.isNull("last_review_at") &&
            (!Instant.parse(row.getString("due_at")).isAfter(now) || row.optInt("state")==1 || row.optInt("state")==3 || retrievability(row,now)<retention)
    }
}
