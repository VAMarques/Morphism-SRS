"""Run the actual Kotlin AES-GCM codec and verify Python interoperability."""
import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]


class TestPortableSyncCrypto(unittest.TestCase):
    def test_python_kotlin_interoperability_and_tamper_rejection(self):
        cache = ROOT / ".build_cache/portable"
        compiler = cache / "kotlin/kotlinc/lib/kotlin-compiler.jar"
        java = Path(os.environ["JAVA_HOME"]) / "bin/java.exe" if os.environ.get("JAVA_HOME") else None
        if java is None or not java.exists():
            found = list((cache / "jdk").rglob("java.exe" if os.name == "nt" else "java"))
            java = found[0] if found else None
        if java is None or not compiler.exists():
            self.skipTest("Prepare Kotlin/JDK toolchain or set JAVA_HOME")
        key = bytes(range(32)); nonce = bytes(range(12)); aad = b"POST /sync body request-proof"
        plain = b"review-uuid:123"
        wire = nonce + AESGCM(key).encrypt(nonce, plain, aad)
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "CryptoCheck.kt"
            jar = Path(directory) / "crypto.jar"
            harness.write_text('''import org.morphism.srs.portable.sync.SyncCrypto
import java.util.Base64
fun main(args: Array<String>) {
    val key=ByteArray(32) { it.toByte() }
    val aad="POST /sync body request-proof".toByteArray()
    val wire=Base64.getDecoder().decode(args[0])
    check(String(SyncCrypto.open(key,wire,aad))=="review-uuid:123")
    val tampered=wire.clone(); tampered[tampered.lastIndex]=(tampered.last().toInt() xor 1).toByte()
    check(runCatching { SyncCrypto.open(key,tampered,aad) }.isFailure)
    check(runCatching { SyncCrypto.open(key,wire,"wrong route".toByteArray()) }.isFailure)
    println(Base64.getEncoder().encodeToString(SyncCrypto.seal(key,"from-kotlin".toByteArray(),aad)))
}''', encoding="utf-8")
            source = ROOT / "src/morphism-portable/kotlin/org/morphism/srs/portable/sync/SyncCrypto.kt"
            subprocess.run([str(java), "-cp", str(compiler), "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                            "-kotlin-home", str(compiler.parent.parent), "-no-reflect", "-jvm-target", "1.8",
                            "-include-runtime", "-d", str(jar), str(source), str(harness)], check=True, capture_output=True)
            result = subprocess.run([str(java), "-jar", str(jar), base64.b64encode(wire).decode()], check=True, capture_output=True, text=True)
            response = base64.b64decode(result.stdout.strip())
            self.assertEqual(AESGCM(key).decrypt(response[:12], response[12:], aad), b"from-kotlin")
