import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

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

    # Qwen-ASR-Realtime / Qwen-Audio-3.1-ASR-Flash-Streaming 的实时预览事件，
    # text 是已确认前缀、stash 是可能变化的草稿，两者拼接才是完整预览。
    if event_type in {
        'conversation.item.input_audio_transcription.text',
        'input_audio_transcription.text',
    }:
        confirmed = data.get('text') if isinstance(data.get('text'), str) else ''
        stash = data.get('stash') if isinstance(data.get('stash'), str) else ''
        text = (confirmed + stash).strip()
        return ASRTranscriptEvent('partial', text) if text else None

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
            'event_id': f'event_{uuid4().hex}',
            'type': 'session.update',
            'session': {
                'input_audio_format': 'pcm',
                'sample_rate': self.settings.qwen_asr_sample_rate,
                # 模型由连接 URL 的 ?model= 指定；这里再塞 model 会被
                # Qwen-ASR-Realtime 判为非法参数，并逐帧返回 CLIENT_ERROR。
                'input_audio_transcription': {
                    'language': self.settings.qwen_asr_language,
                },
                'turn_detection': {
                    'type': 'server_vad',
                    'threshold': self.settings.qwen_asr_vad_threshold,
                    'silence_duration_ms': self.settings.qwen_vad_silence_ms,
                },
            },
        }))

    async def send_audio(self, base64_audio: str) -> None:
        if not self.websocket:
            raise RuntimeError('千问语音识别连接尚未建立。')
        await self.websocket.send(json.dumps({
            'event_id': f'event_{uuid4().hex}',
            'type': 'input_audio_buffer.append',
            'audio': base64_audio,
        }))

    async def transcript_events(self) -> AsyncIterator[ASRTranscriptEvent]:
        if not self.websocket:
            return
        async for raw_message in self.websocket:
            data = json.loads(raw_message)
            header = data.get('header') if isinstance(data.get('header'), dict) else {}
            event_type = str(data.get('type') or '')
            code = str(data.get('code') or '')
            # 专属实例的参数错误不带 type，只有 {"code":"CLIENT_ERROR",...}。
            # 过去会被静默丢弃，造成「连接成功但永远不出字幕」的假可用状态。
            is_error = (
                event_type == 'error'
                or event_type.endswith('input_audio_transcription.failed')
                or header.get('event') == 'task-failed'
                or 'error' in code.lower()
            )
            if is_error:
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


