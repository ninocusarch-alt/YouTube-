"""真实英文语音闭环测试：PCM -> 千问实时 ASR -> 断句 -> qwen 翻译 -> 中文。

用 scripts/tts_en.pcm（16 kHz / 单声道 / s16le，由英文 TTS 生成）按 20 ms
实时节奏送进原有 /ws/sessions/{id} 的 audio.append，验证新模型的 ASR
事件格式能被现有解析器识别，并产出中文字幕。

用法（在 backend/ 下）：
    LIVE_REALTEST_PORT=8010 .venv/Scripts/python.exe scripts/live_realvoice.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

PORT = int(os.environ.get('LIVE_REALTEST_PORT', '8010'))
BASE = f'http://127.0.0.1:{PORT}'
WS = f'ws://127.0.0.1:{PORT}'
PCM_PATH = Path(__file__).resolve().parents[1] / 'data' / 'tts_en.pcm'
FRAME_BYTES = 640  # 20 ms @ 16 kHz mono s16le
EXPECTED_EN = 'We should rotate mid before they collapse on us.'


async def main() -> None:
    if not PCM_PATH.exists():
        raise SystemExit(f'缺少测试音频 {PCM_PATH}')
    pcm = PCM_PATH.read_bytes()
    frames = [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    if frames and len(frames[-1]) < FRAME_BYTES:
        frames[-1] = frames[-1] + b'\x00' * (FRAME_BYTES - len(frames[-1]))
    silence = b'\x00' * FRAME_BYTES
    print(f'=== 真实语音闭环 @ {BASE} ===')
    print(f'音频: {len(pcm)} bytes / {len(pcm) / 32000:.2f} s / {len(frames)} 帧')
    print(f'期望识别: {EXPECTED_EN!r}\n')

    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        response = await client.post('/api/sessions', json={
            'video_url': 'live://realvoice',
            'video_title': '真实语音闭环测试',
            'input_mode': 'audio',
            'subtitle_source': 'tts-en',
        })
        response.raise_for_status()
        session_id = response.json()['session_id']

    events: list[tuple[float, dict[str, Any]]] = []
    stop = asyncio.Event()

    async with websockets.connect(f'{WS}/ws/sessions/{session_id}', open_timeout=15) as ws:
        async def reader() -> None:
            try:
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    events.append((time.perf_counter(), event))
            except Exception:  # noqa: BLE001
                pass
            finally:
                stop.set()

        reader_task = asyncio.create_task(reader())

        # 等待 session.ready（说明真实 ASR WebSocket 已连上）
        deadline = time.perf_counter() + 20
        ready = None
        while time.perf_counter() < deadline and not stop.is_set():
            for _, event in events:
                if event.get('type') == 'session.ready':
                    ready = event
                    break
            if ready:
                break
            await asyncio.sleep(0.03)
        if not ready:
            print('FAIL: 未收到 session.ready')
            print('原始事件:', [str(e)[:200] for _, e in events[:5]])
            reader_task.cancel()
            raise SystemExit(1)
        print(f"ASR 会话就绪: model={ready.get('model')} rate={ready.get('sample_rate')}")

        started = time.perf_counter()
        for frame in frames:
            if stop.is_set():
                break
            await ws.send(json.dumps({
                'type': 'audio.append',
                'audio': base64.b64encode(frame).decode('ascii'),
            }))
            await asyncio.sleep(0.02)
        for _ in range(45):  # 0.9 s 静音触发 server_vad 断句
            if stop.is_set():
                break
            await ws.send(json.dumps({
                'type': 'audio.append',
                'audio': base64.b64encode(silence).decode('ascii'),
            }))
            await asyncio.sleep(0.02)
        sent_done = time.perf_counter()
        print(f'音频发送完成，用时 {(sent_done - started) * 1000:.0f} ms，等待识别与翻译…')

        translation = None
        deadline = time.perf_counter() + 35
        while time.perf_counter() < deadline and not stop.is_set():
            for stamp, event in events:
                if event.get('type') == 'transcript.translation':
                    translation = (stamp, event)
                    break
            if translation:
                break
            await asyncio.sleep(0.03)

        live_texts = [
            (e.get('payload') or {}).get('source_text', '')
            for _, e in events if e.get('type') == 'transcript.live'
        ]
        segments = [
            (e.get('payload') or {}).get('source_text', '')
            for _, e in events if e.get('type') == 'transcript.segment'
        ]
        errors = [
            e for _, e in events
            if e.get('type') in ('error', 'transcript.translation_error', 'chat.error')
        ]

        print('\n--- 事件统计 ---')
        kinds: dict[str, int] = {}
        for _, event in events:
            kinds[event.get('type', '?')] = kinds.get(event.get('type', '?'), 0) + 1
        print('类型:', kinds)
        print('ASR 实时文本（最后 3 条）:', [t for t in live_texts if t][-3:])
        print('断句:', [s for s in segments if s])
        if errors:
            print('错误事件:', [str(e)[:240] for e in errors[:3]])
        print('原始事件样本:')
        for _, event in events[:8]:
            print('  ', json.dumps(event, ensure_ascii=False)[:220])

        print('\n--- 结果 ---')
        if translation:
            stamp, event = translation
            payload = event.get('payload') or {}
            zh = payload.get('target_text') or ''
            en = payload.get('source_text') or ''
            has_han = any('\u4e00' <= ch <= '\u9fff' for ch in zh)
            print(f'PASS  识别原文: {en!r}')
            print(f'PASS  中文译文: {zh!r}')
            print(f'      端到端延迟: {(stamp - started) * 1000:.0f} ms（含 1.7 s 音频播放 + 0.9 s 静音）')
            ok = bool(has_han and en.strip())
            print('VERDICT:', 'PASS' if ok else 'FAIL')
        else:
            print('FAIL  35 s 内没有产出中文译文')
            print('      这通常意味着新 ASR 模型的事件格式与解析器不匹配。')
        try:
            await ws.send(json.dumps({'type': 'session.close'}))
        except Exception:  # noqa: BLE001
            pass
        reader_task.cancel()
        await asyncio.gather(reader_task, return_exceptions=True)

    raise SystemExit(0 if translation else 1)


if __name__ == '__main__':
    asyncio.run(main())
