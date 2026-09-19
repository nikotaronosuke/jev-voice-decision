"""Push-to-talk microphone capture (WASAPI default input) into an in-memory PCM16 16 kHz buffer.

Audio never touches disk. The buffer is discarded when the capture object is dropped.
"""
from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

from app.stt.audio import StreamingResampler, encode_pcm16, rms

MeterCallback = Callable[[float], None]


class MicrophoneError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class MicrophoneCapture:
    def __init__(self, *, on_meter: MeterCallback | None = None, chunk_ms: int = 20, max_seconds: float = 30.0):
        self.on_meter = on_meter or (lambda level: None)
        self.chunk_ms = chunk_ms
        self.max_bytes = int(max_seconds * 16000) * 2
        self.queue: queue.Queue = queue.Queue(maxsize=400)
        self.stop_event = threading.Event()
        self.buffer = bytearray()
        self.truncated = False
        self.errors: list[str] = []
        self.manager = None
        self.stream = None
        self.worker: threading.Thread | None = None
        self.rate = 0
        self.channels = 0
        self.device_name = ""
        self.started_at = 0.0

    def start(self) -> "MicrophoneCapture":
        import pyaudiowpatch as pa

        self.manager = pa.PyAudio()
        try:
            host = self.manager.get_host_api_info_by_type(pa.paWASAPI)
            device = self.manager.get_device_info_by_index(host["defaultInputDevice"])
            self.rate = int(device["defaultSampleRate"])
            self.channels = int(device["maxInputChannels"])
            self.device_name = str(device.get("name", ""))
            if self.channels < 1:
                raise MicrophoneError("mic_unavailable")
            self.stop_event.clear()
            self.buffer = bytearray()
            self.truncated = False
            self.worker = threading.Thread(target=self._consume, daemon=True)
            self.worker.start()

            def callback(data, frames, timing, status):
                try:
                    self.queue.put_nowait((data, frames))
                except queue.Full:
                    pass
                return None, pa.paContinue

            self.stream = self.manager.open(format=pa.paFloat32, channels=self.channels, rate=self.rate, input=True,
                                            input_device_index=device["index"],
                                            frames_per_buffer=max(1, round(self.rate * self.chunk_ms / 1000)),
                                            stream_callback=callback, start=False)
            self.stream.start_stream()
            self.started_at = time.perf_counter()
        except MicrophoneError:
            self.stop()
            raise
        except Exception as error:
            self.stop()
            self.errors.append(type(error).__name__)
            raise MicrophoneError("mic_unavailable") from None
        return self

    def _consume(self) -> None:
        import numpy as np

        resampler = StreamingResampler(self.rate, 16000)
        try:
            while not self.stop_event.is_set() or not self.queue.empty():
                try:
                    data, frames = self.queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                samples = np.frombuffer(data, dtype="<f4").reshape(-1, self.channels).mean(axis=1)
                self.on_meter(rms(samples))
                if len(self.buffer) >= self.max_bytes:
                    self.truncated = True
                    continue
                self.buffer.extend(encode_pcm16(resampler.process(samples)))
        except Exception as error:
            self.errors.append(type(error).__name__)
            self.stop_event.set()

    def stop(self) -> bytes:
        """Stop capturing and return the utterance as PCM16 mono 16 kHz. The buffer is then cleared."""
        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as error:
                self.errors.append(type(error).__name__)
            self.stream = None
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join(timeout=3)
            self.worker = None
        if self.manager is not None:
            self.manager.terminate()
            self.manager = None
        pcm = bytes(self.buffer[: self.max_bytes])
        self.buffer = bytearray()
        return pcm

    def seconds(self) -> float:
        return len(self.buffer) / 32000
