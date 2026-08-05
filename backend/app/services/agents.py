import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import websockets

from app.config import Settings


@dataclass(frozen=True)
class ASRTranscriptEvent:
    status: Literal['partial', 'final']
    text: str
    is_delta: bool = False


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def parse_qwen_asr_event(data: dict[str, Any]) -> ASRTranscriptEvent | None:
    """Normalize Qwen Realtime events and common DashScope result variants."""
    event_type = str(data.get('type') or data.get('event') or '').lower()

    if event_type in {
        'conversation.item.input_audio_transcription.delta',
        'input_audio_transcription.delta',
        'transcription.delta',
    }:
        raw_text = data.get('delta') or data.get('text') or data.get('transcript')
        text = raw_text if isinstance(raw_text, str) else ''
        return ASRTranscriptEvent('partial', text, is_delta=True) if text else None

    if event_type in {
        'conversation.item.input_audio_transcription.completed',
        'input_audio_transcription.completed',
        'transcription.completed',
        'transcription.done',
    }:
        text = _first_text(data, 'transcript', 'text')
        return ASRTranscriptEvent('final', text) if text else None

    output = data.get('output')
    if isinstance(output, dict):
        sentence = output.get('sentence')
        if isinstance(sentence, dict):
            text = _first_text(sentence, 'text', 'transcript')
            if text:
                ended = bool(sentence.get('sentence_end') or sentence.get('end_time') is not None)
                return ASRTranscriptEvent('final' if ended else 'partial', text)

        text = _first_text(output, 'text', 'transcript')
        if text:
            ended = bool(output.get('is_final') or output.get('sentence_end'))
            return ASRTranscriptEvent('final' if ended else 'partial', text)

    result = data.get('result')
    if isinstance(result, dict):
        text = _first_text(result, 'text', 'transcript')
        if text:
            ended = bool(result.get('is_final') or result.get('sentence_end'))
            return ASRTranscriptEvent('final' if ended else 'partial', text)

    return None


class QwenRealtimeASRAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.websocket: Any = None
        self._partial_text = ''

    @property
    def available(self) -> bool:
        return bool(self.settings.dashscope_api_key and self.settings.qwen_asr_model)

    def _connection_url(self) -> str:
        parts = urlsplit(self.settings.qwen_asr_ws_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.setdefault('model', self.settings.qwen_asr_model)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    async def connect(self) -> None:
        if not self.settings.dashscope_api_key:
            raise RuntimeError('后端未配置 DASHSCOPE_API_KEY。')

        self.websocket = await websockets.connect(
            self._connection_url(),
            additional_headers={
                'Authorization': f'Bearer {self.settings.dashscope_api_key}',
                'OpenAI-Beta': 'realtime=v1',
            },
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            max_size=4 * 1024 * 1024,
        )
        await self.websocket.send(json.dumps({
            'type': 'session.update',
            'session': {
                'input_audio_format': 'pcm',
                'sample_rate': self.settings.qwen_asr_sample_rate,
                'input_audio_transcription': {
                    'model': self.settings.qwen_asr_model,
                    'language': self.settings.qwen_asr_language,
                },
                'turn_detection': {
                    'type': 'server_vad',
                    'silence_duration_ms': self.settings.qwen_vad_silence_ms,
                },
            },
        }))

    async def send_audio(self, base64_audio: str) -> None:
        if not self.websocket:
            raise RuntimeError('千问语音识别连接尚未建立。')
        await self.websocket.send(json.dumps({
            'type': 'input_audio_buffer.append',
            'audio': base64_audio,
        }))

    async def transcript_events(self) -> AsyncIterator[ASRTranscriptEvent]:
        if not self.websocket:
            return
        async for raw_message in self.websocket:
            data = json.loads(raw_message)
            header = data.get('header') if isinstance(data.get('header'), dict) else {}
            if data.get('type') == 'error' or header.get('event') == 'task-failed':
                error = data.get('error') or data.get('payload') or data
                raise RuntimeError(f'千问语音识别返回错误：{error}')

            event = parse_qwen_asr_event(data)
            if not event:
                continue

            if event.status == 'partial':
                self._partial_text = self._partial_text + event.text if event.is_delta else event.text
                text = self._partial_text.strip()
                if text:
                    yield ASRTranscriptEvent('partial', text)
                continue

            final_text = event.text.strip() or self._partial_text.strip()
            self._partial_text = ''
            if final_text:
                yield ASRTranscriptEvent('final', final_text)

    async def close(self) -> None:
        if self.websocket:
            await self.websocket.close()
            self.websocket = None


class QwenTranslationAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.qwen_translation_base_url.rstrip('/'),
            headers={
                'Authorization': f'Bearer {settings.dashscope_api_key}',
                'Content-Type': 'application/json',
            },
            timeout=settings.qwen_translation_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(self.settings.dashscope_api_key and self.settings.qwen_translation_model)

    async def translate(self, source_text: str, context: str) -> str:
        if not self.available:
            raise RuntimeError('后端未配置 DASHSCOPE_API_KEY 或 QWEN_TRANSLATION_MODEL。')

        response = await self.client.post(
            '/chat/completions',
            json={
                'model': self.settings.qwen_translation_model,
                'messages': [
                    {
                        'role': 'system',
                        'content': (
                            '你是专业的实时字幕翻译 Agent。把英文口语翻译成简洁、自然的简体中文；'
                            '结合上下文保持人名、数字、代码和专业术语一致；控制在一到两行字幕长度。'
                            '只输出中文翻译，不要解释、引号或说话人标签。'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': json.dumps(
                            {'previous_subtitles': context, 'current_english': source_text},
                            ensure_ascii=False,
                        ),
                    },
                ],
                'temperature': 0.1,
                'max_tokens': 200,
                'enable_thinking': False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return (data['choices'][0]['message'].get('content') or '').strip()

    async def close(self) -> None:
        await self.client.aclose()


class QwenChatAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.qwen_translation_base_url.rstrip('/'),
            headers={
                'Authorization': f'Bearer {settings.dashscope_api_key}',
                'Content-Type': 'application/json',
            },
            timeout=settings.qwen_translation_timeout_seconds,
        )

    @property
    def available(self) -> bool:
        return bool(self.settings.dashscope_api_key and self.settings.qwen_chat_model)

    async def ask(self, question: str, selected_text: str, transcript_context: str) -> str:
        if not self.available:
            raise RuntimeError('后端未配置 DASHSCOPE_API_KEY 或 QWEN_CHAT_MODEL。')

        response = await self.client.post(
            '/chat/completions',
            json={
                'model': self.settings.qwen_chat_model,
                'messages': [
                    {
                        'role': 'system',
                        'content': (
                            '你是 YouTube 英语视频学习助手。根据视频转录上下文，用清晰简洁的中文回答。'
                            '如果用户选中了英文句子，应结合上下文解释含义、语法、词汇或专业术语。'
                            '不要虚构视频中没有的信息；信息不足时明确说明。'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': json.dumps({
                            'video_transcript': transcript_context,
                            'selected_english': selected_text,
                            'question': question,
                        }, ensure_ascii=False),
                    },
                ],
                'temperature': 0.3,
                'max_tokens': 700,
                'enable_thinking': False,
            },
        )
        response.raise_for_status()
        data = response.json()
        return (data['choices'][0]['message'].get('content') or '').strip()

    async def close(self) -> None:
        await self.client.aclose()
