"""Compatibility entry point for the Kotlin/SQLite Android source builder."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "src/morphism-portable/build_portable.py"), run_name="__main__")
