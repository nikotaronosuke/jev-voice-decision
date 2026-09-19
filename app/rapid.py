"""RAPID DEMO: send fictional comments to Jev one at a time, strictly in order, one in flight at most.

Every step is a real request through the normal pipeline. Nothing is precomputed, cached,
or written to disk; a step's result lives only in the dict handed back to the page.
"""
from __future__ import annotations

import json
import threading
from typing import Any

from app.config import PROJECT_ROOT
from app.pipeline import Pipeline

FIXTURE = PROJECT_ROOT / "fixtures" / "rapid-demo-comments.json"


def load_rapid_comments(path=FIXTURE) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(item) for item in data["comments"]]


class RapidDemo:
    def __init__(self, pipeline: Pipeline, comments: list[str] | None = None):
        self.pipeline = pipeline
        self.comments = list(comments) if comments is not None else load_rapid_comments()
        self.total = len(self.comments)
        self.index = 0            # number of comments already processed
        self.stopped = False
        self._lock = threading.Lock()  # one request in flight at most, even if the page misbehaves

    def reset(self) -> None:
        with self._lock:
            self.index = 0
            self.stopped = False

    def stop(self) -> None:
        self.stopped = True  # the step in flight finishes; no further request is sent

    def step(self) -> dict[str, Any]:
        """Process the next comment (blocking) and return it with the pipeline result."""
        with self._lock:
            if self.stopped or self.index >= self.total:
                return {"done": True, "index": self.index, "total": self.total, "stopped": self.stopped}
            position = self.index
            text = self.comments[position]
            result = self.pipeline.run_text(text, record_history=False)
            self.index = position + 1
            return {"done": self.index >= self.total, "index": self.index, "total": self.total,
                    "stopped": False, "text": text, "result": result.to_dict()}
