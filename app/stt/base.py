"""Transcriber interface. Text Mode uses TextInput; Voice Mode uses the local Parakeet JA worker."""
from __future__ import annotations

from typing import Protocol


class Transcriber(Protocol):
    name: str
    state: str  # stopped | starting | ready | error

    def transcribe(self, pcm16: bytes) -> str:
        """Return the final transcript for one utterance (PCM16 mono 16 kHz). Raises SttError."""
        ...
