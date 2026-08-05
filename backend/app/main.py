import asyncio
import logging
import time
from contextlib import suppress
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import CreateSessionRequest, CreateSessionResponse, SessionView, SubtitleSegment
from app.services.agents import QwenChatAgent, QwenRealtimeASRAgent, QwenTranslationAgent
from app.services.segmenter import StreamingSegmenter
from app.services.session_store import SessionStore

settings = get_settings()
sessions = SessionStore(settings.session_max_segments)
logger = logging.getLogger('uvicorn.error')

app = FastAPI(title='Real-time AI Subtitle Agent API', version='0.3.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r'chrome-extension://.*',
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health() -> dict[str, object]:
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
    }


@app.post('/api/sessions', response_model=CreateSessionResponse)
def create_session(payload: CreateSessionRequest) -> CreateSessionResponse:
    session = sessions.create(payload.video_url)
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
        segments=session.segments,
    )


@app.websocket('/ws/sessions/{session_id}')
async def stream_session(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    if not sessions.get(session_id):
        await websocket.send_json({'type': 'error', 'message': '会话不存在，请重新开始。'})
        await websocket.close(code=1008)
        return

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

    async def send_event(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def browser_messages() -> None:
        while True:
            message = await websocket.receive_json()
            message_type = message.get('type')
            if message_type == 'audio.append':
                audio = message.get('audio')
                if isinstance(audio, str) and audio:
                    await asr.send_audio(audio)
            elif message_type == 'chat.ask':
                request_id = str(message.get('request_id') or uuid4())
                question = str(message.get('question') or '').strip()
                selected_segment_id = str(message.get('selected_segment_id') or '')
                selected_text = str(message.get('selected_text') or '').strip()
                if question:
                    await chat_queue.put((request_id, question, selected_segment_id, selected_text))
            elif message_type == 'session.close':
                return

    async def emit_phrase(source_text: str) -> None:
        segment = SubtitleSegment(
            id=str(uuid4()),
            source_text=source_text,
            target_text='',
            timestamp=time.time(),
            status='translating',
        )
        sessions.add_segment(session_id, segment)
        await send_event({'type': 'transcript.segment', 'payload': segment.model_dump()})
        await translation_queue.put(segment)

    async def qwen_to_transcript() -> None:
        async for transcript in asr.transcript_events():
            result = segmenter.feed(
                transcript.text,
                is_final=transcript.status == 'final',
            )
            for phrase in result.phrases:
                await emit_phrase(phrase)

            await send_event({
                'type': 'transcript.live',
                'payload': {
                    'id': 'live',
                    'source_text': result.live_text,
                    'target_text': '',
                    'timestamp': time.time(),
                    'status': 'partial',
                },
            })

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
            except Exception:
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
                    'message': '本段中文暂时未能生成。',
                })
            finally:
                translation_queue.task_done()

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
                    transcript_context=sessions.context(session_id, limit=30),
                )
                await send_event({
                    'type': 'chat.answer',
                    'request_id': request_id,
                    'answer': answer,
                })
            except Exception:
                logger.exception('Qwen chat failed for session %s', session_id)
                await send_event({
                    'type': 'chat.error',
                    'request_id': request_id,
                    'message': 'AI 暂时无法回答，请稍后再试。',
                })
            finally:
                chat_queue.task_done()

    tasks: list[asyncio.Task[None]] = []
    try:
        await asr.connect()
        await send_event({
            'type': 'session.ready',
            'sample_rate': settings.qwen_asr_sample_rate,
            'model': settings.qwen_asr_model,
        })
        tasks = [
            asyncio.create_task(browser_messages()),
            asyncio.create_task(qwen_to_transcript()),
            asyncio.create_task(chat_worker()),
            *[
                asyncio.create_task(translation_worker(worker_number))
                for worker_number in range(1, max(1, settings.translation_workers) + 1)
            ],
        ]
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
