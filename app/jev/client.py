"""Thin adapter over the official typesafe-sdk. Maps answers to typed decisions and errors to safe codes."""
from __future__ import annotations

import time
from typing import Any

import typesafe_sdk as ts

from app.config import DEFAULT_SETTINGS, Settings
from app.jev.questions import INTENT_IDS, PRIORITY_LEVELS, QUESTIONS, build_state
from app.models import ChoiceDecision, JevDecisions, NoulDecision, ScoreDecision

ERROR_MESSAGES_JA: dict[str, str] = {
    "api_key_missing": "TypeSafe の API キーが設定されていません（環境変数 TYPESAFE_API_KEY）",
    "authentication": "Jevから判断を取得できませんでした（認証エラー）",
    "permission": "Jevから判断を取得できませんでした（権限エラー）",
    "rate_limit": "Jevから判断を取得できませんでした（レート制限）",
    "timeout": "Jevから判断を取得できませんでした（タイムアウト）",
    "connection": "Jevから判断を取得できませんでした（接続エラー）",
    "bad_request": "Jevから判断を取得できませんでした（リクエスト不正）",
    "server": "Jevから判断を取得できませんでした（サーバーエラー）",
    "validation": "Jevから判断を取得できませんでした（応答の検証に失敗）",
    "unexpected_answer": "Jevから判断を取得できませんでした（想定外の応答）",
    "unknown": "Jevから判断を取得できませんでした",
}


class JevError(RuntimeError):
    """Carries only a short code (and optional status / request id). Never the provider body."""

    def __init__(self, code: str, *, status: int | None = None, request_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.request_id = request_id

    @property
    def message_ja(self) -> str:
        return ERROR_MESSAGES_JA.get(self.code, ERROR_MESSAGES_JA["unknown"])


def classify_error(error: BaseException) -> JevError:
    if isinstance(error, JevError):
        return error
    if isinstance(error, ts.TypeSafeAPITimeoutError):
        return JevError("timeout")
    if isinstance(error, ts.TypeSafeAPIConnectionError):
        return JevError("connection")
    if isinstance(error, ts.TypeSafeAPIResponseValidationError):
        return JevError("validation", status=getattr(error, "status", None),
                        request_id=getattr(error, "request_id", None))
    if isinstance(error, ts.TypeSafeAPIError):
        status = getattr(error, "status", None)
        request_id = getattr(error, "request_id", None)
        if isinstance(error, ts.TypeSafeAuthenticationError):
            return JevError("authentication", status=status, request_id=request_id)
        if isinstance(error, ts.TypeSafePermissionDeniedError):
            return JevError("permission", status=status, request_id=request_id)
        if isinstance(error, ts.TypeSafeRateLimitError):
            return JevError("rate_limit", status=status, request_id=request_id)
        if isinstance(error, (ts.TypeSafeBadRequestError, ts.TypeSafeUnprocessableEntityError,
                              ts.TypeSafeNotFoundError)):
            return JevError("bad_request", status=status, request_id=request_id)
        if isinstance(error, ts.TypeSafeInternalServerError):
            return JevError("server", status=status, request_id=request_id)
        return JevError("unknown", status=status, request_id=request_id)
    if isinstance(error, ts.TypeSafeError):
        if "api key" in str(error).lower():
            return JevError("api_key_missing")
        return JevError("unknown")
    return JevError("unknown")


class JevClient:
    """One call per final transcript. Retries: at most `settings.max_auto_retries` (SDK default would be 2)."""

    def __init__(self, settings: Settings = DEFAULT_SETTINGS, *, api_key: str | None = None,
                 transport: Any | None = None, base_url: str | None = None):
        self.settings = settings
        retry = ts.RetryPolicy(max_retries=settings.max_auto_retries)
        try:
            self._client = ts.TypeSafeClient(api_key=api_key, model=settings.model, retry=retry,
                                             timeout=settings.request_timeout_s, transport=transport,
                                             base_url=base_url)
        except ts.TypeSafeError as error:
            raise classify_error(error) from None

    def close(self) -> None:
        self._client.close()

    def decide(self, transcript: str) -> JevDecisions:
        started = time.perf_counter()
        try:
            response = self._client.system_one(state=build_state(transcript), questions=QUESTIONS)
        except (ts.TypeSafeError, ConnectionError, TimeoutError) as error:
            raise classify_error(error) from None
        latency_ms = (time.perf_counter() - started) * 1000
        return map_response(response, latency_ms)


def map_response(response: ts.SystemOneResponse, latency_ms: float) -> JevDecisions:
    answers = response.answers
    intent = answers.get("intent")
    needs = answers.get("needs_response")
    priority = answers.get("priority")
    if (not isinstance(intent, ts.ChoiceAnswer) or not isinstance(needs, ts.NoulAnswer)
            or not isinstance(priority, ts.ScoreAnswer)):
        raise JevError("unexpected_answer", request_id=response.request_id)
    if intent.choice not in INTENT_IDS:
        raise JevError("unexpected_answer", request_id=response.request_id)
    probabilities = {option: float(intent.probabilities.get(option, 0.0)) for option in INTENT_IDS}
    max_level = len(PRIORITY_LEVELS) - 1
    return JevDecisions(
        intent=ChoiceDecision(selected=intent.choice, confidence=float(intent.confidence),
                              probabilities=probabilities),
        needs_response=NoulDecision(probability_yes=float(needs.noul)),
        priority=ScoreDecision(
            score=float(priority.score),
            confidence=float(priority.confidence),
            probabilities={int(level): float(p) for level, p in priority.probabilities.items()},
            legend={int(level): (text if isinstance(text, str) else str(text))
                    for level, text in priority.legend.items()},
            max_level=max_level,
        ),
        model=response.model,
        request_id=response.request_id,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        latency_ms=latency_ms,
    )
