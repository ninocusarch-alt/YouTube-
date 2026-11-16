import asyncio
import atexit
import logging
import time
from contextlib import suppress
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionHistoryDetail,
    SessionHistoryItem,
    SessionView,
    SubtitleSegment,
)
from app.services.agents import (
    QwenChatAgent,
    QwenRealtimeASRAgent,
    QwenTranslationAgent,
    user_facing_qwen_error,
)
from app.services.segmenter import StreamingSegmenter
from app.services.session_store import SessionStore

startup_settings = get_settings()
sessions = SessionStore(startup_settings.session_max_segments, startup_settings.database_path)
atexit.register(sessions.close)
logger = logging.getLogger('uvicorn.error')

app = FastAPI(title='Real-time AI Subtitle Agent API', version='0.4.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=startup_settings.cors_origins,
    allow_origin_regex=r'chrome-extension://.*',
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        'ok': True,
        'asr_provider': 'qwen-realtime',
        'asr_configured': bool(settings.dashscope_api_key and settings.qwen_asr_model),
        'asr_model': settings.qwen_asr_model,
        'translation_provider': 'qwen',
        'translation_configured': bool(settings.dashscope_api_key and settings.qwen_translation_model),
        'translation_model': settings.qwen_translation_model,
        'chat_model': settings.qwen_chat_model,
        'translation_workers': settings.translation_workers,
        'segment_max_wait_seconds': settings.segment_max_wait_seconds,
        'history_persistence': True,
    }


@app.post('/api/sessions', response_model=CreateSessionResponse)
def create_session(payload: CreateSessionRequest) -> CreateSessionResponse:
    session = sessions.create(
        payload.video_url,
        video_title=payload.video_title,
        input_mode=payload.input_mode,
        subtitle_source=payload.subtitle_source,
    )
    return CreateSessionResponse(session_id=session.session_id)


@app.get('/api/sessions/{session_id}', response_model=SessionView)
def get_session(session_id: str) -> SessionView:
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    return SessionView(
        session_id=session.session_id,
        video_url=session.video_url,
        created_at=session.created_at,
        video_title=session.video_title,
        input_mode=session.input_mode,
        subtitle_source=session.subtitle_source,
        segments=session.segments,
        summaries=session.summaries,
    )


@app.get('/api/history', response_model=list[SessionHistoryItem])
def list_history(limit: int = 20) -> list[SessionHistoryItem]:
    return sessions.list_history(limit)


@app.get('/api/history/{session_id}', response_model=SessionHistoryDetail)
def get_history(session_id: str) -> SessionHistoryDetail:
    history = sessions.get_history(session_id)
    if not history:
        raise HTTPException(status_code=404, detail='History not found')
    return history


