"""Text Mode: the typed text is the final transcript."""
from __future__ import annotations


class TextInput:
    name = "text"

    def transcribe_text(self, text: str) -> str:
        return text
