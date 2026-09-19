"""Desktop entry point: pywebview window + a small Python API exposed to the page.

The page never sees the API key. Everything the page receives is a plain dict built
from PipelineResult; exceptions are converted to short error codes before crossing the bridge.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from app.actions import ACTION_LABELS_JA
from app.config import (DEFAULT_SETTINGS, PROJECT_ROOT, Settings, VoiceSettings, api_key_present, default_model_name,
                        load_dotenv_if_present, voice_settings_from_env)
from app.jev.client import ERROR_MESSAGES_JA, JevClient, JevError
from app.jev.questions import INTENT_IDS, INTENT_LABELS_JA, PRIORITY_LABELS_JA, PRIORITY_LEVELS
from app.pipeline import Pipeline
from app.stt.microphone import MicrophoneCapture, MicrophoneError
from app.stt.parakeet import STT_MESSAGES_JA, ParakeetTranscriber, SttError

UI_DIR = Path(__file__).resolve().parent / "ui"
FIXTURE = PROJECT_ROOT / "fixtures" / "demo-comments.json"
WINDOW_TITLE = "Jev Voice Decision"


def load_examples() -> list[str]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [str(item) for item in data.get("examples", [])]


def error_payload(code: str, message: str | None = None) -> dict[str, Any]:
    message = message or ERROR_MESSAGES_JA.get(code) or STT_MESSAGES_JA.get(code) or ERROR_MESSAGES_JA["unknown"]
    return {"ok": False, "transcript": "", "decisions": None, "action": None, "error_code": code, "error_message": message}


class Api:
    """Methods callable from JavaScript as window.pywebview.api.<name>(...)."""

    def __init__(self, pipeline: Pipeline | None, settings: Settings, startup_error: str | None = None,
                 transcriber: ParakeetTranscriber | None = None, voice_settings: VoiceSettings | None = None):
        self._pipeline = pipeline
        self._settings = settings
        self._startup_error = startup_error
        self._transcriber = transcriber
        self._voice_settings = voice_settings or VoiceSettings()
        self._window: Any = None
        self._capture: MicrophoneCapture | None = None
        self._capture_lock = threading.Lock()
        self._level = 0.0

    # ---- plumbing -----------------------------------------------------------
    def attach_window(self, window: Any) -> None:
        self._window = window

    def _js(self, code: str) -> None:
        if self._window is not None:
            try:
                self._window.evaluate_js(code)
            except Exception:
                pass

    def push_stage(self, stage: str) -> None:
        self._js(f"window.jvd && window.jvd.setStage({json.dumps(stage)})")

    def push_voice_state(self, state: str, code: str | None) -> None:
        message = STT_MESSAGES_JA.get(code or "", "") if state == "error" else ""
        self._js(f"window.jvd && window.jvd.setVoiceState({json.dumps(state)}, {json.dumps(message)})")

    def _on_meter(self, level: float) -> None:
        # Stored only; the page polls meter_level(). No calls into the page from the capture thread.
        self._level = level

    def shutdown(self) -> None:
        with self._capture_lock:
            if self._capture is not None:
                self._capture.stop()
                self._capture = None
        if self._transcriber is not None:
            self._transcriber.close()

    # ---- exposed to the page ------------------------------------------------
    def status(self) -> dict[str, Any]:
        transcriber = self._transcriber
        return {
            "api_key_present": api_key_present(),
            "model": default_model_name(),
            "voice_available": transcriber is not None,
            "voice_state": transcriber.state if transcriber else "unconfigured",
            "voice_error_message": STT_MESSAGES_JA.get(transcriber.error_code or "", "") if transcriber and transcriber.error_code else "",
            "voice_engine": {"name": transcriber.name, **{k: transcriber.metadata.get(k) for k in ("device", "gpu_name")}} if transcriber else None,
            "max_utterance_s": self._voice_settings.max_utterance_s,
            "thresholds": {
                "confidence": self._settings.demo_confidence_threshold,
                "needs_response": self._settings.demo_needs_response_threshold,
                "priority_highlight": self._settings.demo_priority_highlight_score,
            },
            "labels": {
                "intent_ids": list(INTENT_IDS),
                "intent": INTENT_LABELS_JA,
                "priority": list(PRIORITY_LABELS_JA),
                "priority_levels": list(PRIORITY_LEVELS),
                "action": ACTION_LABELS_JA,
            },
            "startup_error": self._startup_error,
            "startup_error_message": ERROR_MESSAGES_JA.get(self._startup_error, "") if self._startup_error else "",
        }

    def examples(self) -> list[str]:
        return load_examples()

    def decide(self, text: str) -> dict[str, Any]:
        if self._pipeline is None:
            return error_payload(self._startup_error or "unknown")
        try:
            return self._pipeline.run_text(str(text)).to_dict()
        except Exception as error:  # never let a raw exception (possibly with details) reach the page
            return error_payload(error.code if isinstance(error, (JevError, SttError)) else "unknown")

    def history(self) -> list[dict[str, Any]]:
        return self._pipeline.history() if self._pipeline else []

    def start_listening(self) -> dict[str, Any]:
        if self._transcriber is None:
            return {"ok": False, "error_message": STT_MESSAGES_JA["stt_unconfigured"]}
        if self._transcriber.state != "ready":
            code = "stt_starting" if self._transcriber.state == "starting" else "stt_not_ready"
            return {"ok": False, "error_message": STT_MESSAGES_JA[code]}
        with self._capture_lock:
            if self._capture is not None:
                return {"ok": True}
            self._level = 0.0
            capture = MicrophoneCapture(on_meter=self._on_meter, max_seconds=self._voice_settings.max_utterance_s)
            try:
                capture.start()
            except MicrophoneError as error:
                return {"ok": False, "error_message": STT_MESSAGES_JA.get(error.code, STT_MESSAGES_JA["mic_unavailable"])}
            self._capture = capture
        self.push_stage("listening")
        return {"ok": True, "device": capture.device_name[:40]}

    def meter_level(self) -> dict[str, Any]:
        capture = self._capture
        return {"level": round(self._level, 4), "seconds": round(capture.seconds(), 2) if capture else 0.0,
                "recording": capture is not None}

    def stop_listening(self) -> dict[str, Any]:
        with self._capture_lock:
            capture, self._capture = self._capture, None
        if capture is None:
            return error_payload("audio_too_short")
        pcm = capture.stop()
        self._level = 0.0
        if self._pipeline is None:
            return error_payload(self._startup_error or "unknown")
        try:
            return self._pipeline.run_audio(pcm).to_dict()
        except Exception as error:
            return error_payload(error.code if isinstance(error, (JevError, SttError)) else "unknown")
        finally:
            del pcm

    def cancel_listening(self) -> dict[str, Any]:
        with self._capture_lock:
            capture, self._capture = self._capture, None
        if capture is not None:
            capture.stop()
        self._level = 0.0
        self.push_stage("idle")
        return {"ok": True}


def build_app(settings: Settings = DEFAULT_SETTINGS) -> Api:
    load_dotenv_if_present()
    voice_settings = voice_settings_from_env()
    api = Api(None, settings, voice_settings=voice_settings)
    transcriber: ParakeetTranscriber | None = None
    if voice_settings.configured():
        transcriber = ParakeetTranscriber(voice_settings, on_state=api.push_voice_state)
    pipeline: Pipeline | None = None
    startup_error: str | None = None
    try:
        jev = JevClient(settings)
        pipeline = Pipeline(jev, settings, transcriber=transcriber, on_stage=api.push_stage)
    except JevError as error:
        startup_error = error.code
    api._pipeline = pipeline
    api._startup_error = startup_error
    api._transcriber = transcriber
    if transcriber is not None:
        transcriber.start_async()
    return api


def main() -> None:
    import webview

    api = build_app()
    window = webview.create_window(WINDOW_TITLE, str(UI_DIR / "index.html"), js_api=api,
                                   width=1400, height=960, min_size=(1000, 720))
    api.attach_window(window)
    window.events.closed += api.shutdown
    webview.start()


if __name__ == "__main__":
    main()
