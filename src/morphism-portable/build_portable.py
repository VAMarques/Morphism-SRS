"""Build the Android companion from source, without Android Studio or a base APK.

python src/morphism-portable/build_portable.py [--prepare-only]
Downloads official tools into .build_cache; subsequent builds work offline.
An existing JDK 17+ or Android SDK can be supplied through JAVA_HOME/ANDROID_HOME.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import tarfile
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CACHE = ROOT / ".build_cache" / "portable"
WINDOWS = os.name == "nt"
HOST = "windows" if WINDOWS else "linux"


def download(url: str, target: Path, checksum: str = "", algorithm: str = "sha256") -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not checksum or hashlib.new(algorithm, target.read_bytes()).hexdigest() == checksum):
        return target
    print(f"Downloading {target.name}", flush=True)
    temp = target.with_suffix(target.suffix + ".part")
    with urlopen(Request(url, headers={"User-Agent": "Morphism-Portable-Builder"}), timeout=120) as response, temp.open("wb") as out:
        shutil.copyfileobj(response, out)
    if checksum and hashlib.new(algorithm, temp.read_bytes()).hexdigest() != checksum:
        raise RuntimeError(f"Checksum mismatch: {target.name}")
    temp.replace(target)
    return target


def extract(archive: Path, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                dest = (directory / item.filename).resolve()
                if not dest.is_relative_to(directory.resolve()):
                    raise ValueError("Unsafe archive path")
            z.extractall(directory)
            if not WINDOWS:
                for item in z.infolist():
                    mode = item.external_attr >> 16
                    if mode & stat.S_IXUSR:
                        (directory / item.filename).chmod(mode)
    else:
        with tarfile.open(archive) as tar:
            tar.extractall(directory, filter="data")


def find(directory: Path, name: str) -> Path:
    paths = list(directory.rglob(name))
    if not paths:
        raise RuntimeError(f"Missing {name} in {directory}")
    return paths[0]


def tools():
    if platform.machine().lower() not in ("amd64", "x86_64") or platform.system() not in ("Windows", "Linux"):
        raise RuntimeError("The portable toolchain currently supports Windows/Linux x64")
    java = shutil.which("java")
    java_home = Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else Path(java).resolve().parent.parent if java else None
    if java_home:
        probe = subprocess.run([str(java_home / "bin" / ("java.exe" if WINDOWS else "java")), "-version"], capture_output=True, text=True)
        import re
        match = re.search(r'version "(\d+)', probe.stderr)
        if not match or int(match[1]) < 17:
            java_home = None
    if not java_home:
        jdk = CACHE / "jdk"
        if not list(jdk.rglob("java.exe" if WINDOWS else "java")):
            # Adoptium publishes a SHA-256 checksum alongside each official JDK.
            url = f"https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os={HOST}"
            with urlopen(Request(url, headers={"User-Agent": "Morphism-Portable-Builder"}), timeout=60) as response:
                package = json.load(response)[0]["binary"]["package"]
            archive = download(package["link"], CACHE / package["name"], package["checksum"])
            extract(archive, jdk)
        java_home = find(jdk, "java.exe" if WINDOWS else "java").parent.parent
    os.environ["JAVA_HOME"] = str(java_home)
    os.environ["PATH"] = str(java_home / "bin") + os.pathsep + os.environ["PATH"]
    kotlin = CACHE / "kotlin"
    if not (kotlin / "kotlinc/lib/kotlin-compiler.jar").exists():
        extract(download("https://github.com/JetBrains/kotlin/releases/download/v2.0.21/kotlin-compiler-2.0.21.zip", CACHE / "kotlin-compiler-2.0.21.zip"), kotlin)
    sdk = Path(os.environ.get("ANDROID_HOME", str(CACHE / "sdk")))
    targets = [("build-tools;35.0.0", sdk / "build-tools/35.0.0"), ("platforms;android-34", sdk / "platforms/android-34")]
    missing = [(package, dest) for package, dest in targets if not dest.exists()]
    if missing:
        metadata = download("https://dl.google.com/android/repository/repository2-1.xml", CACHE / "repository.xml")
        tree = ET.parse(metadata)
        for package, dest in missing:
            remote = next(p for p in tree.iter() if p.tag.endswith("remotePackage") and p.get("path") == package)
            archives = remote.find("archives")
            archive = next(a for a in archives if a.findtext("host-os") in (None, HOST))
            complete = archive.find("complete")
            url = complete.findtext("url")
            checksum = complete.find("checksum")
            path = download("https://dl.google.com/android/repository/" + url, CACHE / Path(url).name,
                            checksum.text, checksum.get("type", "sha1"))
            staging = CACHE / ("extract-" + package.replace(";", "-"))
            extract(path, staging)
            children = list(staging.iterdir())
            source = children[0] if len(children) == 1 and children[0].is_dir() else staging
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, dest, dirs_exist_ok=True)
    return java_home, kotlin / "kotlinc", sdk / "build-tools/35.0.0", sdk / "platforms/android-34/android.jar"


def prepare_assets():
    assets = CACHE / "assets"
    shutil.copytree(HERE / "assets", assets, dirs_exist_ok=True)
    resources = ROOT / "src/morphism_srs/resources"
    shutil.copy2(ROOT / "src/morphism_srs/storage/schema_v2.sql", assets / "schema_v2.sql")
    for source, destination in [
        (resources / "web/vendor/mathjax", assets / "web/vendor/mathjax"),
        (resources / "web/css", assets / "web/css"),
        (resources / "themes", assets / "web/themes"),
    ]:
        shutil.copytree(source, destination, dirs_exist_ok=True)
    tex = json.loads((resources / "defaults/mathjax_macros.json").read_text(encoding="utf-8"))
    (assets / "web/mathjax_macros.json").write_text(json.dumps(tex, ensure_ascii=False), encoding="utf-8")
    init = "window.MathJax=" + json.dumps({"tex": tex, "svg": {"fontCache": "local"}, "startup": {"typeset": False}}) + ";\n"
    init += """MathJax.startup.ready=function(){MathJax.startup.defaultReady();
        MathJax.startup.promise.then(function(){window.dispatchEvent(new Event('morphism-mathjax-ready'));});};
    """
    (assets / "web/mathjax_init.js").write_text(init, encoding="utf-8")
    res = CACHE / "res"
    shutil.copytree(HERE / "res", res, dirs_exist_ok=True)
    # Qt is already a desktop dependency; use the same canonical app icon.
    from PySide6.QtGui import QImage
    from PySide6.QtCore import Qt
    icon = QImage(str(resources / "icons/icon.png"))
    if icon.isNull():
        raise RuntimeError("Canonical icon missing")
    for density, size in [("mdpi",48),("hdpi",72),("xhdpi",96),("xxhdpi",144),("xxxhdpi",192)]:
        folder = res / ("mipmap-"+density)
        folder.mkdir(exist_ok=True)
        icon.scaled(size,size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation).save(str(folder / "ic_launcher.png"))
    return assets, res


def run(*args):
    args = [str(a) for a in args]
    if WINDOWS and args[0].endswith((".bat", ".cmd")):
        args = ["cmd", "/d", "/c", *args]
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    assets, res = prepare_assets()
    if args.prepare_only:
        print("Canonical assets prepared:", assets)
        return
    jdk, kotlin, build, android = tools()
    java = jdk / "bin" / ("java.exe" if WINDOWS else "java")
    jar = CACHE / "portable.jar"
    sources = sorted((HERE / "kotlin").rglob("*.kt"))
    run(java, "-cp", kotlin / "lib/kotlin-compiler.jar", "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-kotlin-home", kotlin, "-no-reflect", "-classpath", android, "-jvm-target", "1.8", "-include-runtime", "-d", jar, *sources)
    dex = CACHE / "dex"
    dex.mkdir(exist_ok=True)
    run(java, "-cp", build / "lib/d8.jar", "com.android.tools.r8.D8", "--min-api", "26", "--lib", android, "--output", dex, jar)
    exe = ".exe" if WINDOWS else ""
    compiled = CACHE / "resources.zip"
    if compiled.exists():
        compiled.unlink()
    run(build / ("aapt2"+exe), "compile", "--dir", res, "-o", compiled)
    unsigned = CACHE / "unsigned.apk"
    run(build / ("aapt2"+exe), "link", "-I", android, "--manifest", HERE / "AndroidManifest.xml", "-A", assets,
        "-o", unsigned, compiled)
    with zipfile.ZipFile(unsigned, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in dex.glob("classes*.dex"):
            archive.write(path, path.name)
    aligned = CACHE / "aligned.apk"
    run(build / ("zipalign"+exe), "-f", "4", unsigned, aligned)
    key = CACHE / "portable-debug.keystore"
    if not key.exists():
        run(jdk / "bin" / ("keytool"+exe), "-genkeypair", "-keystore", key, "-storepass", "android", "-keypass", "android",
            "-alias", "morphism", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000", "-dname", "CN=Morphism SRS")
    out = ROOT / "morphism-srs.apk"
    signer = build / "lib/apksigner.jar"
    run(java, "-jar", signer, "sign", "--ks", key, "--ks-key-alias", "morphism", "--ks-pass", "pass:android",
        "--key-pass", "pass:android", "--min-sdk-version", "21", "--v1-signing-enabled", "true", "--v2-signing-enabled", "true", "--out", out, aligned)
    run(java, "-jar", signer, "verify", "--verbose", "--min-sdk-version", "21", out)
    run(build / ("zipalign"+exe), "-c", "4", out)
    print("Built and verified:", out)


if __name__ == "__main__":
    main()
