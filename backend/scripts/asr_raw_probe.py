"""直连千问实时 ASR，打印原始事件（不做任何解析），用于诊断事件格式。

用法（在 backend/ 下）：
    VIDEO_COMPANION_ENV_FILE="..." .venv/Scripts/python.exe scripts/asr_raw_probe.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services.agents import QwenRealtimeASRAgent  # noqa: E402

PCM_PATH = Path(__file__).resolve().parents[1] / 'data' / 'tts_en.pcm'
FRAME_BYTES = 640


async def main() -> None:
    settings = get_settings()
    url = QwenRealtimeASRAgent(settings)._connection_url()
    print('URL:', url.split('?')[0], '?model=...')
    print('key configured:', bool(settings.dashscope_api_key))
    pcm = PCM_PATH.read_bytes() if PCM_PATH.exists() else b''
    frames = [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    print('audio frames:', len(frames), 'duration:', round(len(pcm) / 32000, 2), 's')

    raw_events: list[str] = []
    closed = asyncio.Event()

    async with websockets.connect(
        url,
        additional_headers={
            'Authorization': f'Bearer {settings.dashscope_api_key}',
            'OpenAI-Beta': 'realtime=v1',
        },
        open_timeout=15,
        ping_interval=20,
        ping_timeout=20,
        max_size=4 * 1024 * 1024,
    ) as ws:
        async def reader() -> None:
            try:
                async for raw in ws:
                    text = raw if isinstance(raw, str) else raw.decode('utf-8', 'replace')
                    raw_events.append(text)
            except Exception as exc:  # noqa: BLE001
                raw_events.append(f'<READER_CLOSED {type(exc).__name__}: {exc}>')
            finally:
                closed.set()

        task = asyncio.create_task(reader())
        await ws.send(json.dumps({
            'type': 'session.update',
            'session': {
                'input_audio_format': 'pcm',
                'sample_rate': settings.qwen_asr_sample_rate,
                'input_audio_transcription': {
                    'model': settings.qwen_asr_model,
                    'language': settings.qwen_asr_language,
                },
                'turn_detection': {
                    'type': 'server_vad',
                    'silence_duration_ms': settings.qwen_vad_silence_ms,
                },
            },
        }))
        await asyncio.sleep(0.5)
        print('after session.update, events so far:', len(raw_events))
        for event in raw_events[:5]:
            print('  ', event[:400])

        for frame in frames:
            await ws.send(json.dumps({
                'type': 'input_audio_buffer.append',
                'audio': base64.b64encode(frame.ljust(FRAME_BYTES, b'\x00')).decode('ascii'),
            }))
            await asyncio.sleep(0.02)
        for _ in range(45):
            await ws.send(json.dumps({
                'type': 'input_audio_buffer.append',
                'audio': base64.b64encode(b'\x00' * FRAME_BYTES).decode('ascii'),
            }))
            await asyncio.sleep(0.02)
        print('audio sent, waiting 8 s for server events…')
        for _ in range(80):
            if closed.is_set():
                break
            await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    print(f'\n=== ALL RAW EVENTS ({len(raw_events)}) ===')
    for index, event in enumerate(raw_events, 1):
        print(f'{index:3d}. {event[:500]}')


if __name__ == '__main__':
    asyncio.run(main())
