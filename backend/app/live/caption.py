"""Caption state machine for the live (burned-in) subtitle path.

Unlike the YouTube side panel, a stream overlay cannot scroll back and cannot
be edited after it appears on air. So only final, translated whole lines are
allowed, with a short publish queue for recall, de-duplication, and a hard
two-line limit.
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

AI_LABEL_TEXT = 'AI 实时翻译 · English → 中文'


@dataclass
class LiveConfig:
    """Everything the streamer can change from the console."""

    source_microphone: bool = True
    # Cross-border streaming is mostly teammates / game audio coming out of the
    # speakers, so system loopback must be on by default too.
    source_system: bool = True
    publish_delay_ms: int = 0
    hold_ms: int = 3600
    ai_label: bool = True
    font_size: int = 34
    max_lines: int = 2
    dedupe_seconds: float = 4.0
    device_microphone: int | None = None
    device_loopback: int | None = None
    language_name: str = 'English → 中文'

    def update(self, payload: dict[str, Any]) -> None:
        for key, value in payload.items():
            if not hasattr(self, key):
                continue
            current = getattr(self, key)
            if isinstance(current, bool):
                setattr(self, key, bool(value))
            elif isinstance(current, int) and not isinstance(current, bool):
                try:
                    setattr(self, key, int(value))
                except (TypeError, ValueError):
                    continue
            elif isinstance(current, float):
                try:
                    setattr(self, key, float(value))
                except (TypeError, ValueError):
                    continue
            elif isinstance(current, str):
                setattr(self, key, str(value))
            else:
                setattr(self, key, value)
        self.max_lines = max(1, min(3, self.max_lines))
        self.publish_delay_ms = max(0, min(6000, self.publish_delay_ms))
        self.hold_ms = max(800, min(15000, self.hold_ms))

    def as_dict(self) -> dict[str, Any]:
        return {
            'source_microphone': self.source_microphone,
            'source_system': self.source_system,
            'publish_delay_ms': self.publish_delay_ms,
            'hold_ms': self.hold_ms,
            'ai_label': self.ai_label,
            'font_size': self.font_size,
            'max_lines': self.max_lines,
            'dedupe_seconds': self.dedupe_seconds,
            'device_microphone': self.device_microphone,
            'device_loopback': self.device_loopback,
            'language_name': self.language_name,
        }


@dataclass
class Caption:
    id: str
    text: str
    source_text: str
    created_at: float
    publish_at: float
    speaker: str = ''
    hold_ms: int = 3600

    def to_event(self, *, ai_label: bool, label_text: str) -> dict[str, Any]:
        return {
            'type': 'caption.show',
            'id': self.id,
            'text': self.text,
            'source_text': self.source_text,
            'speaker': self.speaker,
            'hold_ms': self.hold_ms,
            'ai_label': ai_label,
            'ai_label_text': label_text,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'text': self.text,
            'source_text': self.source_text,
            'created_at': self.created_at,
            'speaker': self.speaker,
        }


class CaptionState:
    def __init__(self, config: LiveConfig | None = None) -> None:
        self.config = config or LiveConfig()
        self.pending: dict[str, Caption] = {}
        self.lines: deque[Caption] = deque(maxlen=self.config.max_lines)
        self.records: list[dict[str, Any]] = []
        self.hidden = False
        self._last_text = ''
        self._last_at = 0.0
        self._latencies: deque[float] = deque(maxlen=200)
        self.stats: dict[str, int] = {
            'submitted': 0, 'published': 0, 'skipped': 0, 'recalled': 0,
        }

    def submit(self, segment: dict[str, Any], *, now: float | None = None) -> Caption | None:
        """Accept a ``transcript.translation`` payload. Only final lines pass."""
        now = time.time() if now is None else now
        if str(segment.get('status') or 'final') != 'final':
            self.stats['skipped'] += 1
            return None
        text = str(segment.get('target_text') or '').strip()
        source_text = str(segment.get('source_text') or '').strip()
        if not text or not source_text or text == source_text:
            self.stats['skipped'] += 1
            return None
        if text == self._last_text and now - self._last_at < self.config.dedupe_seconds:
            self.stats['skipped'] += 1
            return None

        timestamp = float(segment.get('timestamp') or now)
        latency = max(0.0, now - timestamp)
        self._latencies.append(latency)

        caption = Caption(
            id=str(segment.get('id') or uuid.uuid4().hex),
            text=text,
            source_text=source_text,
            created_at=timestamp,
            publish_at=now + self.config.publish_delay_ms / 1000.0,
            speaker=str(segment.get('speaker') or ''),
            hold_ms=self.config.hold_ms,
        )
        self.pending[caption.id] = caption
        self.records.append(caption.as_record())
        self.stats['submitted'] += 1
        return caption

    def flush(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Publish due captions. Returns caption.show events (empty when hidden)."""
        now = time.time() if now is None else now
        events: list[dict[str, Any]] = []
        due = [cid for cid, cap in self.pending.items() if cap.publish_at <= now]
        for cid in due:
            caption = self.pending.pop(cid, None)
            if caption is None:
                continue
            if self.hidden:
                continue
            self.lines.append(caption)
            self._last_text, self._last_at = caption.text, now
            self.stats['published'] += 1
            events.append(caption.to_event(
                ai_label=self.config.ai_label,
                label_text=f'AI 实时翻译 · {self.config.language_name}',
            ))
        return events

    def recall(self, caption_id: str | None = None) -> list[dict[str, Any]]:
        """Pull a line before / after it goes on air. Returns hide events."""
        if caption_id is None:
            caption_id = next(reversed(self.pending), None) if self.pending else (
                self.lines[-1].id if self.lines else None
            )
        if not caption_id:
            return []
        self.pending.pop(caption_id, None)
        on_air = [line for line in self.lines if line.id == caption_id]
        if not on_air:
            return []
        self.lines = deque(
            (line for line in self.lines if line.id != caption_id),
            maxlen=self.config.max_lines,
        )
        self.stats['recalled'] += 1
        return [{'type': 'caption.hide', 'id': caption_id}]

    def hide_all(self) -> dict[str, Any]:
        self.hidden = True
        self.pending.clear()
        self.lines.clear()
        return {'type': 'caption.clear'}

    def clear_all(self) -> dict[str, Any]:
        self.hidden = False
        self.pending.clear()
        self.lines.clear()
        return {'type': 'caption.clear'}

    def resume(self) -> None:
        self.hidden = False

    def metrics(self) -> dict[str, Any]:
        values = sorted(self._latencies)
        percentile = lambda ratio: round(values[min(len(values) - 1, int(len(values) * ratio))] * 1000) if values else 0
        return {
            'p50_ms': percentile(0.50),
            'p95_ms': percentile(0.95),
            'samples': len(values),
            **self.stats,
        }

    def srt(self) -> str:
        def clock(value: float) -> str:
            millis = int(max(0.0, value) * 1000)
            hours, millis = divmod(millis, 3_600_000)
            minutes, millis = divmod(millis, 60_000)
            seconds, millis = divmod(millis, 1000)
            return f'{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}'

        if not self.records:
            return ''
        origin = float(self.records[0]['created_at'])
        blocks = []
        for index, record in enumerate(self.records, 1):
            start = float(record['created_at']) - origin
            blocks.append(
                f'{index}\n{clock(start)} --> {clock(start + self.config.hold_ms / 1000)}\n'
                f'{record["text"]}\n'
            )
        return '\n'.join(blocks)
