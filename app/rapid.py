"""RAPID DEMO: send fictional comments to Jev with bounded concurrency; every item is a real request.

Nothing is precomputed, cached, or written to disk. Results are handed to the page in the
order they arrive and live only in memory for the duration of the run.

`RapidDemo`  – strictly sequential (25 items; kept for tests and smoke runs).
`RapidRunner` – bounded concurrency (RAPID_CONCURRENCY, default 12). A rate-limit reply pauses
new submissions for a moment and halves the concurrency limit; no extra retries are added on top
of the SDK's own policy (at most one automatic retry in this app).
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Any

from app.actions import decide_action
from app.config import PROJECT_ROOT
from app.jev.client import JevError
from app.models import PipelineResult
from app.pipeline import Pipeline

FIXTURE = PROJECT_ROOT / "fixtures" / "rapid-demo-comments.json"
FIXTURE_200 = PROJECT_ROOT / "fixtures" / "rapid-demo-200.json"
DEFAULT_CONCURRENCY = 12
RATE_LIMIT_PAUSE_S = 1.0


def rapid_concurrency() -> int:
    try:
        return max(1, min(64, int(os.environ.get("RAPID_CONCURRENCY", DEFAULT_CONCURRENCY))))
    except ValueError:
        return DEFAULT_CONCURRENCY


def load_rapid_comments(path=FIXTURE) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(item) for item in data["comments"]]


def decide_one(pipeline: Pipeline, text: str) -> PipelineResult:
    """One real request through the same adapter and rules as the normal pipeline, without stage callbacks."""
    try:
        decisions = pipeline.jev.decide(text)
    except JevError as error:
        return PipelineResult(ok=False, transcript=text, decisions=None, action=None,
                              error_code=error.code, error_message=error.message_ja)
    return PipelineResult(ok=True, transcript=text, decisions=decisions, action=decide_action(decisions, pipeline.settings))


class RapidDemo:
    """Strictly sequential: one request in flight at most."""

    def __init__(self, pipeline: Pipeline, comments: list[str] | None = None):
        self.pipeline = pipeline
        self.comments = list(comments) if comments is not None else load_rapid_comments()
        self.total = len(self.comments)
        self.index = 0
        self.stopped = False
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self.index = 0
            self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def step(self) -> dict[str, Any]:
        with self._lock:
            if self.stopped or self.index >= self.total:
                return {"done": True, "index": self.index, "total": self.total, "stopped": self.stopped}
            position = self.index
            text = self.comments[position]
            result = self.pipeline.run_text(text, record_history=False)
            self.index = position + 1
            return {"done": self.index >= self.total, "index": self.index, "total": self.total,
                    "stopped": False, "text": text, "result": result.to_dict()}


class RapidRunner:
    """Bounded-concurrency runner. Start with start(); the page drains results with poll()."""

    def __init__(self, pipeline: Pipeline, comments: list[str] | None = None, *, concurrency: int | None = None,
                 pause_s: float = RATE_LIMIT_PAUSE_S):
        self.pipeline = pipeline
        self.comments = list(comments) if comments is not None else load_rapid_comments(FIXTURE_200)
        self.total = len(self.comments)
        self.max_concurrency = concurrency or rapid_concurrency()
        self.limit = self.max_concurrency
        self.pause_s = pause_s
        self.paused_until = 0.0
        self.in_flight = 0
        self.next_index = 0
        self.completed = 0
        self.errors = 0
        self.rate_limited = 0
        self.stopped = False
        self.finished = False
        self.peak_in_flight = 0
        self._results: deque[dict[str, Any]] = deque()
        self._cv = threading.Condition()
        self._threads: list[threading.Thread] = []

    # ---- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        for _ in range(self.max_concurrency):
            thread = threading.Thread(target=self._worker, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """No new submissions; requests already in flight finish normally."""
        with self._cv:
            self.stopped = True
            self._cv.notify_all()

    def wait(self, timeout: float | None = None) -> bool:
        with self._cv:
            return self._cv.wait_for(lambda: self.finished, timeout=timeout)

    # ---- workers ----------------------------------------------------------------
    def _take(self) -> int | None:
        """Block until a slot is free and submissions are allowed; return the next index or None to exit."""
        with self._cv:
            while True:
                if self.stopped or self.next_index >= self.total:
                    self._maybe_finish_locked()
                    return None
                wait_for = self.paused_until - time.monotonic()
                if wait_for > 0:
                    self._cv.wait(timeout=wait_for)
                    continue
                if self.in_flight >= self.limit:
                    self._cv.wait(timeout=0.25)
                    continue
                index = self.next_index
                self.next_index += 1
                self.in_flight += 1
                self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
                return index

    def _worker(self) -> None:
        while True:
            index = self._take()
            if index is None:
                return
            text = self.comments[index]
            result = decide_one(self.pipeline, text)
            with self._cv:
                self.in_flight -= 1
                self.completed += 1
                if not result.ok:
                    self.errors += 1
                    if result.error_code == "rate_limit":
                        self.rate_limited += 1
                        self.limit = max(1, self.limit // 2)
                        self.paused_until = time.monotonic() + self.pause_s
                self._results.append({"index": index, "text": text, "result": result.to_dict()})
                self._maybe_finish_locked()
                self._cv.notify_all()

    def _maybe_finish_locked(self) -> None:
        if self.in_flight == 0 and (self.stopped or self.next_index >= self.total):
            self.finished = True

    # ---- page interface ----------------------------------------------------------
    def poll(self) -> dict[str, Any]:
        with self._cv:
            batch = list(self._results)
            self._results.clear()
            return {"results": batch, "completed": self.completed, "total": self.total, "finished": self.finished,
                    "stopped": self.stopped, "in_flight": self.in_flight, "limit": self.limit}
