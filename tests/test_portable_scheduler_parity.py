"""Execute the real Kotlin scheduler on the JVM and compare it with py-fsrs 5.

Run build_portable.py once to populate the official compiler/JDK cache.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from morphism_srs.domain.models import CardScheduleModel
from morphism_srs.domain.scheduler_engine import SchedulerEngine


class TestPortableSchedulerParity(unittest.TestCase):
    def test_real_kotlin_matches_python_for_initial_short_term_and_long_term_reviews(self):
        cache = ROOT / ".build_cache/portable"
        compiler = cache / "kotlin/kotlinc/lib/kotlin-compiler.jar"
        executables = list((cache / "jdk").rglob("java.exe" if os.name == "nt" else "java"))
        if not compiler.exists() or not executables:
            self.skipTest("Build the portable toolchain first")
        engine = SchedulerEngine()
        if len(engine.scheduler.parameters) != 19:
            self.skipTest("Install project dependencies: parity requires fsrs>=5.1.3,<6 with 19 parameters")
        java = executables[0]
        source = ROOT / "src/morphism-portable/kotlin/org/morphism/srs/portable/domain/FsrsV5Scheduler.kt"
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "Parity.kt"
            jar = Path(tmp) / "parity.jar"
            harness.write_text('''import org.morphism.srs.portable.domain.FsrsV5Scheduler
import java.time.Instant
fun main() {
    generateSequence(::readLine).forEach { line ->
        val p=line.split("|")
        val w=if(p[1]=="default") FsrsV5Scheduler.DEFAULT_WEIGHTS else p[1].split(',').map(String::toDouble).toDoubleArray()
        val engine=FsrsV5Scheduler(p[0].toDouble(),w)
        var s=FsrsV5Scheduler.Schedule(null,null,null)
        p.drop(2).forEach { event ->
            val fields=event.split(','); val now=Instant.parse(fields[0]); val rating=fields[1].toInt()
            val result=engine.rate(s,rating,now)
            println("${result.stability}|${result.difficulty}|${result.days}|${result.reps}|${result.lapses}")
            s=FsrsV5Scheduler.Schedule(result.stability,result.difficulty,now,result.reps,result.lapses,2)
        }
    }
}''', encoding="utf-8")
            subprocess.run([str(java), "-cp", str(compiler), "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                "-kotlin-home", str(compiler.parent.parent), "-no-reflect", "-jvm-target", "1.8",
                "-include-runtime", "-d", str(jar), str(source), str(harness)], check=True, capture_output=True)
            rng = random.Random(26)
            lines, expected = [], []
            # Includes every initial rating, all ratings within a day, long gaps,
            # custom folder weights and several retention targets.
            for retention in (0.7, 0.8, 0.9, 0.99):
                for initial in (1, 2, 3, 4):
                    for custom in (False, True):
                        weights = list(engine.scheduler.parameters)
                        if custom:
                            weights[4] = 6.0
                            weights[17] = 0.4
                        reference = SchedulerEngine(retention, weights_json=weights)
                        state = CardScheduleModel(card_id=1)
                        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
                        parts = [str(retention), ",".join(map(str, weights)) if custom else "default"]
                        for i in range(32):
                            if i:
                                now += timedelta(hours=rng.choice((0, 0.5, 23.9, 24, 48, 240, 8760)))
                            rating = initial if i == 0 else rng.randint(1, 4)
                            parts.append(f"{now.isoformat()},{rating}")
                            state, _ = reference.rate_card(state, rating, now=now)
                            expected.append((state.stability, state.difficulty, state.scheduled_days, state.reps, state.lapses))
                        lines.append("|".join(parts))
            result = subprocess.run([str(java), "-jar", str(jar)], input="\n".join(lines)+"\n", capture_output=True, text=True, check=True)
            actual = [tuple(map(float, line.split("|"))) for line in result.stdout.splitlines()]
            self.assertEqual(len(actual), 1024)
            for index, (kotlin, python) in enumerate(zip(actual, expected)):
                with self.subTest(index=index):
                    self.assertAlmostEqual(kotlin[0], python[0], delta=max(abs(python[0])*1e-12,1e-12))
                    self.assertAlmostEqual(kotlin[1], python[1], places=11)
                    self.assertEqual(kotlin[2:], python[2:])


if __name__ == "__main__":
    unittest.main()
