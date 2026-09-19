"""text -> Jev -> typed decisions -> deterministic action. State lives in memory for this process only."""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any

from app.actions import ACTION_LABELS_JA, decide_action
from app.config import Settings, DEFAULT_SETTINGS
from app.jev.client import JevClient, JevError
from app.jev.questions import INTENT_LABELS_JA
from app.models import HistoryEntry, PipelineResult

STAGES = ("idle", "listening", "transcribing", "deciding", "complete", "error")
MAX_TRANSCRIPT_CHARS = 500


class Pipeline:
    def __init__(self, jev: JevClient, settings: Settings = DEFAULT_SETTINGS,
                 on_stage: Callable[[str], None] | None = None, clock: Callable[[], float] = time.time):
        self.jev = jev
        self.settings = settings
        self.on_stage = on_stage or (lambda stage: None)
        self.clock = clock
        self._history: deque[HistoryEntry] = deque(maxlen=settings.history_limit)

    def run_text(self, text: str) -> PipelineResult:
        transcript = " ".join(text.split())
        if not transcript:
            return PipelineResult(ok=False, transcript="", decisions=None, action=None,
                                  error_code="empty_input", error_message="テキストを入力してください")
        if len(transcript) > MAX_TRANSCRIPT_CHARS:
            return PipelineResult(ok=False, transcript=transcript[:MAX_TRANSCRIPT_CHARS], decisions=None, action=None,
                                  error_code="too_long", error_message=f"{MAX_TRANSCRIPT_CHARS} 文字以内で入力してください")
        return self._decide(transcript)

    def _decide(self, transcript: str) -> PipelineResult:
        self.on_stage("deciding")
        try:
            decisions = self.jev.decide(transcript)
        except JevError as error:
            self.on_stage("error")
            return PipelineResult(ok=False, transcript=transcript, decisions=None, action=None,
                                  error_code=error.code, error_message=error.message_ja)
        action = decide_action(decisions, self.settings)
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
