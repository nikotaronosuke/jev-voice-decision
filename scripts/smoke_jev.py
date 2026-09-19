"""Real Jev smoke: sends the fictional demo utterances to TypeSafe. Requires --confirm-send.

Nothing is written to disk. Output is a human-readable table for local confirmation only;
it is not a benchmark and must not be turned into one.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DEFAULT_SETTINGS, PROJECT_ROOT, api_key_present, load_dotenv_if_present  # noqa: E402
from app.actions import ACTION_LABELS_JA  # noqa: E402
from app.jev.client import JevClient, JevError  # noqa: E402
from app.jev.questions import INTENT_IDS, INTENT_LABELS_JA, PRIORITY_LABELS_JA  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402

MAX_EXAMPLES = 8


def main() -> int:
    parser = argparse.ArgumentParser(description="Send up to 8 fictional Japanese utterances to the real Jev API.")
    parser.add_argument("--confirm-send", action="store_true", help="required: acknowledges that real requests are sent")
    parser.add_argument("--limit", type=int, default=MAX_EXAMPLES)
    parser.add_argument("--text", action="append", default=[], help="extra utterance (repeatable)")
    args = parser.parse_args()
    if not args.confirm_send:
        print("refusing: pass --confirm-send to actually contact TypeSafe", file=sys.stderr)
        return 2
    load_dotenv_if_present()
    if not api_key_present():
        print("refusing: TYPESAFE_API_KEY is not set (environment or untracked .env)", file=sys.stderr)
        return 2
    examples = json.loads((PROJECT_ROOT / "fixtures" / "demo-comments.json").read_text(encoding="utf-8"))["examples"]
    utterances = (list(examples) + list(args.text))[: min(args.limit, MAX_EXAMPLES)]
    try:
        pipeline = Pipeline(JevClient(DEFAULT_SETTINGS), DEFAULT_SETTINGS)
    except JevError as error:
        print(f"client error: {error.code}", file=sys.stderr)
        return 1
    failures = 0
    for text in utterances:
        result = pipeline.run_text(text)
        print("=" * 72)
        print("INPUT     :", text)
        if not result.ok:
            failures += 1
            print("ERROR     :", result.error_code, "-", result.error_message)
            continue
        d, a = result.decisions, result.action
        dist = "  ".join(f"{INTENT_LABELS_JA[k]} {d.intent.probabilities[k]:.2f}" for k in INTENT_IDS)
        print(f"intent    : {INTENT_LABELS_JA[d.intent.selected]}  (confidence {d.intent.confidence:.2f})  [{dist}]")
        print(f"needs_resp: P(yes)={d.needs_response.probability_yes:.2f}")
        levels = "  ".join(f"{PRIORITY_LABELS_JA[i]} {d.priority.probabilities.get(i, 0.0):.2f}" for i in range(d.priority.max_level + 1))
        print(f"priority  : score {d.priority.score:.2f}/{d.priority.max_level}  (confidence {d.priority.confidence:.2f})  [{levels}]")
        print(f"action    : {ACTION_LABELS_JA[a.action]}  hold={a.hold} highlight={a.highlight}")
        print(f"meta      : model={d.model} latency={d.latency_ms:.0f}ms tokens={d.input_tokens}/{d.output_tokens} request_id={d.request_id}")
    print("=" * 72)
    print(f"done: {len(utterances) - failures} ok, {failures} failed (history entries in memory: {len(pipeline.history())})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
