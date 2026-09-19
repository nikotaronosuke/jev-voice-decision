from __future__ import annotations

from app.actions import decide_action
from app.config import Settings
from app.models import ChoiceDecision, JevDecisions, NoulDecision, ScoreDecision


def decisions(intent: str, *, confidence: float = 0.9, noul: float = 0.8, score: float = 1.0) -> JevDecisions:
    probabilities = {option: 0.0 for option in ("question", "impression", "request", "other")}
    probabilities[intent] = confidence
    return JevDecisions(
        intent=ChoiceDecision(selected=intent, confidence=confidence, probabilities=probabilities),
        needs_response=NoulDecision(probability_yes=noul),
        priority=ScoreDecision(score=score, confidence=0.7, probabilities={0: 0.1, 1: 0.3, 2: 0.4, 3: 0.2},
                               legend={0: "a", 1: "b", 2: "c", 3: "d"}, max_level=3),
        model="jev-1.13.0", request_id="req", input_tokens=1, output_tokens=1, latency_ms=1.0,
    )


def test_question_needing_reply_goes_to_question_queue():
    action = decide_action(decisions("question", noul=0.9))
    assert action.action == "question_queue"
    assert action.needs_response is True and action.hold is False


def test_question_not_needing_reply_is_only_recorded():
    action = decide_action(decisions("question", noul=0.2))
    assert action.action == "record_only"
    assert action.needs_response is False


def test_request_goes_to_request_list():
    assert decide_action(decisions("request")).action == "request_list"


def test_impression_goes_to_feedback():
    assert decide_action(decisions("impression", noul=0.1)).action == "feedback"


def test_other_is_only_recorded():
    assert decide_action(decisions("other", noul=0.1)).action == "record_only"


def test_low_confidence_is_held_for_manual_review():
    action = decide_action(decisions("request", confidence=0.4))
    assert action.action == "manual_review"
    assert action.hold is True
    assert any("判断保留" in rule for rule in action.rules)


def test_confidence_threshold_is_a_named_setting():
    strict = Settings(demo_confidence_threshold=0.95)
    assert decide_action(decisions("request", confidence=0.9), strict).hold is True
    assert decide_action(decisions("request", confidence=0.9)).hold is False


def test_high_priority_is_highlighted_and_low_is_not():
    assert decide_action(decisions("question", score=2.4)).highlight is True
    assert decide_action(decisions("question", score=2.0)).highlight is True
    assert decide_action(decisions("question", score=1.9)).highlight is False


def test_rules_are_deterministic():
    first = decide_action(decisions("request", noul=0.33, score=2.2))
    second = decide_action(decisions("request", noul=0.33, score=2.2))
    assert first == second
    assert first.rules  # the trace is never empty
