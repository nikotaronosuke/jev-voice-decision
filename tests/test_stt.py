from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from app.config import VoiceSettings
from app.stt.audio import StreamingResampler, encode_pcm16, pcm16_seconds, rms
from app.stt.parakeet import ParakeetTranscriber, SttError, windows_to_wsl_path, worker_command, worker_environment

FAKE_WORKER = Path(__file__).resolve().parent / "fake_worker.py"


def fake_command(mode: str = "ok") -> list[str]:
    return [sys.executable, "-u", str(FAKE_WORKER), mode]


def settings(**kwargs) -> VoiceSettings:
    base = dict(wsl_python="/venv/bin/python", model_dir="/models/parakeet-ja", ready_timeout_s=20, request_timeout_s=3)
    base.update(kwargs)
    return VoiceSettings(**base)


def one_second_pcm() -> bytes:
    import numpy as np
    t = np.arange(16000) / 16000
    return encode_pcm16(0.2 * np.sin(2 * math.pi * 440 * t))


def test_resampler_48k_to_16k_keeps_duration_and_is_causal():
    import numpy as np
    resampler = StreamingResampler(48000, 16000)
    chunks = [np.random.default_rng(0).uniform(-0.5, 0.5, 960) for _ in range(50)]  # 20 ms each
    total = sum(len(resampler.process(chunk)) for chunk in chunks)
    assert abs(total - 50 * 320) <= 320
    assert StreamingResampler(16000, 16000).identity is True


def test_pcm16_helpers():
    pcm = one_second_pcm()
    assert len(pcm) == 32000
    assert pcm16_seconds(pcm) == pytest.approx(1.0)
    assert 0.1 < rms([0.2, -0.2, 0.2, -0.2]) < 0.3
    assert encode_pcm16([2.0, -2.0]) == b"\xff\x7f\x00\x80"


def test_windows_path_becomes_wsl_path():
    assert windows_to_wsl_path(Path("C:/proj/app/stt/parakeet_worker.py")) == "/mnt/c/proj/app/stt/parakeet_worker.py"


def test_worker_command_and_environment_never_carry_credentials(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy-value-not-a-real-key-000000")
    command = worker_command(settings(extracted_dir="/models/extracted"))
    assert command[:3] == ["wsl", "-d", "Ubuntu"] and "--extracted-dir" in command and "--cache-dir" in command
    env = worker_environment()
    assert "TYPESAFE_API_KEY" not in env
    assert env["WSLENV"] == ""
    assert all("KEY" not in k.upper() and "TOKEN" not in k.upper() for k in env)


def test_fake_worker_round_trip_and_states():
    states: list[str] = []
    t = ParakeetTranscriber(settings(), command=fake_command("ok"), on_state=lambda s, c: states.append(s))
    t.start()
    assert t.state == "ready" and states == ["starting", "ready"]
    assert t.transcribe(one_second_pcm()) == "これって無料で使えますか#32000"
    assert t.transcribe(one_second_pcm()) == "これって無料で使えますか#32000"  # second request on the same worker
    t.close()
    assert t.state == "stopped"


def test_fatal_worker_is_reported_as_start_failure():
    t = ParakeetTranscriber(settings(), command=fake_command("fatal"))
    with pytest.raises(SttError) as info:
        t.start()
    assert info.value.code == "stt_start_failed" and t.state == "error"


def test_worker_error_timeout_and_empty_text():
    for mode, code in (("error", "stt_failed"), ("slow", "stt_timeout"), ("silent", "stt_empty")):
        t = ParakeetTranscriber(settings(), command=fake_command(mode))
        t.start()
        with pytest.raises(SttError) as info:
            t.transcribe(one_second_pcm())
        assert info.value.code == code, mode
        t.close()


def test_short_audio_and_not_ready_are_rejected_before_any_request():
    t = ParakeetTranscriber(settings(), command=fake_command("ok"))
    with pytest.raises(SttError) as info:
        t.transcribe(one_second_pcm())
    assert info.value.code == "stt_not_ready"
    t.start()
    with pytest.raises(SttError) as info:
        t.transcribe(b"\x00\x00" * 100)
    assert info.value.code == "audio_too_short"
    t.close()


def test_unconfigured_settings_fail_fast():
    t = ParakeetTranscriber(VoiceSettings())
    with pytest.raises(SttError) as info:
        t.start()
    assert info.value.code == "stt_unconfigured"
    assert SttError("stt_unconfigured").message_ja.startswith("端末内 STT")
