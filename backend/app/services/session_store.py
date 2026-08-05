from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.models import SubtitleSegment


@dataclass
class Session:
    session_id: str
    video_url: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    segments: list[SubtitleSegment] = field(default_factory=list)


class SessionStore:
    def __init__(self, max_segments: int = 500) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_segments = max_segments

    def create(self, video_url: str) -> Session:
        session = Session(session_id=str(uuid4()), video_url=video_url)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def add_segment(self, session_id: str, segment: SubtitleSegment) -> None:
        session = self._sessions[session_id]
        existing_index = next((
            index for index, existing in enumerate(session.segments) if existing.id == segment.id
        ), None)
        if existing_index is None:
            session.segments.append(segment)
        else:
            session.segments[existing_index] = segment
        session.segments = session.segments[-self._max_segments:]

    def get_segment(self, session_id: str, segment_id: str) -> Optional[SubtitleSegment]:
        session = self._sessions[session_id]
        return next((segment for segment in session.segments if segment.id == segment_id), None)

    def context(self, session_id: str, limit: int = 12) -> str:
        session = self._sessions[session_id]
        recent = session.segments[-limit:]
        return '\n'.join(
            f'EN: {segment.source_text}\nZH: {segment.target_text}'
            for segment in recent
            if segment.source_text
        )
