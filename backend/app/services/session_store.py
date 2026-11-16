import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal, Optional
from uuid import uuid4

from app.models import (
    SessionHistoryDetail,
    SessionHistoryItem,
    SessionQuestion,
    SessionSummary,
    SubtitleSegment,
)


@dataclass
class Session:
    session_id: str
    video_url: str
    video_title: str = ''
    input_mode: Literal['audio', 'captions'] = 'audio'
    subtitle_source: str = ''
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    segments: list[SubtitleSegment] = field(default_factory=list)
    summaries: list[SessionSummary] = field(default_factory=list)


def format_video_time(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


def retrieval_tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r'[a-z0-9][a-z0-9_-]+', lowered))
    chinese_runs = re.findall(r'[\u4e00-\u9fff]+', lowered)
    for run in chinese_runs:
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


class SessionStore:
    def __init__(self, max_segments: int = 500, database_path: Path | str | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_segments = max_segments
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None
        if database_path:
            path = Path(database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._initialize_database()

    def _initialize_database(self) -> None:
        assert self._connection is not None
        with self._connection:
            self._connection.executescript(
                '''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    video_url TEXT NOT NULL,
                    video_title TEXT NOT NULL DEFAULT '',
                    input_mode TEXT NOT NULL DEFAULT 'audio',
                    subtitle_source TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    target_text TEXT NOT NULL DEFAULT '',
                    timestamp REAL NOT NULL,
                    start_ms INTEGER NOT NULL DEFAULT 0,
                    end_ms INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'qwen-asr',
                    status TEXT NOT NULL DEFAULT 'final',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_segments_session_time
                    ON segments(session_id, start_ms, timestamp);
                CREATE TABLE IF NOT EXISTS summaries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_summaries_session_time
                    ON summaries(session_id, start_ms);
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    selected_text TEXT NOT NULL DEFAULT '',
                    answer TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                '''
            )

    def create(
        self,
        video_url: str,
        video_title: str = '',
        input_mode: Literal['audio', 'captions'] = 'audio',
        subtitle_source: str = '',
    ) -> Session:
        session = Session(
            session_id=str(uuid4()),
            video_url=video_url,
            video_title=video_title,
            input_mode=input_mode,
            subtitle_source=subtitle_source,
        )
        with self._lock:
            self._sessions[session.session_id] = session
            if self._connection:
                with self._connection:
                    self._connection.execute(
                        '''INSERT INTO sessions
                           (session_id, video_url, video_title, input_mode, subtitle_source, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        (
                            session.session_id,
                            session.video_url,
                            session.video_title,
                            session.input_mode,
                            session.subtitle_source,
                            session.created_at.isoformat(),
                        ),
                    )
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            if self._connection:
                with self._connection:
                    self._connection.execute(
                        'UPDATE sessions SET ended_at = ? WHERE session_id = ?',
                        (datetime.now(timezone.utc).isoformat(), session_id),
                    )

    def add_segment(self, session_id: str, segment: SubtitleSegment) -> None:
        with self._lock:
            session = self._sessions[session_id]
            existing_index = next((
                index for index, existing in enumerate(session.segments) if existing.id == segment.id
            ), None)
            if existing_index is None:
                session.segments.append(segment)
            else:
                session.segments[existing_index] = segment
            session.segments = session.segments[-self._max_segments:]
            if self._connection:
                with self._connection:
                    self._connection.execute(
                        '''INSERT INTO segments
                           (id, session_id, source_text, target_text, timestamp, start_ms, end_ms, source, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET
                             source_text = excluded.source_text,
                             target_text = excluded.target_text,
                             timestamp = excluded.timestamp,
                             start_ms = excluded.start_ms,
                             end_ms = excluded.end_ms,
                             source = excluded.source,
                             status = excluded.status''',
                        (
                            segment.id,
                            session_id,
                            segment.source_text,
                            segment.target_text,
                            segment.timestamp,
                            segment.start_ms,
                            segment.end_ms,
                            segment.source,
                            segment.status or 'final',
                        ),
                    )

    def get_segment(self, session_id: str, segment_id: str) -> Optional[SubtitleSegment]:
        session = self._sessions[session_id]
        return next((segment for segment in session.segments if segment.id == segment_id), None)

    def add_summary(self, session_id: str, start_ms: int, end_ms: int, content: str) -> SessionSummary:
        summary = SessionSummary(
            id=str(uuid4()),
            session_id=session_id,
            start_ms=start_ms,
            end_ms=end_ms,
            content=content,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._sessions[session_id].summaries.append(summary)
            if self._connection:
                with self._connection:
                    self._connection.execute(
                        '''INSERT INTO summaries (id, session_id, start_ms, end_ms, content, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        (
                            summary.id,
                            session_id,
                            summary.start_ms,
                            summary.end_ms,
                            summary.content,
                            summary.created_at.isoformat(),
                        ),
                    )
        return summary

    def add_question(self, session_id: str, question_id: str, question: str, selected_text: str, answer: str) -> None:
        if not self._connection:
            return
        with self._lock, self._connection:
            self._connection.execute(
                '''INSERT OR REPLACE INTO questions
                   (id, session_id, question, selected_text, answer, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (question_id, session_id, question, selected_text, answer, datetime.now(timezone.utc).isoformat()),
            )

    def context(self, session_id: str, limit: int = 12) -> str:
        session = self._sessions[session_id]
        recent = session.segments[-limit:]
        return '\n'.join(self._format_segment(segment) for segment in recent if segment.source_text)

    def question_context(
        self,
        session_id: str,
        question: str,
        selected_text: str = '',
        recent_limit: int = 18,
        relevant_limit: int = 10,
    ) -> str:
        session = self._sessions[session_id]
        query_tokens = retrieval_tokens(f'{question} {selected_text}')
        scored: list[tuple[int, int, SubtitleSegment]] = []
        for index, segment in enumerate(session.segments):
            segment_tokens = retrieval_tokens(f'{segment.source_text} {segment.target_text}')
            score = len(query_tokens.intersection(segment_tokens))
            if selected_text and selected_text.lower() in segment.source_text.lower():
                score += 12
            if score:
                scored.append((score, index, segment))
        relevant = [item[2] for item in sorted(scored, key=lambda item: (-item[0], item[1]))[:relevant_limit]]
        recent = session.segments[-recent_limit:]
        selected_ids = {segment.id for segment in relevant}
        evidence = relevant + [segment for segment in recent if segment.id not in selected_ids]
        evidence.sort(key=lambda segment: (segment.start_ms, segment.timestamp))

        summary_text = '\n'.join(
            f'[{format_video_time(summary.start_ms)}-{format_video_time(summary.end_ms)}] {summary.content}'
            for summary in session.summaries[-24:]
        )
        evidence_text = '\n'.join(self._format_segment(segment) for segment in evidence if segment.source_text)
        parts = []
        if summary_text:
            parts.append(f'阶段摘要：\n{summary_text}')
        if evidence_text:
            parts.append(f'字幕证据：\n{evidence_text}')
        return '\n\n'.join(parts)

    def list_history(self, limit: int = 20) -> list[SessionHistoryItem]:
        if not self._connection:
            return []
        safe_limit = max(1, min(100, limit))
        with self._lock:
            rows = self._connection.execute(
                '''SELECT s.session_id, s.video_url, s.video_title, s.created_at, s.ended_at,
                          s.input_mode, s.subtitle_source,
                          COUNT(DISTINCT g.id) AS segment_count,
                          COUNT(DISTINCT q.id) AS question_count,
                          COALESCE(MAX(g.end_ms), 0) AS last_position_ms
                   FROM sessions s
                   LEFT JOIN segments g ON g.session_id = s.session_id
                   LEFT JOIN questions q ON q.session_id = s.session_id
                   GROUP BY s.session_id
                   ORDER BY s.created_at DESC
                   LIMIT ?''',
                (safe_limit,),
            ).fetchall()
        return [self._history_item(row) for row in rows]

    def get_history(self, session_id: str) -> Optional[SessionHistoryDetail]:
        if not self._connection:
            return None
        with self._lock:
            row = self._connection.execute(
                '''SELECT s.session_id, s.video_url, s.video_title, s.created_at, s.ended_at,
                          s.input_mode, s.subtitle_source,
                          COUNT(DISTINCT g.id) AS segment_count,
                          COUNT(DISTINCT q.id) AS question_count,
                          COALESCE(MAX(g.end_ms), 0) AS last_position_ms
                   FROM sessions s
                   LEFT JOIN segments g ON g.session_id = s.session_id
                   LEFT JOIN questions q ON q.session_id = s.session_id
                   WHERE s.session_id = ?
                   GROUP BY s.session_id''',
                (session_id,),
            ).fetchone()
            if not row:
                return None
            segment_rows = self._connection.execute(
                '''SELECT id, source_text, target_text, timestamp, start_ms, end_ms, source, status
                   FROM segments WHERE session_id = ? ORDER BY start_ms, timestamp''',
                (session_id,),
            ).fetchall()
            summary_rows = self._connection.execute(
                '''SELECT id, session_id, start_ms, end_ms, content, created_at
                   FROM summaries WHERE session_id = ? ORDER BY start_ms''',
                (session_id,),
            ).fetchall()
            question_rows = self._connection.execute(
                '''SELECT id, question, selected_text, answer, created_at
                   FROM questions WHERE session_id = ? ORDER BY created_at''',
                (session_id,),
            ).fetchall()

        item = self._history_item(row)
        return SessionHistoryDetail(
            **item.model_dump(),
            segments=[SubtitleSegment(**dict(segment)) for segment in segment_rows],
            summaries=[SessionSummary(**dict(summary)) for summary in summary_rows],
            questions=[SessionQuestion(**dict(question)) for question in question_rows],
        )

    @staticmethod
    def _history_item(row: sqlite3.Row) -> SessionHistoryItem:
        values = dict(row)
        values['created_at'] = datetime.fromisoformat(values['created_at'])
        values['ended_at'] = datetime.fromisoformat(values['ended_at']) if values['ended_at'] else None
        return SessionHistoryItem(**values)

    @staticmethod
    def _format_segment(segment: SubtitleSegment) -> str:
        timestamp = format_video_time(segment.start_ms)
        return f'[{timestamp}] EN: {segment.source_text}\n[{timestamp}] ZH: {segment.target_text}'

    def close(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None
