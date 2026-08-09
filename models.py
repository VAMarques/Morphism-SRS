import time
import random
import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fsrs import Card as FSRSCard, Scheduler, Rating, State

def generate_id64() -> int:
    """Generate a unique 64-bit integer ID."""
    return (int(time.time() * 1000) << 20) | random.randint(0, (1 << 20) - 1)

def to_hex_id(val: Any) -> str:
    """Format any ID as 0x Hex representation (e.g. 0x19FA38B20D7)."""
    try:
        return f"0x{int(val):X}"
    except Exception:
        return f"0x{val}"

class ReviewLogRecord:

    """Record of a single card review event for FSRS optimization."""
    def __init__(self, card_id: int, rating: int, review_time: str, 
                 elapsed_days: int = 0, scheduled_days: int = 0, 
                 state: int = 0, stability: Optional[float] = None, 
                 difficulty: Optional[float] = None):
        self.card_id = card_id
        self.rating = rating
        self.review_time = review_time
        self.elapsed_days = elapsed_days
        self.scheduled_days = scheduled_days
        self.state = state
        self.stability = stability
        self.difficulty = difficulty

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id,
            "rating": self.rating,
            "review_time": self.review_time,
            "elapsed_days": self.elapsed_days,
            "scheduled_days": self.scheduled_days,
            "state": self.state,
            "stability": self.stability,
            "difficulty": self.difficulty
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ReviewLogRecord':
        return cls(
            card_id=d["card_id"],
            rating=d["rating"],
            review_time=d["review_time"],
            elapsed_days=d.get("elapsed_days", 0),
            scheduled_days=d.get("scheduled_days", 0),
            state=d.get("state", 0),
            stability=d.get("stability"),
            difficulty=d.get("difficulty")
        )

class ReviewObject(ABC):
    """Base class for anything that can be scheduled and reviewed."""
    
    def __init__(self, item_id: Optional[Any] = None):
        if item_id is not None:
            try:
                self.item_id = int(item_id)
            except ValueError:
                self.item_id = generate_id64()
        else:
            self.item_id = generate_id64()
            
        self.fsrs_card = FSRSCard()
        
    def get_hex_id(self) -> str:
        """Return 64-bit ID formatted as uppercase Hex representation (e.g. 0x19FA38B20D7)."""
        try:
            return f"0x{int(self.item_id):X}"
        except Exception:
            return f"0x{self.item_id}"

    @abstractmethod

    def get_title(self) -> str:
        """Short title or question header."""
        pass

    @abstractmethod
    def get_html_front(self) -> str:
        """HTML content for the front of the card."""
        pass

    @abstractmethod
    def get_html_back(self) -> str:
        """HTML content for the back / solution of the card."""
        pass

    def is_due(self) -> bool:
        """Check if the card is due for review."""
        now = datetime.now(timezone.utc)
        return self.fsrs_card.due <= now

    def get_state_name(self) -> str:
        """Human-readable FSRS state name."""
        if self.fsrs_card.last_review is None:
            return "New"
        if self.is_due():
            return "Due"
        state = self.fsrs_card.state
        if state == State.Learning:
            return "Learning"
        elif state == State.Review:
            return "Review"
        elif state == State.Relearning:
            return "Relearning"
        return "Review"

    def to_dict(self, include_scheduling: bool = True) -> Dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        d = {
            "item_id": self.item_id,
            "type": self.__class__.__name__
        }
        if include_scheduling:
            d["fsrs_card"] = self.fsrs_card.to_dict() if hasattr(self.fsrs_card, 'to_dict') else None
        return d



class Flashcard(ReviewObject):
    """Standard Flashcard with LaTeX MathJax support."""
    def __init__(self, title: str, front: str, back: str, item_id: Optional[Any] = None):
        super().__init__(item_id)
        self.title = title
        self.front = front
        self.back = back

    def get_title(self) -> str:
        return self.title

    def get_html_front(self) -> str:
        return f"<div class='card-title'>{self.title}</div><div class='card-body'>{self.front}</div>"

    def get_html_back(self) -> str:
        return f"<div class='card-body'>{self.back}</div>"

    def to_dict(self, include_scheduling: bool = True) -> Dict[str, Any]:
        d = super().to_dict(include_scheduling=include_scheduling)
        d.update({
            "title": self.title,
            "front": self.front,
            "back": self.back
        })
        return d


