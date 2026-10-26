from __future__ import annotations

from enum import Enum, IntEnum


class NoteReviewMode(str, Enum):
    STANDARD = "standard"
    SERIAL = "serial"
    CLOZE = "cloze"


class CardState(IntEnum):
    NEW = 0
    LEARNING = 1
    REVIEW = 2
    RELEARNING = 3


class RatingEnum(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4
