from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    video_url: str = ''
    video_title: str = ''
    input_mode: Literal['audio', 'captions'] = 'audio'
    subtitle_source: str = ''


class CreateSessionResponse(BaseModel):
    session_id: str


class SubtitleSegment(BaseModel):
    id: str
    source_text: str
    target_text: str
    timestamp: float
    start_ms: int = 0
    end_ms: int = 0
    source: str = 'qwen-asr'
    status: Optional[Literal['partial', 'translating', 'final', 'error']] = 'final'


class SessionSummary(BaseModel):
    id: str
    session_id: str
    start_ms: int
    end_ms: int
    content: str
    created_at: datetime


class SessionView(BaseModel):
    session_id: str
    video_url: str
    created_at: datetime
    video_title: str = ''
    input_mode: Literal['audio', 'captions'] = 'audio'
    subtitle_source: str = ''
    segments: list[SubtitleSegment] = Field(default_factory=list)
    summaries: list[SessionSummary] = Field(default_factory=list)


class SessionHistoryItem(BaseModel):
    session_id: str
    video_url: str
    video_title: str = ''
    created_at: datetime
    ended_at: Optional[datetime] = None
    input_mode: Literal['audio', 'captions'] = 'audio'
    subtitle_source: str = ''
    segment_count: int = 0
    question_count: int = 0
    last_position_ms: int = 0


class SessionQuestion(BaseModel):
    id: str
    question: str
    selected_text: str = ''
    answer: str = ''
    created_at: datetime


class SessionHistoryDetail(SessionHistoryItem):
    segments: list[SubtitleSegment] = Field(default_factory=list)
    summaries: list[SessionSummary] = Field(default_factory=list)
    questions: list[SessionQuestion] = Field(default_factory=list)
