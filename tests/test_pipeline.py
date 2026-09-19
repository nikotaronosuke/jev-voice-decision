from __future__ import annotations

from app.config import Settings
from app.jev.client import JevClient
from app.main import Api
from app.pipeline import Pipeline
from tests.fakes import DUMMY_KEY, FakeTransport, answer_body


def make_pipeline(fake: FakeTransport | None = None, **kwargs) -> Pipeline:
    fake = fake or FakeTransport()
    settings = Settings()
    return Pipeline(JevClient(settings, api_key=DUMMY_KEY, transport=fake.transport()), settings, **kwargs)


def test_text_runs_end_to_end():
    stages: list[str] = []
    pipeline = make_pipeline(on_stage=stages.append)
    result = pipeline.run_text("  これって無料で使えますか？ ")
    assert result.ok is True
    assert result.transcript == "これって無料で使えますか？"
    assert result.decisions.intent.selected == "question"
    assert result.action.action == "question_queue"
    assert stages == ["deciding", "complete"]
    payload = result.to_dict()
    assert payload["ok"] and payload["decisions"]["intent"]["selected"] == "question"


def test_empty_and_too_long_inputs_never_reach_jev():
    fake = FakeTransport()
    pipeline = make_pipeline(fake)
    assert pipeline.run_text("   ").error_code == "empty_input"
    assert pipeline.run_text("あ" * 501).error_code == "too_long"
    assert fake.requests == []


def test_api_failure_becomes_a_japanese_message():
    stages: list[str] = []
    pipeline = make_pipeline(FakeTransport(status=500, text_body="PROVIDER-BODY"), on_stage=stages.append)
    result = pipeline.run_text("こんばんは")
    assert result.ok is False
    assert result.error_code == "server"
    assert result.error_message == "Jevから判断を取得できませんでした（サーバーエラー）"
    assert "PROVIDER-BODY" not in result.error_message
    assert stages == ["deciding", "error"]
    assert pipeline.history() == []


def test_history_is_in_memory_and_capped():
    pipeline = make_pipeline(clock=lambda: 0.0)
    for index in range(7):
        pipeline.run_text(f"発話 {index}")
    history = pipeline.history()
    assert len(history) == 5
    assert history[0]["transcript"] == "発話 6"
    assert history[0]["intent"] == "質問" and history[0]["action"] == "質問キューへ"
    pipeline.clear_history()
    assert pipeline.history() == []
    assert make_pipeline().history() == []  # a new pipeline starts empty: nothing persisted


def test_held_decisions_are_recorded_as_hold():
    pipeline = make_pipeline(FakeTransport(answer_body(intent_confidence=0.3)))
    result = pipeline.run_text("うーん")
    assert result.action.action == "manual_review"
    assert pipeline.history()[0]["intent"] == "保留"


def test_page_api_never_raises():
    api = Api(make_pipeline(FakeTransport(status=500, text_body="x")), Settings())
    payload = api.decide("こんばんは")
    assert payload["ok"] is False and payload["error_message"]
    empty = Api(None, Settings(), startup_error="api_key_missing")
    payload = empty.decide("こんばんは")
    assert payload["error_code"] == "api_key_missing"
    assert empty.status()["startup_error"] == "api_key_missing"
    assert empty.history() == []
    assert len(Api(None, Settings()).examples()) >= 4
