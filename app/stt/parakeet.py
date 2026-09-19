"""Windows-side driver for the local Parakeet JA worker (runs in WSL). Final transcript only, one request at a time."""
from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.config import PROJECT_ROOT, VoiceSettings
from app.stt.audio import pcm16_seconds

WORKER_SCRIPT = Path(__file__).resolve().parent / "parakeet_worker.py"

STT_MESSAGES_JA: dict[str, str] = {
    "stt_unconfigured": "端末内 STT が設定されていません（.env の JVD_PARAKEET_* を確認してください）",
    "stt_starting": "端末内 STT を準備しています",
    "stt_not_ready": "端末内 STT の準備ができていません",
    "stt_start_failed": "端末内 STT を起動できませんでした",
    "stt_timeout": "端末内 STT が時間内に応答しませんでした",
    "stt_failed": "端末内 STT で文字起こしに失敗しました",
    "stt_empty": "音声から文字を取り出せませんでした",
    "audio_too_short": "録音が短すぎます。もう一度話してください",
    "no_speech": "音声が検出されませんでした。もう一度話してください",
    "mic_unavailable": "マイクを開けませんでした",
}


class SttError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    @property
    def message_ja(self) -> str:
        return STT_MESSAGES_JA.get(self.code, STT_MESSAGES_JA["stt_failed"])


def windows_to_wsl_path(path: Path) -> str:
    path = path.resolve()
    drive = path.drive.rstrip(":").lower()
    return "/mnt/" + drive + "/" + "/".join(path.parts[1:]).replace("\\", "/")


def worker_environment(source: dict | None = None) -> dict[str, str]:
    """Allow-list for the child process: no service credentials can reach the worker."""
    source = os.environ if source is None else source
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "COMSPEC", "USERPROFILE", "HOMEDRIVE",
               "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
               "SYSTEMDRIVE", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
    env = {k: source[k] for k in source if k.upper() in allowed}
    env["WSLENV"] = ""  # nothing from the Windows environment is forwarded into WSL
    return env


def worker_command(settings: VoiceSettings) -> list[str]:
    cache_dir = windows_to_wsl_path(PROJECT_ROOT / ".cache" / "parakeet")
    command = ["wsl", "-d", settings.wsl_distro, "--", settings.wsl_python, "-u", windows_to_wsl_path(WORKER_SCRIPT),
               "--model-dir", settings.model_dir, "--cache-dir", cache_dir, "--precision", settings.precision]
    if settings.extracted_dir:
        command += ["--extracted-dir", settings.extracted_dir]
    return command


class ParakeetTranscriber:
    """Owns one worker process. `transcribe` blocks; callers serialize through `lock`."""

    name = "parakeet-ja"

    def __init__(self, settings: VoiceSettings, *, command: list[str] | None = None,
                 on_state: Callable[[str, str | None], None] | None = None):
        self.settings = settings
        self.command = command
        self.on_state = on_state or (lambda state, message: None)
        self.process: subprocess.Popen | None = None
        self.state = "stopped"
        self.error_code: str | None = None
        self.metadata: dict = {}
        self.lock = threading.Lock()
        self._events: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._ready = threading.Event()
        self._counter = 0

    def _set_state(self, state: str, code: str | None = None) -> None:
        self.state = state
        self.error_code = code
        self.on_state(state, code)

    def start_async(self) -> None:
        threading.Thread(target=self._start_guarded, daemon=True).start()

    def _start_guarded(self) -> None:
        try:
            self.start()
        except SttError:
            pass

    def start(self) -> None:
        if not self.settings.configured():
            self._set_state("error", "stt_unconfigured")
            raise SttError("stt_unconfigured")
        self._set_state("starting")
        (PROJECT_ROOT / ".cache" / "parakeet").mkdir(parents=True, exist_ok=True)
        command = self.command or worker_command(self.settings)
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, env=worker_environment(),
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            self._set_state("error", "stt_start_failed")
            raise SttError("stt_start_failed") from None
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        deadline = time.monotonic() + self.settings.ready_timeout_s
        while time.monotonic() < deadline:
            try:
                event = self._events.get(timeout=0.5)
            except queue.Empty:
                process = self.process
                if process is None or process.poll() is not None:  # closed while starting
                    break
                continue
            kind = event.get("kind")
            if kind == "ready":
                self.metadata = dict(event.get("metadata") or {})
                self._ready.set()
                self._set_state("ready")
                return
            if kind == "fatal":
                break
        self.close()
        self._set_state("error", "stt_start_failed")
        raise SttError("stt_start_failed")

    def _read(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for raw in self.process.stdout:
            try:
                event = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                self._events.put(event)
        self._events.put({"kind": "eof"})

    def transcribe(self, pcm16: bytes) -> str:
        if self.state != "ready" or self.process is None or self.process.stdin is None:
            raise SttError("stt_not_ready" if self.state in ("starting", "stopped") else "stt_start_failed")
        if pcm16_seconds(pcm16) < self.settings.min_utterance_s:
            raise SttError("audio_too_short")
        with self.lock:
            while not self._events.empty():  # drop stale resource/maintenance events
                try:
                    self._events.get_nowait()
                except queue.Empty:
                    break
            self._counter += 1
            request = self._counter
            message = json.dumps({"request": request, "audio": base64.b64encode(pcm16).decode("ascii")}) + "\n"
            try:
                self.process.stdin.write(message.encode("utf-8"))
                self.process.stdin.flush()
            except (OSError, ValueError):
                self._set_state("error", "stt_failed")
                raise SttError("stt_failed") from None
            deadline = time.monotonic() + self.settings.request_timeout_s
            while time.monotonic() < deadline:
                try:
                    event = self._events.get(timeout=0.5)
                except queue.Empty:
                    if self.process.poll() is not None:
                        self._set_state("error", "stt_failed")
                        raise SttError("stt_failed")
                    continue
                kind = event.get("kind")
                if kind in ("result", "error") and event.get("request") == request:
                    if kind == "error":
                        raise SttError("stt_failed")
                    text = str(event.get("text", "")).strip()
                    if not text:
                        raise SttError("stt_empty")
                    return text
                if kind in ("fatal", "eof"):
                    self._set_state("error", "stt_failed")
                    raise SttError("stt_failed")
            raise SttError("stt_timeout")

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.write(b'{"quit": true}\n')
                process.stdin.flush()
                process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        if self.state != "error":
            self._set_state("stopped")
