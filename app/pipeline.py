"""text or audio -> (local STT) -> Jev -> typed decisions -> deterministic action. State lives in memory only."""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any

from app.actions import ACTION_LABELS_JA, decide_action
from app.config import DEFAULT_SETTINGS, Settings
from app.jev.client import JevClient, JevError
from app.jev.questions import INTENT_LABELS_JA
from app.models import HistoryEntry, PipelineResult
from app.stt.audio import trim_silence
from app.stt.parakeet import SttError

STAGES = ("idle", "listening", "transcribing", "deciding", "complete", "error")
MAX_TRANSCRIPT_CHARS = 500


class Pipeline:
    def __init__(self, jev: JevClient, settings: Settings = DEFAULT_SETTINGS, *, transcriber: Any | None = None,
                 on_stage: Callable[[str], None] | None = None, clock: Callable[[], float] = time.time):
        self.jev = jev
        self.settings = settings
        self.transcriber = transcriber
        self.on_stage = on_stage or (lambda stage: None)
        self.clock = clock
        self._history: deque[HistoryEntry] = deque(maxlen=settings.history_limit)

    def run_text(self, text: str, *, record_history: bool = True) -> PipelineResult:
        transcript = " ".join(text.split())
        if not transcript:
            return PipelineResult(ok=False, transcript="", decisions=None, action=None,
                                  error_code="empty_input", error_message="テキストを入力してください")
        if len(transcript) > MAX_TRANSCRIPT_CHARS:
            return PipelineResult(ok=False, transcript=transcript[:MAX_TRANSCRIPT_CHARS], decisions=None, action=None,
                                  error_code="too_long", error_message=f"{MAX_TRANSCRIPT_CHARS} 文字以内で入力してください")
        return self._decide(transcript, record_history)

    def run_audio(self, pcm16: bytes) -> PipelineResult:
        """Final transcript from the local engine, then exactly one Jev call. The audio bytes are not kept."""
        if self.transcriber is None:
            return PipelineResult(ok=False, transcript="", decisions=None, action=None,
                                  error_code="stt_unconfigured", error_message=SttError("stt_unconfigured").message_ja)
        self.on_stage("transcribing")
        try:
            pcm16 = trim_silence(pcm16)  # recognizers invent words on long room-noise stretches
            if not pcm16:
                raise SttError("no_speech")
            transcript = self.transcriber.transcribe(pcm16)
        except SttError as error:
            self.on_stage("error")
            return PipelineResult(ok=False, transcript="", decisions=None, action=None,
                                  error_code=error.code, error_message=error.message_ja)
        finally:
            del pcm16
        return self.run_text(transcript)

    def _decide(self, transcript: str, record_history: bool = True) -> PipelineResult:
        self.on_stage("deciding")
        try:
            decisions = self.jev.decide(transcript)
        except JevError as error:
            self.on_stage("error")
            return PipelineResult(ok=False, transcript=transcript, decisions=None, action=None,
                                  error_code=error.code, error_message=error.message_ja)
        action = decide_action(decisions, self.settings)
        if record_history:
            self._history.appendleft(HistoryEntry(
            time_label=time.strftime("%H:%M", time.localtime(self.clock())),
            transcript=transcript,
            intent="保留" if action.hold else INTENT_LABELS_JA[decisions.intent.selected],
            action=ACTION_LABELS_JA[action.action],
            highlight=action.highlight,
        ))
        self.on_stage("complete")
        return PipelineResult(ok=True, transcript=transcript, decisions=decisions, action=action)

    def history(self) -> list[dict[str, Any]]:
        return [entry.__dict__ for entry in self._history]

    def clear_history(self) -> None:
        self._history.clear()
