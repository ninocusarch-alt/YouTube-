"""PCM helpers for local microphone / WASAPI loopback capture.

The existing backend already accepts 16 kHz mono signed-16-bit PCM base64
frames on ``/ws/sessions/{id}`` (``audio.append``). This module converts
whatever Windows gives us - usually 48 kHz stereo int16 - into that exact
shape. Pure standard library on purpose, so the PyInstaller payload stays
small and no numpy dependency is introduced.
"""
from __future__ import annotations

import array
import math
from collections import deque
from typing import Iterable, Iterator

TARGET_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = TARGET_RATE * FRAME_MS // 1000 * 2  # 640 bytes = 320 samples


def to_mono(data: bytes, channels: int = 2) -> bytes:
    if channels <= 1:
        return data[: len(data) // 2 * 2]
    frame_bytes = 2 * channels
    usable = data[: len(data) // frame_bytes * frame_bytes]
    samples = array.array('h')
    samples.frombytes(usable)
    out = array.array('h')
    for index in range(0, len(samples) - channels + 1, channels):
        out.append(sum(int(value) for value in samples[index:index + channels]) // channels)
    return out.tobytes()


def resample(data: bytes, src_rate: int, dst_rate: int = TARGET_RATE) -> bytes:
    """Linear resample. Adequate for speech; 48k -> 16k is an exact 3:1 ratio."""
    if src_rate <= 0 or src_rate == dst_rate:
        return data
    usable = data[: len(data) // 2 * 2]
    samples = array.array('h')
    samples.frombytes(usable)
    if not samples:
        return b''
    ratio = src_rate / dst_rate
    output_length = int(len(samples) / ratio)
    out = array.array('h')
    for index in range(output_length):
        position = index * ratio
        low = int(position)
        high = min(low + 1, len(samples) - 1)
        fraction = position - low
        value = samples[low] * (1 - fraction) + samples[high] * fraction
        out.append(int(max(-32768, min(32767, value))))
    return out.tobytes()


def normalize(data: bytes, channels: int, src_rate: int) -> bytes:
    return resample(to_mono(data, channels), int(src_rate))


class FrameAssembler:
    """Re-chunk arbitrary capture blocks into exact 20 ms frames."""

    def __init__(self, frame_bytes: int = FRAME_BYTES) -> None:
        self.frame_bytes = frame_bytes
        self._buffer = bytearray()

    def feed(self, pcm: bytes) -> Iterator[bytes]:
        self._buffer.extend(pcm)
        while len(self._buffer) >= self.frame_bytes:
            yield bytes(self._buffer[:self.frame_bytes])
            del self._buffer[:self.frame_bytes]


def rms(frame: bytes) -> float:
    samples = array.array('h')
    samples.frombytes(frame[: len(frame) // 2 * 2])
    if not samples:
        return 0.0
    total = sum((value / 32768.0) ** 2 for value in samples)
    return math.sqrt(total / len(samples))


class EnergyVAD:
    """Local silence gate - avoids paying ASR seconds for silent audio.

    The default is deliberately sensitive: laptop microphone arrays often sit
    around RMS 0.01 after down-mixing to mono, and gating them drops whole
    sentences. A longer hold-off keeps the tail of a sentence attached.
    """

    def __init__(self, threshold: float = 0.004, silence_frames: int = 25) -> None:
        self.threshold = max(0.0, threshold)
        self.silence_frames = max(0, silence_frames)
        self._silent = 0
        self.stats = {'frames': 0, 'sent': 0, 'gated': 0}

    def process(self, frame: bytes) -> bool:
        self.stats['frames'] += 1
        if rms(frame) >= self.threshold:
            self._silent = 0
            self.stats['sent'] += 1
            return True
        self._silent += 1
        if self._silent <= self.silence_frames:
            self.stats['sent'] += 1
            return True
        self.stats['gated'] += 1
        return False


def auto_gain(data: bytes, target_peak: int = 9000, max_gain: float = 4.0) -> bytes:
    """Lift quiet microphone input before it reaches ASR.

    Only called for frames the VAD already accepted, so background noise is not
    amplified. Laptop arrays frequently deliver peaks of 1000-3000 on a
    +/-32768 scale, which makes streaming ASR miss words.
    """
    usable = data[: len(data) // 2 * 2]
    if not usable:
        return data
    samples = array.array('h')
    samples.frombytes(usable)
    peak = max((abs(int(value)) for value in samples), default=0)
    if peak <= 0:
        return data
    gain = min(max_gain, target_peak / peak)
    if gain <= 1.05:
        return data
    boosted = array.array('h', (
        int(max(-32768, min(32767, int(value) * gain))) for value in samples
    ))
    return boosted.tobytes()


def mix_frames(parts: Iterable[bytes | None]) -> bytes:
    """Sample-wise sum of aligned 20 ms frames; ``None`` means a silent source."""
    arrays: list[array.array[int]] = []
    for frame in parts:
        if not frame:
            continue
        values = array.array('h')
        values.frombytes(frame[:FRAME_BYTES])
        arrays.append(values)
    out = array.array('h', [0]) * (FRAME_BYTES // 2)
    for values in arrays:
        for index, value in enumerate(values):
            if index >= len(out):
                break
            out[index] = int(max(-32768, min(32767, out[index] + int(value))))
    return out.tobytes()


def tone_frames(seconds: float, frequency: float = 220.0, frame_ms: int = FRAME_MS,
                active_ratio: float = 0.6) -> Iterator[bytes]:
    """Deterministic synthetic audio, used by the offline end-to-end smoke test."""
    sample_count = TARGET_RATE * frame_ms // 1000
    total_frames = max(1, int(seconds * 1000 / frame_ms))
    phase = 0.0
    for frame_index in range(total_frames):
        active = (frame_index % 10) / 10 < active_ratio
        chunk = array.array('h')
        for _ in range(sample_count):
            if active:
                chunk.append(int(12000 * math.sin(phase)))
                phase += 2 * math.pi * frequency / TARGET_RATE
            else:
                chunk.append(0)
        yield chunk.tobytes()


class FrameMailbox:
    """Bounded, thread-safe mailbox between a capture thread and the event loop."""

    def __init__(self, maxlen: int = 40) -> None:
        self._items: deque[bytes] = deque(maxlen=maxlen)

    def push(self, frame: bytes) -> None:
        self._items.append(frame)

    def pop(self) -> bytes | None:
        return self._items.popleft() if self._items else None
