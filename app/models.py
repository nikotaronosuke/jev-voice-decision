"""Typed results. Everything here lives in process memory only."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChoiceDecision:
    """Jev Choice: one option out of a closed set, with the full output distribution."""

    selected: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class NoulDecision:
    """Jev Noul: probability that the statement is true (0..1). Carries no separate confidence."""

    probability_yes: float


@dataclass(frozen=True)
class ScoreDecision:
    """Jev Score: probability-weighted position on an ordered rubric, 0 .. max_level, as returned."""

    score: float
    confidence: float
    probabilities: dict[int, float]
    legend: dict[int, str]
    max_level: int


@dataclass(frozen=True)
class JevDecisions:
    intent: ChoiceDecision
    needs_response: NoulDecision
    priority: ScoreDecision
    model: str
    request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float


@dataclass(frozen=True)
class ActionDecision:
    """Result of deterministic Python rules. `rules` is the human-readable trace shown in the UI."""

    action: str  # question_queue | request_list | feedback | record_only | manual_review
    hold: bool
    needs_response: bool
    highlight: bool
    rules: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineResult:
    ok: bool
    transcript: str
    decisions: JevDecisions | None
    action: ActionDecision | None
    error_code: str | None = None
    error_message: str | None = None  # Japanese, user-facing, never a provider body

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoryEntry:
    time_label: str
    transcript: str
    intent: str
    action: str
    highlight: bool
