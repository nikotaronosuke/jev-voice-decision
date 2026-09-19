"""PCM helpers: causal resampling to 16 kHz mono and PCM16 encoding. Nothing here touches disk."""
from __future__ import annotations

import math

TARGET_RATE = 16000


class StreamingResampler:
    """Causal FIR resampler. State persists across chunks; no look-ahead, no per-chunk padding."""

    def __init__(self, source_rate: int, target_rate: int = TARGET_RATE):
        import numpy as np
        from scipy.signal import firwin

        gcd = math.gcd(source_rate, target_rate)
        self.up, self.down = target_rate // gcd, source_rate // gcd
        self.phase = 0
        self.identity = self.up == self.down
        taps = 20 * max(self.up, self.down) + 1
        self.kernel = (np.array([1.0]) if self.identity
                       else firwin(taps, 1 / max(self.up, self.down), window=("kaiser", 5.0)) * self.up)
        self.state = np.zeros(len(self.kernel) - 1)

    def process(self, values):
        import numpy as np
        from scipy.signal import lfilter

        values = np.asarray(values, dtype=np.float64)
        if self.identity or not len(values):
            return values.copy()
        upsampled = np.zeros(len(values) * self.up)
        upsampled[:: self.up] = values
        filtered, self.state = lfilter(self.kernel, [1.0], upsampled, zi=self.state)
        output = filtered[self.phase :: self.down]
        self.phase = (self.phase - len(filtered)) % self.down
        return output


def encode_pcm16(values) -> bytes:
    import numpy as np

    return np.rint(np.clip(values, -1.0, 32767 / 32768) * 32768).astype("<i2").tobytes()


def rms(values) -> float:
    import numpy as np

    values = np.asarray(values, dtype=np.float64)
    return float(np.sqrt(np.mean(values * values))) if len(values) else 0.0


def pcm16_seconds(pcm16: bytes, rate: int = TARGET_RATE) -> float:
    return len(pcm16) / (2 * rate)


def trim_silence(pcm16: bytes, *, rate: int = TARGET_RATE, frame_ms: int = 20, absolute: float = 0.01,
                 relative: float = 0.1, margin_ms: int = 250) -> bytes:
    """Cut leading and trailing silence (energy below max(absolute, relative * peak)), keeping a margin.

    Speech models tend to invent words on long stretches of room noise, so the utterance handed
    to the recognizer starts and ends near the speech. Returns b"" when nothing exceeds the floor.
    """
    import numpy as np

    values = np.frombuffer(pcm16, dtype="<i2").astype(np.float64) / 32768.0
    frame = max(1, rate * frame_ms // 1000)
    count = len(values) // frame
    if count == 0:
        return pcm16
    frames = values[: count * frame].reshape(count, frame)
    energy = np.sqrt((frames * frames).mean(axis=1))
    floor = max(absolute, relative * float(energy.max()))
    active = np.flatnonzero(energy > floor)
    if not len(active):
        return b""
    margin = rate * margin_ms // 1000
    start = max(0, int(active[0]) * frame - margin)
    end = min(len(values), (int(active[-1]) + 1) * frame + margin)
    return encode_pcm16(values[start:end])
