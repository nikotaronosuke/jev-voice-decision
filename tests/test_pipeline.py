from __future__ import annotations

from app.config import Settings
from app.jev.client import JevClient
from app.main import Api
from app.pipeline import Pipeline
from app.stt.parakeet import SttError
from tests.fakes import DUMMY_KEY, FakeTransport, answer_body


class FakeTranscriber:
    name = "fake"
    state = "ready"

    def __init__(self, text: str = "料金について詳しく知りたいです", error: str | None = None):
        self.text, self.error, self.calls = text, error, 0

    def transcribe(self, pcm16: bytes) -> str:
        self.calls += 1
        if self.error:
            raise SttError(self.error)
        return self.text


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


def test_audio_runs_through_stt_then_exactly_one_jev_call():
    stages: list[str] = []
    fake = FakeTransport()
    transcriber = FakeTranscriber()
    pipeline = make_pipeline(fake, transcriber=transcriber, on_stage=stages.append)
    result = pipeline.run_audio(b"\x00\x10" * 16000)
    assert result.ok and result.transcript == "料金について詳しく知りたいです"
    assert transcriber.calls == 1 and len(fake.requests) == 1
    assert fake.requests[0]["json"]["state"]["utterance"] == "料金について詳しく知りたいです"
    assert stages == ["transcribing", "deciding", "complete"]


def test_audio_stt_failure_never_reaches_jev():
    stages: list[str] = []
    fake = FakeTransport()
    pipeline = make_pipeline(fake, transcriber=FakeTranscriber(error="stt_timeout"), on_stage=stages.append)
    result = pipeline.run_audio(b"\x00\x10" * 16000)
    assert result.ok is False and result.error_code == "stt_timeout"
    assert result.error_message == "端末内 STT が時間内に応答しませんでした"
    assert fake.requests == [] and stages == ["transcribing", "error"]


def test_silent_audio_is_reported_without_calling_stt_or_jev():
    fake = FakeTransport()
    transcriber = FakeTranscriber()
    result = make_pipeline(fake, transcriber=transcriber).run_audio(bytes(32000))
    assert result.ok is False and result.error_code == "no_speech"
    assert result.error_message == "音声が検出されませんでした。もう一度話してください"
    assert transcriber.calls == 0 and fake.requests == []


def test_audio_without_transcriber_is_refused():
    fake = FakeTransport()
    result = make_pipeline(fake).run_audio(b"\x00\x10" * 16000)
    assert result.error_code == "stt_unconfigured" and fake.requests == []


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
    assert empty.status()["voice_available"] is False and empty.status()["voice_state"] == "unconfigured"
    assert empty.history() == []
    assert len(Api(None, Settings()).examples()) >= 4
    assert api.start_listening()["ok"] is False  # no transcriber configured
    assert api.stop_listening()["error_code"] == "audio_too_short"  # nothing was recording
    assert api.cancel_listening()["ok"] is True
