"""Fake HTTP transport for the official SDK. No test in this suite talks to TypeSafe."""
from __future__ import annotations

import json
from typing import Any, Callable

import httpx2

DUMMY_KEY = "dummy-value-not-a-real-key-000000"


def answer_body(*, intent: str = "question", intent_confidence: float = 0.92,
                intent_probabilities: dict[str, float] | None = None, noul: float = 0.85,
                score: float = 2.1, score_confidence: float = 0.7,
                score_probabilities: dict[str, float] | None = None, model: str = "jev-1.13.0") -> dict[str, Any]:
    intent_probabilities = intent_probabilities or {"question": 0.92, "impression": 0.03, "request": 0.03, "other": 0.02}
    score_probabilities = score_probabilities or {"0": 0.05, "1": 0.1, "2": 0.55, "3": 0.3}
    return {
        "model": model,
        "usage": {"input_tokens": 321, "output_tokens": 40},
        "answers": {
            "intent": {"type": "choice", "choice": intent, "confidence": intent_confidence,
                       "probabilities": intent_probabilities},
            "needs_response": {"type": "noul", "noul": noul},
            "priority": {"type": "score", "score": score, "confidence": score_confidence,
                         "probabilities": score_probabilities,
                         "legend": {"0": "greeting", "1": "opinion", "2": "question", "3": "blocked"}},
        },
    }


class FakeTransport:
    """Records every request; replies with `body` (or raises) so retries can be counted."""

    def __init__(self, body: dict[str, Any] | None = None, *, status: int = 200,
                 raise_exc: Callable[[httpx2.Request], BaseException] | None = None,
                 text_body: str | None = None):
        self.body = body if body is not None else answer_body()
        self.status = status
        self.raise_exc = raise_exc
        self.text_body = text_body
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append({
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "json": json.loads(request.content) if request.content else None,
        })
        if self.raise_exc is not None:
            raise self.raise_exc(request)
        if self.text_body is not None:
            return httpx2.Response(self.status, text=self.text_body, headers={"x-typesafe-request-id": "req_fake_1"})
        return httpx2.Response(self.status, json=self.body, headers={"x-typesafe-request-id": "req_fake_1"})

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)
