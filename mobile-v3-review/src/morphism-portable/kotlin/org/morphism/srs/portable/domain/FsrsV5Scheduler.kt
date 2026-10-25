package org.morphism.srs.portable.domain

import java.time.Instant
import kotlin.math.*

/** FSRS-5, no learning/relearning steps, deterministic whole-day intervals. */
class FsrsV5Scheduler(val retention: Double = 0.8, val w: DoubleArray = DEFAULT_WEIGHTS) {
    data class Schedule(val stability: Double?, val difficulty: Double?, val last: Instant?,
                        val reps: Int = 0, val lapses: Int = 0, val state: Int = 0)
    data class Result(val stability: Double, val difficulty: Double, val days: Int,
                      val elapsed: Double, val reps: Int, val lapses: Int)
    init { require(w.size == 19 && w.all { it.isFinite() }); require(retention in 0.7..0.99) }
    fun retrievability(s: Schedule, now: Instant): Double =
        if (s.last == null || s.stability == null || s.stability <= 0 || s.state == 0) 0.0
        else (1 + FACTOR * max(0.0, (now.toEpochMilli() - s.last.toEpochMilli()) / DAY) / s.stability).pow(-0.5)
    private fun initialDifficulty(rating: Int) = (w[4] - exp(w[5] * (rating - 1)) + 1).coerceIn(1.0, 10.0)
    fun rate(s: Schedule, rating: Int, now: Instant): Result {
        require(rating in 1..4)
        val elapsed = if (s.last == null) 0.0 else max(0.0, (now.toEpochMilli() - s.last.toEpochMilli()) / DAY)
        val stability: Double
        val difficulty: Double
        if (s.last == null || s.state == 0 || s.stability == null || s.difficulty == null) {
            stability = max(0.1, w[rating - 1]); difficulty = initialDifficulty(rating)
        } else {
            val old = s.stability
            val d = s.difficulty
            difficulty = (w[7] * initialDifficulty(4) + (1-w[7]) * (d - w[6]*(rating-3)*(10-d)/9)).coerceIn(1.0, 10.0)
            // py-fsrs 5 uses integer elapsed days for the scheduling curve.
            val r = (1 + FACTOR * floor(elapsed) / old).pow(-0.5)
            stability = if (elapsed < 1) old * exp(w[17] * (rating - 3 + w[18]))
            else if (rating == 1) min(w[11]*d.pow(-w[12])*((old+1).pow(w[13])-1)*exp((1-r)*w[14]), old/exp(w[17]*w[18]))
            else old * (1 + exp(w[8])*(11-d)*old.pow(-w[9])*(exp((1-r)*w[10])-1)*(if (rating==2) w[15] else 1.0)*(if (rating==4) w[16] else 1.0))
        }
        val days = Math.rint(stability / FACTOR * (retention.pow(-2)-1)).toInt().coerceIn(1,36500)
        return Result(stability,difficulty,days,elapsed,s.reps+1,s.lapses+if(rating==1 && s.state==2) 1 else 0)
    }
    companion object {
        const val DAY = 86400000.0
        const val FACTOR = 19.0/81.0
        val DEFAULT_WEIGHTS = doubleArrayOf(0.40255,1.18385,3.173,15.69105,7.1949,0.5345,1.4604,0.0046,1.54575,0.1192,1.01925,1.9395,0.11,0.29605,2.2698,0.2315,2.9898,0.51655,0.6621)
    }
}
