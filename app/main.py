"""Desktop entry point: pywebview window + a small Python API exposed to the page.

The page never sees the API key. Everything the page receives is a plain dict built
from PipelineResult; exceptions are converted to short error codes before crossing the bridge.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import DEFAULT_SETTINGS, PROJECT_ROOT, Settings, api_key_present, default_model_name, load_dotenv_if_present
from app.jev.client import ERROR_MESSAGES_JA, JevClient, JevError
from app.jev.questions import INTENT_IDS, INTENT_LABELS_JA, PRIORITY_LABELS_JA, PRIORITY_LEVELS
from app.actions import ACTION_LABELS_JA
from app.pipeline import Pipeline

UI_DIR = Path(__file__).resolve().parent / "ui"
FIXTURE = PROJECT_ROOT / "fixtures" / "demo-comments.json"
WINDOW_TITLE = "Jev Voice Decision"


def load_examples() -> list[str]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [str(item) for item in data.get("examples", [])]


class Api:
    """Methods callable from JavaScript as window.pywebview.api.<name>(...)."""

    def __init__(self, pipeline: Pipeline | None, settings: Settings, startup_error: str | None = None):
        self._pipeline = pipeline
        self._settings = settings
        self._startup_error = startup_error
        self._window: Any = None

    def attach_window(self, window: Any) -> None:
        self._window = window

    def push_stage(self, stage: str) -> None:
        if self._window is not None:
            self._window.evaluate_js(f"window.jvd && window.jvd.setStage({json.dumps(stage)})")

    # ---- exposed to the page ------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "api_key_present": api_key_present(),
            "model": default_model_name(),
            "mode": "text",
            "voice_available": False,
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
            code = self._startup_error or "unknown"
            return {"ok": False, "transcript": "", "decisions": None, "action": None,
                    "error_code": code, "error_message": ERROR_MESSAGES_JA.get(code, ERROR_MESSAGES_JA["unknown"])}
        try:
            return self._pipeline.run_text(str(text)).to_dict()
        except Exception as error:  # never let a raw exception (possibly with details) reach the page
            code = error.code if isinstance(error, JevError) else "unknown"
            return {"ok": False, "transcript": "", "decisions": None, "action": None,
                    "error_code": code, "error_message": ERROR_MESSAGES_JA.get(code, ERROR_MESSAGES_JA["unknown"])}

    def history(self) -> list[dict[str, Any]]:
        return self._pipeline.history() if self._pipeline else []


def build_app(settings: Settings = DEFAULT_SETTINGS) -> Api:
    load_dotenv_if_present()
    pipeline: Pipeline | None = None
    startup_error: str | None = None
    api = Api(None, settings)
    try:
        jev = JevClient(settings)
        pipeline = Pipeline(jev, settings, on_stage=api.push_stage)
    except JevError as error:
        startup_error = error.code
    api._pipeline = pipeline
    api._startup_error = startup_error
    return api


def main() -> None:
    import webview

    api = build_app()
    window = webview.create_window(WINDOW_TITLE, str(UI_DIR / "index.html"), js_api=api,
                                   width=1380, height=880, min_size=(1000, 700))
    api.attach_window(window)
    webview.start()


if __name__ == "__main__":
    main()
