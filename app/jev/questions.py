"""The three Jev questions, kept in one place so a human can review them.

Instructions are written in English (Jev's primary training language); the criteria
carry Japanese examples because the state is a Japanese utterance. Everything
below is fictional live-stream / event comment material.
"""
from __future__ import annotations

from typesafe_sdk import Choice, Noul, Score

INTENT_IDS: tuple[str, ...] = ("question", "impression", "request", "other")
INTENT_LABELS_JA: dict[str, str] = {
    "question": "質問",
    "impression": "感想",
    "request": "要望",
    "other": "その他",
}

STATE_CHANNEL = "live_stream_comment"

INTENT_QUESTION = Choice(
    instructions=(
        "A viewer said this during a live stream or event. "
        "What is the main intent of the utterance? Pick exactly one."
    ),
    criteria={
        "question": {
            "what": "Asks for information, an explanation, or an answer.",
            "not_for": "Statements of opinion, or asking the host to add or change something.",
            "examples": ["これって無料で使えますか？", "料金について詳しく知りたいです"],
        },
        "impression": {
            "what": "States an opinion, evaluation, reaction, or feeling about what was shown.",
            "not_for": "Requests for information or for changes.",
            "examples": ["この機能かなり便利ですね", "すごく分かりやすかったです"],
        },
        "request": {
            "what": "Asks for something to be added, changed, fixed, or improved.",
            "not_for": "Pure questions or pure opinions.",
            "examples": ["ダークモードも追加してほしいです", "文字をもう少し大きくしてください"],
        },
        "other": {
            "what": "Greetings, small talk, or anything that fits none of the above.",
            "examples": ["こんばんは！", "初見です"],
        },
    },
)

NEEDS_RESPONSE_QUESTION = Noul(
    instructions="Does this utterance need a reply from the host or staff?",
    criteria={
        "true": "The viewer is waiting for an answer, confirmation, or help. 例: 料金を教えてください",
        "false": "No reply is expected; it can simply be read or noted. 例: すごく便利ですね",
    },
)

# Ordered rubric, low -> high. Levels describe situations, not degrees (per the Score guide).
PRIORITY_LEVELS: tuple[str, ...] = (
    "A greeting or small talk; nothing needs to be done. 例: こんばんは",
    "An opinion or feedback that can be read later without any action. 例: 便利ですね",
    "A question or request that deserves a reply during the session. 例: 料金を教えてください",
    "Something is broken or the viewer is blocked and asks for immediate help. 例: エラーで操作できません、すぐ確認してほしい",
)
PRIORITY_LABELS_JA: tuple[str, ...] = ("低", "やや低", "やや高", "高")

PRIORITY_QUESTION = Score(
    instructions="How urgently should the host or staff deal with this utterance?",
    criteria=list(PRIORITY_LEVELS),
)

QUESTIONS = {
    "intent": INTENT_QUESTION,
    "needs_response": NEEDS_RESPONSE_QUESTION,
    "priority": PRIORITY_QUESTION,
}


def build_state(transcript: str) -> dict[str, str]:
    """Exactly what leaves the machine: the final transcript plus minimal decision context."""
    return {"channel": STATE_CHANNEL, "language": "ja", "utterance": transcript}
