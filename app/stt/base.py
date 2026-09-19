"""Transcriber interface. Phase 1 uses TextInput; Phase 2 adds a local speech engine."""
from __future__ import annotations

from typing import Protocol


class Transcriber(Protocol):
    name: str

    def transcribe_text(self, text: str) -> str:
        """Return the final transcript for already-typed text."""
        ...
