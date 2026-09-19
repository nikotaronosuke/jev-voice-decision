"""Runtime settings. The API key is never read into this module; the SDK reads it from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from typesafe_sdk.constants import API_KEY_ENV, DEFAULT_MODEL, DEFAULT_TIMEOUT

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Demo thresholds are explicit, named values; they are not tuned or claimed optimal."""

    # Below this Choice confidence the intent is put on hold (manual review). The
    # official Confidence guide describes < 0.5 as "do not act; route to a human".
    demo_confidence_threshold: float = 0.5
    # A Noul is the probability of "yes"; at or above this the utterance counts as needing a reply.
    demo_needs_response_threshold: float = 0.5
    # Score on the priority rubric (0 .. levels-1) at or above which the UI highlights the item.
    demo_priority_highlight_score: float = 2.0
    history_limit: int = 5
    request_timeout_s: float = DEFAULT_TIMEOUT
    # Official SDK default is 2 automatic retries; this demo allows at most one.
    max_auto_retries: int = 1
    model: str | None = None  # None -> SDK default (jev-latest) or TYPESAFE_DEFAULT_MODEL


DEFAULT_SETTINGS = Settings()


def load_dotenv_if_present(path: Path | None = None) -> bool:
    """Populate os.environ from an untracked .env (KEY=VALUE lines). Existing variables win."""
    path = path or PROJECT_ROOT / ".env"
    if not path.is_file():
        return False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
    return True


def api_key_present() -> bool:
    """Presence only. The value is never returned, logged, or shown."""
    return bool(os.environ.get(API_KEY_ENV))


def default_model_name() -> str:
    return os.environ.get("TYPESAFE_DEFAULT_MODEL") or DEFAULT_MODEL