class ProofSequenceCard(ReviewObject):
    """Multi-step proof card where steps can be revealed incrementally."""
    def __init__(self, title: str, premise: str, steps: List[str], item_id: Optional[Any] = None):
        super().__init__(item_id)
        self.title = title
        self.premise = premise
        self.steps = steps  # List of step strings (LaTeX/HTML)
        self.current_revealed = 0

    def get_title(self) -> str:
        return self.title

    def get_html_front(self) -> str:
        return f"<div class='card-title'>{self.title}</div><div class='card-body'><strong>Premise / Goal:</strong><br>{self.premise}</div>"

    def get_html_back(self) -> str:
        steps_html = "".join([f"<li class='proof-step'>Step {i+1}: {step}</li>" for i, step in enumerate(self.steps)])
        return f"<div class='card-body'><strong>Complete Proof:</strong><ol class='proof-list'>{steps_html}</ol></div>"

    def to_dict(self, include_scheduling: bool = True) -> Dict[str, Any]:
        d = super().to_dict(include_scheduling=include_scheduling)
        d.update({
            "title": self.title,
            "premise": self.premise,
            "steps": self.steps
        })
        return d


class NoteNode:
    """A Node in the knowledge graph representing a 'Note' containing multiple cards/review objects."""
    def __init__(self, note_id: Optional[Any] = None, title: str = "New Note", x: float = 0.0, y: float = 0.0, 
                 tags: Optional[List[str]] = None, note_type: str = "standard", 
                 desired_retention: float = 0.85):
        if note_id is not None:
            try:
                self.note_id = str(int(note_id))
            except ValueError:
                self.note_id = str(note_id)
        else:
            self.note_id = str(generate_id64())

        self.title = title
        self.x = x
        self.y = y
        self.tags = tags or []
        self.cards: List[ReviewObject] = []
        self.note_type = note_type  # "standard", "serial_sequence", or "serial_sequence_single"
        self.desired_retention = desired_retention  # Target retention R for the note (e.g. 0.85)

    def is_serial_sequence(self) -> bool:
        return self.note_type in ("serial_sequence", "serial_sequence_single")

    def is_serial_sequence_single(self) -> bool:
        return self.note_type == "serial_sequence_single"

    def is_serial_sequence_full(self) -> bool:
        return self.note_type == "serial_sequence"


    def add_card(self, card: ReviewObject):
        self.cards.append(card)

    def get_joint_retention(self, scheduler_manager=None) -> float:
        """
        Calculate joint retention P(∩ A_i) = ∏ R_i(t) for all cards in this note.
        """
        if not self.cards:
            return 1.0
        if scheduler_manager is not None:
            return scheduler_manager.get_note_retention(self.cards)
        if any(c.is_due() for c in self.cards):
            return 0.0
        return 1.0

    def is_due(self, scheduler_manager=None) -> bool:
        """
        Due if any card is New, any card's scheduled due timestamp has expired (intraday reviews),
        or joint retention P(∩ A_i) <= desired_retention.
        """
        if not self.cards:
            return False

        if any(c.fsrs_card.last_review is None for c in self.cards):
            return True

        if any(c.is_due() for c in self.cards):
            return True

        if scheduler_manager is not None:
            joint_r = self.get_joint_retention(scheduler_manager)
            return joint_r <= self.desired_retention

        return False


    def due_count(self, scheduler_manager=None) -> int:
        if self.is_due(scheduler_manager):
            return len(self.cards)
        return sum(1 for c in self.cards if c.is_due())

    def total_count(self) -> int:
        return len(self.cards)

    def to_dict(self, include_scheduling: bool = True) -> Dict[str, Any]:
        return {
            "note_id": self.note_id,
            "title": self.title,
            "x": self.x,
            "y": self.y,
            "tags": self.tags,
            "note_type": self.note_type,
            "desired_retention": self.desired_retention,
            "cards": [c.to_dict(include_scheduling=include_scheduling) for c in self.cards]
        }


class NoteEdge:
    """A directed edge in the graph indicating prerequisite or concept dependency."""
    def __init__(self, source_id: str, target_id: str, label: str = ""):
        self.source_id = str(source_id)
        self.target_id = str(target_id)
        self.label = label

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "label": self.label
        }


class Course:
    """A Course representing a full knowledge graph of notes and directed edges."""

    def __init__(self, name: str, notes: Optional[List[NoteNode]] = None, 
                 edges: Optional[List[NoteEdge]] = None, folder_path: str = ""):
        self.name = name
        self.notes: List[NoteNode] = notes or []
        self.edges: List[NoteEdge] = edges or []
        self.folder_path: str = folder_path  # Relative folder path e.g. "Math/Analysis"

    def to_dict(self, include_scheduling: bool = True) -> Dict[str, Any]:
        return {
            "name": self.name,
            "folder_path": self.folder_path,
            "notes": [n.to_dict(include_scheduling=include_scheduling) for n in self.notes],
            "edges": [e.to_dict() for e in self.edges]
        }

