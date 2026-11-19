import asyncio
import base64
import json
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings
from app.services.agents import (
    ASRTranscriptEvent,
    QwenRealtimeASRAgent,
    QwenStreamingASRAgent,
    create_asr_agent,
    parse_qwen_asr_event,
    raise_for_qwen_status,
    user_facing_qwen_error,
)


class _FakeWebSocket:
    def __init__(self, incoming: list[dict] | None = None) -> None:
        self.incoming = list(incoming or [])
        self.sent: list[dict] = []
        self.binary_sent: list[bytes] = []

    async def send(self, payload) -> None:  # noqa: ANN001
        if isinstance(payload, (bytes, bytearray)):
            self.binary_sent.append(bytes(payload))
        else:
            self.sent.append(json.loads(payload))

    async def recv(self):  # noqa: ANN201
        if self.incoming:
            item = self.incoming.pop(0)
            return item if isinstance(item, str) else json.dumps(item)
        await asyncio.sleep(10)

    async def close(self) -> None:
        pass

    def __aiter__(self):  # noqa: ANN204
        async def generator():
            while self.incoming:
                item = self.incoming.pop(0)
                yield item if isinstance(item, str) else json.dumps(item)
        return generator()


class ParseQwenASREventTests(unittest.TestCase):
    def test_realtime_delta(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.delta',
            'delta': 'Hello',
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', 'Hello', is_delta=True))

    def test_realtime_delta_preserves_leading_space(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.delta',
            'delta': ' world',
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', ' world', is_delta=True))

    def test_realtime_completed(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.completed',
            'transcript': 'Hello world.',
        })
        self.assertEqual(event, ASRTranscriptEvent('final', 'Hello world.'))

    def test_dashscope_sentence_partial(self) -> None:
        event = parse_qwen_asr_event({
            'output': {'sentence': {'text': 'Hello', 'sentence_end': False}},
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', 'Hello'))

    def test_dashscope_sentence_final(self) -> None:
        event = parse_qwen_asr_event({
            'output': {'sentence': {'text': 'Hello world.', 'sentence_end': True}},
        })
        self.assertEqual(event, ASRTranscriptEvent('final', 'Hello world.'))

    def test_realtime_text_event_joins_confirmed_prefix_and_stash(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.text',
            'text': 'We should rotate ',
            'stash': 'mid',
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', 'We should rotate mid'))

    def test_realtime_text_event_with_only_stash(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.text',
            'text': '',
            'stash': 'Their jungler is top',
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', 'Their jungler is top'))

    def test_realtime_text_event_empty_is_ignored(self) -> None:
        self.assertIsNone(parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.text',
            'text': '',
            'stash': '',
        }))

    def test_ignores_non_transcript_event(self) -> None:
        self.assertIsNone(parse_qwen_asr_event({'type': 'session.updated'}))


class QwenRealtimeASRProtocolTests(unittest.TestCase):
    """回归：专属实例要求 event_id、且不接受 input_audio_transcription.model。"""

    @staticmethod
    def _settings() -> Settings:
        return Settings(_env_file=None, dashscope_api_key='test-key', qwen_asr_model='test-model')

    def test_session_update_matches_documented_shape(self) -> None:
        fake = _FakeWebSocket()

        async def fake_connect(url: str, **kwargs):  # noqa: ANN001, ARG001
            return fake

        with patch('app.services.agents.websockets.connect', new=fake_connect):
            asyncio.run(QwenRealtimeASRAgent(self._settings()).connect())
        self.assertEqual(len(fake.sent), 1)
        message = fake.sent[0]
        self.assertEqual(message['type'], 'session.update')
        self.assertTrue(message.get('event_id'))
        session = message['session']
        self.assertEqual(session['input_audio_transcription'], {'language': 'en'})
        self.assertNotIn('model', session['input_audio_transcription'])
        self.assertEqual(session['turn_detection']['type'], 'server_vad')
        self.assertIn('threshold', session['turn_detection'])

    def test_audio_append_has_required_event_id(self) -> None:
        agent = QwenRealtimeASRAgent(self._settings())
        fake = _FakeWebSocket()
        agent.websocket = fake
        asyncio.run(agent.send_audio('AAAA'))
        message = fake.sent[0]
        self.assertEqual(message['type'], 'input_audio_buffer.append')
        self.assertTrue(message.get('event_id'))
        self.assertEqual(message['audio'], 'AAAA')

    def test_bare_client_error_is_surfaced(self) -> None:
        """专属实例的 {"code":"CLIENT_ERROR"} 过去会被静默丢弃。"""
        agent = QwenRealtimeASRAgent(self._settings())
        agent.websocket = _FakeWebSocket(incoming=[
            {'code': 'CLIENT_ERROR', 'message': 'parse parameters failed'},
        ])

        async def collect():  # noqa: ANN202
            return [event async for event in agent.transcript_events()]

        with self.assertRaisesRegex(RuntimeError, 'CLIENT_ERROR'):
            asyncio.run(collect())

    def test_transcription_failed_event_is_surfaced(self) -> None:
        agent = QwenRealtimeASRAgent(self._settings())
        agent.websocket = _FakeWebSocket(incoming=[
            {
                'type': 'conversation.item.input_audio_transcription.failed',
                'error': {'code': 'bad_audio', 'message': 'unsupported'},
            },
        ])

        async def collect():  # noqa: ANN202
            return [event async for event in agent.transcript_events()]

        with self.assertRaisesRegex(RuntimeError, 'bad_audio'):
            asyncio.run(collect())


class QwenStreamingASRTests(unittest.TestCase):
    """回归：qwen-audio-3.1-asr-flash-streaming 走 run-task / 二进制帧协议。"""

    @staticmethod
    def _settings(**overrides) -> Settings:  # noqa: ANN003
        return Settings(
            _env_file=None,
            dashscope_api_key='test-key',
            qwen_asr_model='qwen-audio-3.1-asr-flash-streaming',
            **overrides,
        )

    def test_factory_selects_protocol_by_model(self) -> None:
        streaming = self._settings(dashscope_base_url=(
            'https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
        ))
        self.assertTrue(streaming.asr_is_streaming)
        self.assertIsInstance(create_asr_agent(streaming), QwenStreamingASRAgent)
        self.assertTrue(streaming.qwen_asr_ws_url.endswith('/api-ws/v1/inference'))
        realtime = Settings(_env_file=None, qwen_asr_model='qwen3-asr-flash-realtime')
        self.assertFalse(realtime.asr_is_streaming)
        self.assertIsInstance(create_asr_agent(realtime), QwenRealtimeASRAgent)

    def test_run_task_shape_and_binary_audio(self) -> None:
        fake = _FakeWebSocket(incoming=[
            {'header': {'event': 'task-started', 'task_id': 'x'}, 'payload': {}},
        ])

        async def fake_connect(url, **kwargs):  # noqa: ANN001, ARG001
            return fake

        with patch('app.services.agents.websockets.connect', new=fake_connect):
            agent = create_asr_agent(self._settings())
            asyncio.run(agent.connect())
        message = fake.sent[0]
        self.assertEqual(message['header']['action'], 'run-task')
        self.assertEqual(message['header']['streaming'], 'duplex')
        self.assertTrue(message['header']['task_id'])
        self.assertEqual(message['payload']['model'], 'qwen-audio-3.1-asr-flash-streaming')
        parameters = message['payload']['parameters']
        self.assertEqual(parameters['format'], 'pcm')
        self.assertEqual(parameters['sample_rate'], 16000)
        self.assertEqual(parameters['language_hints'], ['en'])

        asyncio.run(agent.send_audio(base64.b64encode(b'\x01\x02').decode('ascii')))
        self.assertEqual(fake.binary_sent, [b'\x01\x02'])

    def test_result_generated_yields_partial_then_final(self) -> None:
        agent = QwenStreamingASRAgent(self._settings())
        agent.websocket = _FakeWebSocket(incoming=[
            {
                'header': {'event': 'result-generated'},
                'payload': {'output': {'sentence': {'text': 'We should', 'sentence_end': False}}},
            },
            {
                'header': {'event': 'result-generated'},
                'payload': {'output': {'sentence': {
                    'text': 'We should rotate mid.', 'sentence_end': True,
                }}},
            },
            {'header': {'event': 'task-finished'}, 'payload': {}},
        ])

        async def collect():  # noqa: ANN202
            return [event async for event in agent.transcript_events()]

        self.assertEqual(asyncio.run(collect()), [
            ASRTranscriptEvent('partial', 'We should'),
            ASRTranscriptEvent('final', 'We should rotate mid.'),
        ])

    def test_heartbeat_is_skipped_and_task_failed_raises(self) -> None:
        agent = QwenStreamingASRAgent(self._settings())
        agent.websocket = _FakeWebSocket(incoming=[
            {
                'header': {'event': 'result-generated'},
                'payload': {'output': {'sentence': {'heartbeat': True, 'text': ''}}},
            },
            {
                'header': {
                    'event': 'task-failed',
                    'error_code': 'CLIENT_ERROR',
                    'error_message': 'bad format',
                },
                'payload': {},
            },
        ])

        async def collect():  # noqa: ANN202
            return [event async for event in agent.transcript_events()]

        with self.assertRaisesRegex(RuntimeError, 'bad format'):
            asyncio.run(collect())


class QwenHttpErrorTests(unittest.TestCase):
    def test_free_tier_exhaustion_has_actionable_message(self) -> None:
        request = httpx.Request('POST', 'https://example.test/chat/completions')
        response = httpx.Response(
            403,
            request=request,
            json={'code': 'AllocationQuota.FreeTierOnly', 'message': 'Free quota exhausted.'},
        )
        with self.assertRaisesRegex(RuntimeError, '免费额度已用完'):
            raise_for_qwen_status(response)

    def test_unauthorized_has_actionable_message(self) -> None:
        request = httpx.Request('POST', 'https://example.test/chat/completions')
        response = httpx.Response(401, request=request, json={'message': 'Unauthorized'})
        with self.assertRaisesRegex(RuntimeError, '鉴权失败'):
            raise_for_qwen_status(response)

    def test_known_quota_error_is_safe_to_show_to_user(self) -> None:
        error = RuntimeError('千问免费额度已用完。请在阿里云百炼控制台充值。')
        self.assertEqual(
            user_facing_qwen_error(error, '通用提示'),
            '千问免费额度已用完。请在阿里云百炼控制台充值。',
        )

    def test_unknown_error_uses_generic_fallback(self) -> None:
        self.assertEqual(user_facing_qwen_error(RuntimeError('private detail'), '通用提示'), '通用提示')


if __name__ == '__main__':
    unittest.main()
