"""Nothing leaves the process except the request the SDK sends; nothing is written to disk."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, Settings, VoiceSettings, api_key_present
from app.jev.client import JevClient, JevError
from app.pipeline import Pipeline
from app.stt.parakeet import ParakeetTranscriber
from tests.fakes import DUMMY_KEY, FakeTransport

TRANSCRIPT = "エラーで何も操作できません。すぐ確認してほしいです"
FAKE_WORKER = Path(__file__).resolve().parent / "fake_worker.py"


def snapshot(root: Path) -> set[Path]:
    return {p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
            and ".venv" not in p.parts and ".git" not in p.parts and ".pytest_cache" not in p.parts
            and ".cache" not in p.parts}


def test_nothing_is_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = snapshot(PROJECT_ROOT)
    pipeline = Pipeline(JevClient(Settings(), api_key=DUMMY_KEY, transport=FakeTransport().transport()), Settings())
    result = pipeline.run_text(TRANSCRIPT)
    assert result.ok
    assert list(tmp_path.iterdir()) == []
    assert snapshot(PROJECT_ROOT) == before


def test_audio_is_never_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = snapshot(PROJECT_ROOT)
    transcriber = ParakeetTranscriber(VoiceSettings(wsl_python="x", model_dir="y", request_timeout_s=5),
                                      command=[sys.executable, "-u", str(FAKE_WORKER), "ok"])
    transcriber.start()
    pipeline = Pipeline(JevClient(Settings(), api_key=DUMMY_KEY, transport=FakeTransport().transport()), Settings(),
                        transcriber=transcriber)
    result = pipeline.run_audio(b"\x00\x10" * 16000)
    transcriber.close()
    assert result.ok
    assert list(tmp_path.iterdir()) == []
    assert snapshot(PROJECT_ROOT) == before
    assert not any(p.suffix.lower() in (".wav", ".flac", ".mp3", ".ogg") for p in PROJECT_ROOT.rglob("*")
                   if ".venv" not in p.parts)


def test_api_key_never_appears_in_logs_results_or_errors(monkeypatch, caplog):
    monkeypatch.setenv("TYPESAFE_API_KEY", DUMMY_KEY)
    caplog.set_level(logging.DEBUG)
    logging.getLogger("typesafe_sdk").setLevel(logging.DEBUG)
    ok = Pipeline(JevClient(Settings(), transport=FakeTransport().transport()), Settings()).run_text(TRANSCRIPT)
    failing = Pipeline(JevClient(Settings(), transport=FakeTransport(status=401, text_body="nope").transport()), Settings())
    failed = failing.run_text(TRANSCRIPT)
    assert ok.ok and not failed.ok
    assert DUMMY_KEY not in caplog.text
    assert DUMMY_KEY not in json.dumps(ok.to_dict(), ensure_ascii=False)
    assert DUMMY_KEY not in json.dumps(failed.to_dict(), ensure_ascii=False)
    with pytest.raises(JevError) as info:
        JevClient(Settings(), transport=FakeTransport(status=401, text_body=DUMMY_KEY).transport()).decide("x")
    assert DUMMY_KEY not in str(info.value) and DUMMY_KEY not in info.value.message_ja


def test_api_key_presence_check_does_not_expose_value(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", DUMMY_KEY)
    assert api_key_present() is True
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert api_key_present() is False


def test_error_messages_contain_neither_transcript_nor_provider_body():
    fake = FakeTransport(status=422, text_body='{"detail": "PROVIDER-DETAIL"}')
    result = Pipeline(JevClient(Settings(), api_key=DUMMY_KEY, transport=fake.transport()), Settings()).run_text(TRANSCRIPT)
    assert result.ok is False
    assert "PROVIDER-DETAIL" not in result.error_message
    assert TRANSCRIPT not in result.error_message


def test_session_history_lives_only_in_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pipeline = Pipeline(JevClient(Settings(), api_key=DUMMY_KEY, transport=FakeTransport().transport()), Settings())
    pipeline.run_text(TRANSCRIPT)
    assert len(pipeline.history()) == 1
    assert list(tmp_path.iterdir()) == []
    assert not (PROJECT_ROOT / "logs").exists()


def test_env_example_has_key_names_only():
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            assert key.strip() in {"TYPESAFE_API_KEY", "JVD_PARAKEET_WSL_PYTHON", "JVD_PARAKEET_MODEL_DIR",
                                   "JVD_PARAKEET_EXTRACTED_DIR"} and value.strip() == ""
    assert ".env" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert not os.environ.get("TYPESAFE_API_KEY", "").startswith("sk-")  # tests must never run with a real key
