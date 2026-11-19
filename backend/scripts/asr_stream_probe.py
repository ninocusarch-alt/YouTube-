"""Probe DashScope Streaming ASR: log every server event with elapsed time.

Run from backend/ with VIDEO_COMPANION_ENV_FILE pointing at the installed .env.
Answers: does the server end the task spontaneously (task-finished / close)
when audio goes quiet, and how long after?
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services.agents import QwenStreamingASRAgent  # noqa: E402

FRAME_BYTES = 640  # 20 ms @ 16 kHz mono int16


async def main() -> None:
    settings = get_settings()
    pcm_path = Path(__file__).resolve().parents[1] / 'data' / 'tts_en.pcm'
    pcm = pcm_path.read_bytes() if pcm_path.exists() else b''
    speech_frames = [pcm[i:i + FRAME_BYTES].ljust(FRAME_BYTES, b'\x00')
                     for i in range(0, len(pcm), FRAME_BYTES)]
    print('protocol =', 'streaming' if settings.asr_is_streaming else 'realtime')
    print('url =', settings.qwen_asr_ws_url)
    print('model =', settings.qwen_asr_model, 'speech frames =', len(speech_frames))
    t0 = time.monotonic()

    def stamp() -> str:
        return f'{time.monotonic() - t0:6.2f}s'

    async with websockets.connect(
        settings.qwen_asr_ws_url,
        additional_headers={'Authorization': f'Bearer {settings.dashscope_api_key}'},
        open_timeout=15, ping_interval=20, ping_timeout=20,
        max_size=4 * 1024 * 1024,
    ) as ws:
        task_id = 'probe-' + str(int(t0))
        await ws.send(json.dumps({
            'header': {'action': 'run-task', 'task_id': task_id, 'streaming': 'duplex'},
            'payload': {
                'task_group': 'audio', 'task': 'asr', 'function': 'recognition',
                'model': settings.qwen_asr_model,
                'parameters': {
                    'format': 'pcm', 'sample_rate': settings.qwen_asr_sample_rate,
                    'max_sentence_silence': settings.qwen_vad_silence_ms,
                    'speech_noise_threshold': settings.qwen_asr_vad_threshold,
                    'heartbeat': True,
                    **({'language_hints': [settings.qwen_asr_language]}
                       if (settings.qwen_asr_language or '').strip() else {}),
                },
                'input': {},
            },
        }))

        # The protocol requires task-started before any audio frame.
        for _ in range(10):
            raw = await asyncio.wait_for(ws.recv(), timeout=8)
            text = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else raw
            print(f'[{stamp()}] PRE {text[:420]}', flush=True)
            if '"task-started"' in text:
                break

        async def reader() -> None:
            try:
                async for raw in ws:
                    text = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else raw
                    print(f'[{stamp()}] EVENT {text[:420]}', flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f'[{stamp()}] READER_CLOSED {type(exc).__name__}: {exc}', flush=True)

        reader_task = asyncio.create_task(reader())
        print(f'[{stamp()}] sending {len(speech_frames)} speech frames ...', flush=True)
        for frame in speech_frames:
            await ws.send(frame)
            await asyncio.sleep(0.02)
        print(f'[{stamp()}] speech done; now sending 35s of SILENCE frames ...', flush=True)
        for i in range(35 * 50):
            await ws.send(b'\x00' * FRAME_BYTES)
            await asyncio.sleep(0.02)
        print(f'[{stamp()}] silence done; waiting 5s ...', flush=True)
        await asyncio.sleep(5)
        print(f'[{stamp()}] closing from client', flush=True)
        reader_task.cancel()
        await asyncio.gather(reader_task, return_exceptions=True)

    print(f'[{stamp()}] DONE', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
