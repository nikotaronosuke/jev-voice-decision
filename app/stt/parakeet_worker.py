"""Local Parakeet JA worker (NVIDIA NeMo). Runs inside WSL, speaks JSONL over stdio, never touches the network.

Protocol (one JSON object per line):
  -> {"request": 1, "audio": "<base64 PCM16 mono 16 kHz>"}
  <- {"kind": "started"} / {"kind": "ready", "metadata": {...}} / {"kind": "result", "request": 1, "text": "..."}
     {"kind": "error", "request": 1, "code": "..."} / {"kind": "fatal", "code": "..."}
  -> {"quit": true}

Credential-like environment variables are removed before any import; caches are confined to --cache-dir.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

MAX_SECONDS = 30
protocol_out = sys.stdout


def emit(value: dict) -> None:
    protocol_out.write(json.dumps(value, ensure_ascii=False) + "\n")
    protocol_out.flush()


def main() -> None:
    if hasattr(protocol_out, "reconfigure"):
        protocol_out.reconfigure(encoding="utf-8")
    emit({"kind": "started", "pid": os.getpid()})
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--extracted-dir", default=None)
    parser.add_argument("--precision", choices=["fp32", "fp16", "bf16"], default="fp32")
    args = parser.parse_args()

    for name in list(os.environ):
        upper = name.upper()
        if any(marker in upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
            os.environ.pop(name, None)
    cache = Path(args.cache_dir)
    for sub in ("tmp", "huggingface", "nemo", "matplotlib"):
        (cache / sub).mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
                      TRANSFORMERS_OFFLINE="1", WANDB_MODE="disabled", OTEL_SDK_DISABLED="true", DO_NOT_TRACK="1",
                      TMPDIR=str(cache / "tmp"), HF_HOME=str(cache / "huggingface"),
                      NEMO_CACHE_DIR=str(cache / "nemo"), MPLCONFIGDIR=str(cache / "matplotlib"))
    sys.stdout = sys.stderr  # third-party logging must not corrupt the protocol stream

    import numpy as np
    import torch
    import nemo.collections.asr as nemo_asr
    from nemo.core.connectors.save_restore_connector import SaveRestoreConnector

    checkpoints = sorted(Path(args.model_dir).glob("*.nemo"))
    if len(checkpoints) != 1:
        raise RuntimeError("model_checkpoint_missing")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    connector = SaveRestoreConnector()
    extracted = Path(args.extracted_dir) if args.extracted_dir else None
    if extracted is not None and (extracted / "extraction.json").is_file():
        provenance_path = Path(args.model_dir) / "provenance.json"
        prepared = json.loads((extracted / "extraction.json").read_text(encoding="utf-8"))
        if provenance_path.is_file():
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            if prepared.get("checkpoint_sha256") != provenance.get("sha256"):
                raise RuntimeError("model_checkpoint_mismatch")
        connector.model_extracted_dir = str(extracted)  # read-only use of a pre-extracted checkpoint
    started = time.perf_counter()
    torch.set_num_threads(4)
    model = nemo_asr.models.ASRModel.restore_from(str(checkpoints[0]), map_location=device,
                                                 save_restore_connector=connector)
    model.eval()
    dtype = {"fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}[args.precision]

    def infer(pcm: bytes) -> str:
        values = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if not len(values) or len(values) > (MAX_SECONDS + 1) * 16000:
            raise ValueError("invalid_audio_size")
        import contextlib
        autocast = (torch.autocast("cuda", dtype=dtype) if device == "cuda" and args.precision != "fp32"
                    else contextlib.nullcontext())
        with torch.inference_mode(), autocast:
            results = model.transcribe([values], batch_size=1, verbose=False)
        if isinstance(results, tuple):
            results = results[0]
        hypothesis = results[0]
        return hypothesis.text if hasattr(hypothesis, "text") else str(hypothesis)

    infer(bytes(32000))  # warm-up on one second of silence
    if device == "cuda":
        torch.cuda.synchronize()
    emit({"kind": "ready", "metadata": {"engine": "nemo-parakeet-ja", "device": device,
                                        "gpu_name": torch.cuda.get_device_name() if device == "cuda" else None,
                                        "torch_version": torch.__version__, "load_warmup_s": time.perf_counter() - started,
                                        "pre_extracted_checkpoint": connector.model_extracted_dir is not None}})
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("quit"):
            break
        request = message.get("request")
        try:
            pcm = base64.b64decode(message["audio"], validate=True)
            if not pcm or len(pcm) % 2:
                raise ValueError("invalid_audio")
            emit({"kind": "result", "request": request, "text": infer(pcm)})
        except Exception as error:
            emit({"kind": "error", "request": request, "code": "inference_failed", "cause": type(error).__name__.lower()})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        known = str(error) if str(error) in ("model_checkpoint_missing", "model_checkpoint_mismatch") else "worker_initialization_failed"
        emit({"kind": "fatal", "code": known, "cause": type(error).__name__.lower()})
        raise SystemExit(1)
