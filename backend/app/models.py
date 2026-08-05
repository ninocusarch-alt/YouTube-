from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    video_url: str = ''


class CreateSessionResponse(BaseModel):
    session_id: str


class SubtitleSegment(BaseModel):
    id: str
    source_text: str
    target_text: str
    timestamp: float
    status: Optional[Literal['partial', 'translating', 'final', 'error']] = 'final'


class SessionView(BaseModel):
    session_id: str
    video_url: str
    created_at: datetime
    segments: list[SubtitleSegment] = Field(default_factory=list)