class QwenStreamingASRAgent:
    """DashScope Streaming 协议（qwen-audio-3.1-asr-flash-streaming 等）。

    与 OpenAI Realtime 完全不同：端点 /api-ws/v1/inference，用 run-task
    启动任务、WebSocket **二进制帧**送 PCM、result-generated 返回识别结果。
    对外接口与 QwenRealtimeASRAgent 保持一致，main.py 无需感知差异。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.websocket: Any = None
        self._task_id = str(uuid4())
        self._partial_text = ''

    @property
    def available(self) -> bool:
        return bool(self.settings.dashscope_api_key and self.settings.qwen_asr_model)

    @staticmethod
    def _parse(raw: Any) -> dict[str, Any]:
        try:
            text = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError, AttributeError):
            return {}

    async def connect(self) -> None:
        if not self.settings.dashscope_api_key:
            raise RuntimeError('后端未配置 DASHSCOPE_API_KEY。')

        self.websocket = await websockets.connect(
            self.settings.qwen_asr_ws_url,
            additional_headers={
                'Authorization': f'Bearer {self.settings.dashscope_api_key}',
            },
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            max_size=4 * 1024 * 1024,
        )
        parameters: dict[str, Any] = {
            'format': 'pcm',
            'sample_rate': self.settings.qwen_asr_sample_rate,
            'max_sentence_silence': self.settings.qwen_vad_silence_ms,
            'speech_noise_threshold': self.settings.qwen_asr_vad_threshold,
            'heartbeat': True,
        }
        language = (self.settings.qwen_asr_language or '').strip()
        if language:
            parameters['language_hints'] = [language]
        await self.websocket.send(json.dumps({
            'header': {
                'action': 'run-task',
                'task_id': self._task_id,
                'streaming': 'duplex',
            },
            'payload': {
                'task_group': 'audio',
                'task': 'asr',
                'function': 'recognition',
                'model': self.settings.qwen_asr_model,
                'parameters': parameters,
                'input': {},
            },
        }))

        # 收到 task-started 之后才允许送音频。
        for _ in range(10):
            try:
                raw = await asyncio.wait_for(self.websocket.recv(), timeout=8)
            except asyncio.TimeoutError as exc:
                raise RuntimeError('千问实时语音识别任务启动超时。') from exc
            data = self._parse(raw)
            header = data.get('header') if isinstance(data.get('header'), dict) else {}
            event = header.get('event') or data.get('type')
            code = str(header.get('error_code') or data.get('code') or '')
            if event == 'task-started':
                return
            if event == 'task-failed' or 'error' in code.lower():
                raise RuntimeError(
                    f"千问语音识别任务失败：{header.get('error_message') or data}"
                )
        raise RuntimeError('千问实时语音识别任务未能启动。')

    async def send_audio(self, base64_audio: str) -> None:
        if not self.websocket:
            raise RuntimeError('千问语音识别连接尚未建立。')
        # 本地协议用 base64 字符串，Streaming 协议要求原始二进制帧。
        await self.websocket.send(base64.b64decode(base64_audio))

    async def transcript_events(self) -> AsyncIterator[ASRTranscriptEvent]:
        if not self.websocket:
            return
        async for raw_message in self.websocket:
            data = self._parse(raw_message)
            if not data:
                continue
            header = data.get('header') if isinstance(data.get('header'), dict) else {}
            event = header.get('event') or data.get('type')
            code = str(header.get('error_code') or data.get('code') or '')
            if event == 'task-failed' or 'error' in code.lower():
                raise RuntimeError(
                    f"千问语音识别返回错误：{header.get('error_message') or data}"
                )
            if event == 'task-finished':
                return
            if event != 'result-generated':
                continue

            payload = data.get('payload') if isinstance(data.get('payload'), dict) else {}
            output = payload.get('output') if isinstance(payload.get('output'), dict) else {}
            sentence = output.get('sentence') if isinstance(output.get('sentence'), dict) else {}
            if sentence.get('heartbeat'):
                continue
            text = str(sentence.get('text') or '').strip()
            if not text:
                continue
            ended = bool(sentence.get('sentence_end'))
            yield ASRTranscriptEvent('final' if ended else 'partial', text)

    async def close(self) -> None:
        if self.websocket:
            try:
                await self.websocket.send(json.dumps({
                    'header': {
                        'action': 'finish-task',
                        'task_id': self._task_id,
                        'streaming': 'duplex',
                    },
                    'payload': {'input': {}},
                }))
            except Exception:  # noqa: BLE001 - best effort during shutdown
                pass
            try:
                await self.websocket.close()
            except Exception:  # noqa: BLE001
                pass
            self.websocket = None


def create_asr_agent(settings: Settings) -> QwenRealtimeASRAgent | QwenStreamingASRAgent:
    """按模型名 / QWEN_ASR_PROTOCOL 选择 ASR 协议实现。"""
    if settings.asr_is_streaming:
        return QwenStreamingASRAgent(settings)
    return QwenRealtimeASRAgent(settings)


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
        raise_for_qwen_status(response)
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
                            '上下文中的方括号内容是视频时间戳。回答涉及视频观点或事实时，必须在对应结论后引用时间戳，'
                            '格式为 [MM:SS] 或 [HH:MM:SS]。不要虚构视频中没有的信息；证据不足时明确说明。'
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
        raise_for_qwen_status(response)
        data = response.json()
        return (data['choices'][0]['message'].get('content') or '').strip()

    async def summarize(self, transcript_context: str) -> str:
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
                            '你是视频内容整理助手。把给定的连续双语字幕压缩成不超过120字的简体中文阶段摘要。'
                            '保留人物、数字、结论、因果关系和专业术语，不要补充字幕之外的信息。只输出摘要正文。'
                        ),
                    },
                    {'role': 'user', 'content': transcript_context},
                ],
                'temperature': 0.1,
                'max_tokens': 220,
                'enable_thinking': False,
            },
        )
        raise_for_qwen_status(response)
        data = response.json()
        return (data['choices'][0]['message'].get('content') or '').strip()

    async def close(self) -> None:
        await self.client.aclose()
def raise_for_qwen_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        payload = response.json()
    except Exception:
        payload = {}
    error = payload.get('error') if isinstance(payload.get('error'), dict) else {}
    code = str(payload.get('code') or error.get('code') or '')
    if code == 'AllocationQuota.FreeTierOnly':
        raise RuntimeError(
            '千问免费额度已用完。请在阿里云百炼控制台充值，或关闭“仅使用免费额度”模式。'
        )
    if response.status_code == 401:
        raise RuntimeError('千问 API Key 鉴权失败，请检查 Key 是否完整、有效。')
    if response.status_code == 403:
        raise RuntimeError('千问拒绝访问，请检查模型权限、账户余额和地域配置。')
    response.raise_for_status()


def user_facing_qwen_error(error: Exception, fallback: str) -> str:
    message = str(error)
    actionable_messages = (
        '千问免费额度已用完',
        '千问 API Key 鉴权失败',
        '千问拒绝访问',
    )
    if message.startswith(actionable_messages):
        return message
    return fallback
