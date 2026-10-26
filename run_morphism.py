#!/usr/bin/env python3
"""Convenience launcher for Morphism SRS v2 from the repository root."""

from __future__ import annotations

from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from morphism_srs.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
