import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentationResult:
    phrases: list[str]
    live_text: str


class StreamingSegmenter:
    """Turn a growing ASR hypothesis into short, stable translation units."""

    def __init__(self, min_words: int, max_words: int, max_wait_seconds: float) -> None:
        self.min_words = max(1, min_words)
        self.max_words = max(self.min_words, max_words)
        self.max_wait_seconds = max(0.2, max_wait_seconds)
        self._committed_words = 0
        self._pending_since: float | None = None

    @staticmethod
    def _has_boundary(word: str) -> bool:
        return bool(re.search(r'[,.;:!?]$', word))

    def _next_cut(self, words: list[str], is_final: bool, now: float) -> int:
        if not words:
            return 0

        boundary = next((
            index + 1
            for index, word in enumerate(words[:self.max_words])
            if index + 1 >= self.min_words and self._has_boundary(word)
        ), 0)
        if boundary:
            return boundary
        if len(words) >= self.max_words:
            return self.max_words
        if is_final:
            return len(words)
        if (
            len(words) >= self.min_words
            and self._pending_since is not None
            and now - self._pending_since >= self.max_wait_seconds
        ):
            return len(words)
        return 0

    def feed(self, text: str, is_final: bool, now: float | None = None) -> SegmentationResult:
        current_time = time.monotonic() if now is None else now
        words = text.split()

        # Realtime ASR may revise its latest words. Already emitted phrases stay
        # immutable; only the uncommitted tail follows the newest hypothesis.
        start = min(self._committed_words, len(words))
        pending = words[start:]
        if pending and self._pending_since is None:
            self._pending_since = current_time

        phrases: list[str] = []
        while pending:
            cut = self._next_cut(pending, is_final, current_time)
            if not cut:
                break
            phrases.append(' '.join(pending[:cut]).strip())
            self._committed_words += cut
            pending = pending[cut:]
            self._pending_since = current_time if pending else None

        live_text = ' '.join(pending).strip()
        if is_final:
            self._committed_words = 0
            self._pending_since = None
        return SegmentationResult([phrase for phrase in phrases if phrase], live_text)
