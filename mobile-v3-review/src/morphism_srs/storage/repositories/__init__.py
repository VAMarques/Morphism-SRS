from __future__ import annotations

from morphism_srs.storage.repositories.browser_repo import BrowserRepository
from morphism_srs.storage.repositories.card_repo import CardRepository
from morphism_srs.storage.repositories.course_repo import CourseRepository
from morphism_srs.storage.repositories.folder_repo import FolderRepository
from morphism_srs.storage.repositories.note_repo import NoteRepository
from morphism_srs.storage.repositories.review_repo import ReviewRepository
from morphism_srs.storage.repositories.scratch_repo import ScratchRepository

__all__ = [
    "BrowserRepository",
    "CardRepository",
    "CourseRepository",
    "FolderRepository",
    "NoteRepository",
    "ReviewRepository",
    "ScratchRepository",
]
