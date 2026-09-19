"""Deterministic action rules. Jev gives fuzzy, probabilistic decisions; this module is plain Python.

No model call happens here. Given the typed decisions and the demo thresholds, the
rules below always produce the same action for the same input.
"""
from __future__ import annotations

from app.config import Settings, DEFAULT_SETTINGS
from app.jev.questions import INTENT_LABELS_JA
from app.models import ActionDecision, JevDecisions

ACTION_LABELS_JA: dict[str, str] = {
    "question_queue": "質問キューへ",
    "request_list": "要望リストへ",
    "feedback": "フィードバックへ",
    "record_only": "記録のみ",
    "manual_review": "手動確認",
}


def decide_action(decisions: JevDecisions, settings: Settings = DEFAULT_SETTINGS) -> ActionDecision:
    rules: list[str] = []
    intent = decisions.intent
    needs_response = decisions.needs_response.probability_yes >= settings.demo_needs_response_threshold
    highlight = decisions.priority.score >= settings.demo_priority_highlight_score

    if intent.confidence < settings.demo_confidence_threshold:
        rules.append(f"主な意図の confidence {intent.confidence:.2f} < demo threshold {settings.demo_confidence_threshold:.2f} → 判断保留")
        rules.append("保留中の発話は自動で振り分けない → 手動確認")
        return ActionDecision(action="manual_review", hold=True, needs_response=needs_response, highlight=highlight, rules=rules)

    label = INTENT_LABELS_JA[intent.selected]
    rules.append(f"主な意図 = {label}（confidence {intent.confidence:.2f} ≥ {settings.demo_confidence_threshold:.2f}）")
    rules.append(f"返答が必要 = {'YES' if needs_response else 'NO'}（P(yes) {decisions.needs_response.probability_yes:.2f}"
                 f" {'≥' if needs_response else '<'} {settings.demo_needs_response_threshold:.2f}）")

    if intent.selected == "question":
        if needs_response:
            action = "question_queue"
            rules.append("質問 かつ 返答が必要 → 質問キューへ")
        else:
            action = "record_only"
            rules.append("質問 だが 返答は不要 → 記録のみ")
    elif intent.selected == "request":
        action = "request_list"
        rules.append("要望 → 要望リストへ")
    elif intent.selected == "impression":
        action = "feedback"
        rules.append("感想 → フィードバックへ")
    else:
        action = "record_only"
        rules.append("その他 → 記録のみ")

    if highlight:
        rules.append(f"優先度 score {decisions.priority.score:.2f} ≥ {settings.demo_priority_highlight_score:.1f} → 強調表示")
    return ActionDecision(action=action, hold=False, needs_response=needs_response, highlight=highlight, rules=rules)