@app.websocket('/ws/sessions/{session_id}')
async def stream_session(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    session = sessions.get(session_id)
    if not session:
        await websocket.send_json({'type': 'error', 'message': '会话不存在，请重新开始。'})
        await websocket.close(code=1008)
        return

    settings = get_settings()
    asr = QwenRealtimeASRAgent(settings)
    translator = QwenTranslationAgent(settings)
    chat_agent = QwenChatAgent(settings)
    segmenter = StreamingSegmenter(
        min_words=settings.segment_min_words,
        max_words=settings.segment_max_words,
        max_wait_seconds=settings.segment_max_wait_seconds,
    )
    send_lock = asyncio.Lock()
    translation_queue: asyncio.Queue[SubtitleSegment] = asyncio.Queue()
    chat_queue: asyncio.Queue[tuple[str, str, str, str]] = asyncio.Queue()
    summary_queue: asyncio.Queue[list[SubtitleSegment]] = asyncio.Queue()
    summary_lock = asyncio.Lock()
    latest_playback_ms = 0
    last_asr_segment_end_ms = 0
    summarized_segment_count = 0

    async def send_event(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def browser_messages() -> None:
        nonlocal latest_playback_ms
        while True:
            message = await websocket.receive_json()
            message_type = message.get('type')
            if message_type == 'audio.append':
                audio = message.get('audio')
                if isinstance(audio, str) and audio:
                    await asr.send_audio(audio)
            elif message_type == 'playback.position':
                latest_playback_ms = max(0, int(float(message.get('seconds') or 0) * 1000))
            elif message_type == 'caption.segment':
                source_text = str(message.get('text') or '').strip()
                if source_text:
                    await emit_phrase(
                        source_text,
                        segment_id=str(message.get('id') or uuid4()),
                        start_ms=max(0, int(message.get('start_ms') or 0)),
                        end_ms=max(0, int(message.get('end_ms') or 0)),
                        source=str(message.get('source') or 'youtube-caption'),
                    )
            elif message_type == 'chat.ask':
                request_id = str(message.get('request_id') or uuid4())
                question = str(message.get('question') or '').strip()
                selected_segment_id = str(message.get('selected_segment_id') or '')
                selected_text = str(message.get('selected_text') or '').strip()
                if question:
                    await chat_queue.put((request_id, question, selected_segment_id, selected_text))
            elif message_type == 'session.close':
                return

    async def emit_phrase(
        source_text: str,
        segment_id: str | None = None,
        start_ms: int = 0,
        end_ms: int = 0,
        source: str = 'qwen-asr',
    ) -> None:
        segment = SubtitleSegment(
            id=segment_id or str(uuid4()),
            source_text=source_text,
            target_text='',
            timestamp=time.time(),
            start_ms=start_ms,
            end_ms=max(start_ms, end_ms),
            source=source,
            status='translating',
        )
        sessions.add_segment(session_id, segment)
        await send_event({'type': 'transcript.segment', 'payload': segment.model_dump()})
        await translation_queue.put(segment)

    async def qwen_to_transcript() -> None:
        nonlocal last_asr_segment_end_ms
        async for transcript in asr.transcript_events():
            result = segmenter.feed(
                transcript.text,
                is_final=transcript.status == 'final',
            )
            for phrase in result.phrases:
                estimated_duration_ms = max(900, min(8000, len(phrase.split()) * 360))
                end_ms = latest_playback_ms
                start_ms = max(last_asr_segment_end_ms, end_ms - estimated_duration_ms)
                await emit_phrase(phrase, start_ms=start_ms, end_ms=end_ms, source='qwen-asr')
                last_asr_segment_end_ms = max(last_asr_segment_end_ms, end_ms)

            await send_event({
                'type': 'transcript.live',
                'payload': {
                    'id': 'live',
                    'source_text': result.live_text,
                    'target_text': '',
                    'timestamp': time.time(),
                    'start_ms': latest_playback_ms,
                    'end_ms': latest_playback_ms,
                    'source': 'qwen-asr',
                    'status': 'partial',
                },
            })

    async def maybe_queue_summary() -> None:
        nonlocal summarized_segment_count
        async with summary_lock:
            finalized = [segment for segment in session.segments if segment.status == 'final']
            batch_size = max(5, settings.summary_batch_segments)
            while len(finalized) - summarized_segment_count >= batch_size:
                batch = finalized[summarized_segment_count:summarized_segment_count + batch_size]
                summarized_segment_count += batch_size
                await summary_queue.put(batch)

    async def translation_worker(worker_number: int) -> None:
        while True:
            segment = await translation_queue.get()
            try:
                translated = await translator.translate(segment.source_text, sessions.context(session_id))
                final_segment = segment.model_copy(update={
                    'target_text': translated,
                    'status': 'final',
                })
                sessions.add_segment(session_id, final_segment)
                await send_event({'type': 'transcript.translation', 'payload': final_segment.model_dump()})
                await maybe_queue_summary()
            except Exception as exc:
                logger.exception(
                    'Qwen translation worker %s failed for session %s',
                    worker_number,
                    session_id,
                )
                failed_segment = segment.model_copy(update={'status': 'error'})
                sessions.add_segment(session_id, failed_segment)
                await send_event({
                    'type': 'transcript.translation_error',
                    'payload': failed_segment.model_dump(),
                    'message': user_facing_qwen_error(exc, '本段中文暂时未能生成。'),
                })
            finally:
                translation_queue.task_done()

    async def summary_worker() -> None:
        while True:
            batch = await summary_queue.get()
            try:
                transcript_context = '\n'.join(
                    f'[{segment.start_ms // 60000:02d}:{(segment.start_ms // 1000) % 60:02d}] '
                    f'EN: {segment.source_text}\nZH: {segment.target_text}'
                    for segment in batch
                )
                content = await chat_agent.summarize(transcript_context)
                if content:
                    summary = sessions.add_summary(
                        session_id,
                        min(segment.start_ms for segment in batch),
                        max(segment.end_ms for segment in batch),
                        content,
                    )
                    await send_event({'type': 'session.summary', 'payload': summary.model_dump(mode='json')})
            except Exception:
                logger.exception('Qwen summary failed for session %s', session_id)
            finally:
                summary_queue.task_done()

    async def chat_worker() -> None:
        while True:
            request_id, question, selected_segment_id, selected_text = await chat_queue.get()
            try:
                selected_segment = (
                    sessions.get_segment(session_id, selected_segment_id)
                    if selected_segment_id
                    else None
                )
                quote = selected_segment.source_text if selected_segment else selected_text
                answer = await chat_agent.ask(
                    question=question,
                    selected_text=quote,
                    transcript_context=sessions.question_context(
                        session_id,
                        question=question,
                        selected_text=quote,
                    ),
                )
                sessions.add_question(session_id, request_id, question, quote, answer)
                await send_event({
                    'type': 'chat.answer',
                    'request_id': request_id,
                    'answer': answer,
                })
            except Exception as exc:
                logger.exception('Qwen chat failed for session %s', session_id)
                await send_event({
                    'type': 'chat.error',
                    'request_id': request_id,
                    'message': user_facing_qwen_error(exc, 'AI 暂时无法回答，请稍后再试。'),
                })
            finally:
                chat_queue.task_done()

    tasks: list[asyncio.Task[None]] = []
    try:
        if session.input_mode == 'audio':
            await asr.connect()
        await send_event({
            'type': 'session.ready',
            'input_mode': session.input_mode,
            'subtitle_source': session.subtitle_source,
            'sample_rate': settings.qwen_asr_sample_rate if session.input_mode == 'audio' else None,
            'model': settings.qwen_asr_model if session.input_mode == 'audio' else None,
        })
        tasks = [
            asyncio.create_task(browser_messages()),
            asyncio.create_task(chat_worker()),
            asyncio.create_task(summary_worker()),
            *[
                asyncio.create_task(translation_worker(worker_number))
                for worker_number in range(1, max(1, settings.translation_workers) + 1)
            ],
        ]
        if session.input_mode == 'audio':
            tasks.append(asyncio.create_task(qwen_to_transcript()))
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled():
                task.result()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception('Realtime video assistant failed for session %s', session_id)
        with suppress(Exception):
            await send_event({'type': 'error', 'message': str(exc)})
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asr.close()
        await translator.close()
        await chat_agent.close()
        with suppress(Exception):
            await websocket.close()


@app.delete('/api/sessions/{session_id}', status_code=204)
def delete_session(session_id: str) -> None:
    sessions.delete(session_id)
