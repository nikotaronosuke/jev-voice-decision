from __future__ import annotations

import httpx2
import pytest

from app.config import Settings
from app.jev.client import JevClient, JevError
from app.jev.questions import INTENT_IDS, PRIORITY_LEVELS
from tests.fakes import DUMMY_KEY, FakeTransport, answer_body


def make_client(fake: FakeTransport, **settings) -> JevClient:
    return JevClient(Settings(**settings), api_key=DUMMY_KEY, transport=fake.transport())


def test_maps_choice_noul_score():
    fake = FakeTransport(answer_body(intent="request", intent_confidence=0.81, noul=0.2, score=1.4))
    decisions = make_client(fake).decide("ダークモードも追加してほしいです")
    assert decisions.intent.selected == "request"
    assert decisions.intent.confidence == pytest.approx(0.81)
    assert set(decisions.intent.probabilities) == set(INTENT_IDS)
    assert decisions.needs_response.probability_yes == pytest.approx(0.2)
    assert decisions.priority.score == pytest.approx(1.4)
    assert decisions.priority.max_level == len(PRIORITY_LEVELS) - 1
    assert decisions.priority.probabilities == {0: 0.05, 1: 0.1, 2: 0.55, 3: 0.3}
    assert decisions.priority.legend[3] == "blocked"
    assert decisions.model == "jev-1.13.0"
    assert decisions.request_id == "req_fake_1"
    assert decisions.input_tokens == 321 and decisions.output_tokens == 40
    assert decisions.latency_ms >= 0


def test_request_carries_only_state_model_and_questions():
    fake = FakeTransport()
    make_client(fake).decide("これって無料で使えますか？")
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request["method"] == "POST" and request["url"].endswith("/v1/systemone")
    assert set(request["json"]) == {"state", "model", "questions"}
    assert request["json"]["state"] == {"channel": "live_stream_comment", "language": "ja",
                                        "utterance": "これって無料で使えますか？"}
    assert request["json"]["model"] == "jev-latest"
    assert set(request["json"]["questions"]) == {"intent", "needs_response", "priority"}
    assert request["json"]["questions"]["intent"]["type"] == "choice"
    assert request["json"]["questions"]["needs_response"]["type"] == "noul"
    assert request["json"]["questions"]["priority"]["type"] == "score"
    assert len(request["json"]["questions"]["priority"]["criteria"]) == len(PRIORITY_LEVELS)


def test_api_error_is_reduced_to_a_safe_code():
    fake = FakeTransport(status=401, text_body='{"error": "SECRET-BODY-MARKER"}')
    with pytest.raises(JevError) as info:
        make_client(fake).decide("料金を教えてください")
    error = info.value
    assert error.code == "authentication"
    assert error.status == 401
    assert "SECRET-BODY-MARKER" not in str(error)
    assert "SECRET-BODY-MARKER" not in error.message_ja
    assert error.message_ja.startswith("Jevから判断を取得できませんでした")
    assert len(fake.requests) == 1  # 401 is not retried


def test_server_error_is_retried_at_most_once():
    fake = FakeTransport(status=500, text_body="boom")
    with pytest.raises(JevError) as info:
        make_client(fake).decide("こんばんは！")
    assert info.value.code == "server"
    assert len(fake.requests) == 2  # initial attempt + one automatic retry


def test_rate_limit_maps_to_rate_limit():
    fake = FakeTransport(status=429, text_body="slow down")
    with pytest.raises(JevError) as info:
        make_client(fake, max_auto_retries=0).decide("こんばんは！")
    assert info.value.code == "rate_limit"
    assert len(fake.requests) == 1


def test_timeout_maps_to_timeout():
    fake = FakeTransport(raise_exc=lambda request: httpx2.ReadTimeout("slow", request=request))
    with pytest.raises(JevError) as info:
        make_client(fake).decide("エラーで何も操作できません")
    assert info.value.code == "timeout"
    assert len(fake.requests) == 2


def test_connection_error_maps_to_connection():
    fake = FakeTransport(raise_exc=lambda request: httpx2.ConnectError("down", request=request))
    with pytest.raises(JevError) as info:
        make_client(fake, max_auto_retries=0).decide("こんばんは")
    assert info.value.code == "connection"


def test_missing_api_key_is_reported_before_any_request(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    fake = FakeTransport()
    with pytest.raises(JevError) as info:
        JevClient(Settings(), transport=fake.transport())
    assert info.value.code == "api_key_missing"
    assert fake.requests == []


def test_unexpected_answer_shape_is_rejected():
    body = answer_body()
    del body["answers"]["priority"]
    fake = FakeTransport(body)
    with pytest.raises(JevError) as info:
        make_client(fake).decide("テスト")
    assert info.value.code == "unexpected_answer"


def test_unknown_choice_is_rejected():
    fake = FakeTransport(answer_body(intent="spam", intent_probabilities={"spam": 1.0}))
    with pytest.raises(JevError) as info:
        make_client(fake).decide("テスト")
    assert info.value.code == "unexpected_answer"
