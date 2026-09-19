"""A stand-in for the local speech worker: speaks the same JSONL protocol without any model.

Modes (first argument): ok | fatal | error | slow | silent
"""
from __future__ import annotations

import base64
import json
import sys
import time

FIXED_TEXT = "これって無料で使えますか"


def emit(value: dict) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # the protocol is UTF-8 regardless of the console code page
    mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
    emit({"kind": "started", "pid": 0})
    if mode == "fatal":
        emit({"kind": "fatal", "code": "model_checkpoint_missing"})
        return
    emit({"kind": "ready", "metadata": {"engine": "fake", "device": "none"}})
    for line in sys.stdin:
        message = json.loads(line)
        if message.get("quit"):
            return
        request = message.get("request")
        pcm = base64.b64decode(message["audio"])
        if mode == "error":
            emit({"kind": "error", "request": request, "code": "inference_failed"})
        elif mode == "slow":
            time.sleep(5)
            emit({"kind": "result", "request": request, "text": FIXED_TEXT})
        elif mode == "silent":
            emit({"kind": "result", "request": request, "text": ""})
        else:
            emit({"kind": "result", "request": request, "text": f"{FIXED_TEXT}#{len(pcm)}"})


if __name__ == "__main__":
    main()
