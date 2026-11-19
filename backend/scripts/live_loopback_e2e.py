"""直播模式真实端到端：英文语音 -> 扬声器 -> WASAPI loopback -> ASR -> 翻译 -> OBS 字幕。

会把 16 kHz PCM 包成 WAV 用 winsound 异步播放，同时让直播模式只采集
系统声音，最后在 /ws/live/overlay 上等待 caption.show。

用法（在 backend/ 下）：
    LIVE_REALTEST_PORT=8010 .venv/Scripts/python.exe scripts/live_loopback_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import wave
import winsound
from pathlib import Path

import httpx
import websockets

PORT = int(os.environ.get('LIVE_REALTEST_PORT', '8010'))
BASE = f'http://127.0.0.1:{PORT}'
WS = f'ws://127.0.0.1:{PORT}'
DATA = Path(__file__).resolve().parents[1] / 'data'
PCM_PATH = DATA / 'tts_en.pcm'
WAV_PATH = DATA / 'tts_en.wav'


def make_wav() -> float:
    pcm = PCM_PATH.read_bytes()
    with wave.open(str(WAV_PATH), 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)
    return len(pcm) / 32000.0


async def main() -> None:
    duration = make_wav()
    print('=== 直播模式真实端到端（系统声音 loopback） ===')
    print(f'测试音频: {WAV_PATH.name}  {duration:.2f} s')

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        devices = (await client.get('/api/live/devices', params={'refresh': 'true'})).json()
        loops = devices.get('loopbacks') or []
        print(f"可用 loopback: {len(loops)} 个, 默认={devices.get('default_loopback')}")
        if not loops:
            raise SystemExit('没有可用的系统声音 loopback 设备。')

        await client.post('/api/live/config', json={
            'source_microphone': False,
            'source_system': True,
            'publish_delay_ms': 0,
            'hold_ms': 8000,
            'device_loopback': None,
        })
        await client.post('/api/live/stop', json={})

    events: list[tuple[float, dict]] = []
    async with websockets.connect(f'{WS}/ws/live/overlay', open_timeout=10) as overlay:
        async def reader() -> None:
            try:
                async for raw in overlay:
                    try:
                        events.append((time.perf_counter(), json.loads(raw)))
                    except (TypeError, ValueError):
                        continue
            except Exception:  # noqa: BLE001
                pass

        reader_task = asyncio.create_task(reader())

        async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
            start = await client.post('/api/live/start', json={'mock': False})
            if start.status_code != 200:
                print('FAIL 启动失败:', start.status_code, str(start.json().get('detail'))[:220])
                reader_task.cancel()
                raise SystemExit(1)
            print('直播真实模式已启动:', start.json().get('mode'))

            await asyncio.sleep(0.8)  # 等采集线程就绪
            played_at = time.perf_counter()
            winsound.PlaySound(str(WAV_PATH), winsound.SND_FILENAME | winsound.SND_ASYNC)
            print('已在扬声器播放英文语音，等待 ASR / 翻译 / 字幕上屏…')

            shown: list[tuple[float, dict]] = []
            deadline = time.perf_counter() + 28
            while time.perf_counter() < deadline:
                for stamp, event in events:
                    if event.get('type') == 'caption.show' and (stamp, event) not in shown:
                        shown.append((stamp, event))
                if shown:
                    break
                await asyncio.sleep(0.1)

            status = (await client.get('/api/live/status')).json()
            print('\n--- 指标 ---')
            print(json.dumps(status.get('metrics'), ensure_ascii=False)[:420])
            print('on_air:', len(status.get('on_air') or []),
                  ' records:', len(status.get('records') or []),
                  ' last_error:', status.get('last_error'))
            print('overlay 事件类型:', sorted({e.get('type') for _, e in events}))

            print('\n--- 结果 ---')
            for stamp, event in shown[:3]:
                print(f"PASS  caption.show  {(stamp - played_at) * 1000:.0f} ms  "
                      f"EN={str(event.get('source_text'))[:44]!r}  ZH={event.get('text')!r}")
            if not shown:
                print('FAIL  28 s 内 OBS 叠层没有收到字幕')
                print('      （可能是扬声器被静音 / loopback 采不到播放 / 环境未发声）')

            await client.post('/api/live/stop', json={})
            await client.post('/api/live/config', json={
                'source_microphone': True,
                'source_system': False,
                'hold_ms': 3600,
            })
        reader_task.cancel()
        await asyncio.gather(reader_task, return_exceptions=True)

    raise SystemExit(0 if shown else 1)


if __name__ == '__main__':
    asyncio.run(main())
