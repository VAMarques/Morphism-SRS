from __future__ import annotations

import uuid


def generate_uuid() -> str:
    """Generates a standard lowercase UUID4 string."""
    return str(uuid.uuid4())
