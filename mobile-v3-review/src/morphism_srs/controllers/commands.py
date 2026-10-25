from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class UndoableCommand:
    description: str
    undo_fn: Callable[[], None]
    redo_fn: Callable[[], None] | None = None


class CommandStack:
    """Undo/Redo stack for Ctrl+Z in Review and Explorer views."""

    def __init__(self, max_depth: int = 100) -> None:
        self.max_depth = max_depth
        self._undo_stack: list[UndoableCommand] = []
        self._redo_stack: list[UndoableCommand] = []

    def push(self, cmd: UndoableCommand) -> None:
        self._undo_stack.append(cmd)
        if len(self._undo_stack) > self.max_depth:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def undo(self) -> str | None:
        if not self._undo_stack:
            return None
        cmd = self._undo_stack.pop()
        cmd.undo_fn()
        if cmd.redo_fn is not None:
            self._redo_stack.append(cmd)
        return cmd.description

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
