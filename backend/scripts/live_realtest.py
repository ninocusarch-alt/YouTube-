"""直播模式真实链路端到端测试。

与 live_smoke.py 的区别：本脚本连的是带真实 DASHSCOPE_API_KEY 的后端，
会真实调用千问 ASR / 翻译 / 问答接口（产生极小额费用），并真实打开
本机麦克风采集音频。密钥不会打印。

用法（在 backend/ 下）：
    LIVE_REALTEST_PORT=8010 .venv/Scripts/python.exe scripts/live_realtest.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any

import httpx
import websockets

PORT = int(os.environ.get('LIVE_REALTEST_PORT', '8010'))
BASE = f'http://127.0.0.1:{PORT}'
WS = f'ws://127.0.0.1:{PORT}'

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ''))


class Collector:
    """把 WebSocket 事件按接收时刻收进列表，便于按 id 精确匹配。"""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.events: list[tuple[float, dict[str, Any]]] = []
        self.task: asyncio.Task[Any] | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._run(), name='EventCollector')

    async def _run(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    event = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                self.events.append((time.perf_counter(), event))
        except Exception:  # noqa: BLE001 - socket closed normally at shutdown
            pass

    async def wait_for(
        self,
        predicate: Any,
        timeout: float,
        since: float | None = None,
    ) -> tuple[float, dict[str, Any]] | None:
        since = since if since is not None else 0.0
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            for stamp, event in self.events:
                if stamp >= since and predicate(event):
                    return stamp, event
            await asyncio.sleep(0.02)
        return None

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


async def create_session(client: httpx.AsyncClient, mode: str, title: str) -> str:
    response = await client.post('/api/sessions', json={
        'video_url': 'live://realtest',
        'video_title': title,
        'input_mode': mode,
        'subtitle_source': 'realtest',
    })
    response.raise_for_status()
    return response.json()['session_id']


async def test_service_config(client: httpx.AsyncClient) -> None:
    response = await client.get('/api/health')
    check('服务健康', response.status_code == 200, f'HTTP {response.status_code}')
    for path in ('/api/config', '/api/settings'):
        try:
            cfg_response = await client.get(path)
            if cfg_response.status_code == 200:
                cfg = cfg_response.json()
                print(
                    '  后端配置: '
                    f"asr={cfg.get('asr_model')}  "
                    f"translation={cfg.get('translation_model')}  "
                    f"chat={cfg.get('chat_model')}  "
                    f"asr_configured={cfg.get('asr_configured')}"
                )
                break
        except Exception:  # noqa: BLE001
            continue


async def test_real_translation_and_chat() -> None:
    """用 captions 会话走真实 qwen 翻译 + 真实 Agent 问答。"""
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        session_id = await create_session(client, 'captions', '真实链路测试 · 翻译与问答')

    async with websockets.connect(f'{WS}/ws/sessions/{session_id}', open_timeout=10) as ws:
        collector = Collector(ws)
        collector.start()
        ready = await collector.wait_for(lambda e: e.get('type') == 'session.ready', 10)
        check('captions 会话就绪', ready is not None)
        if not ready:
            await collector.stop()
            return

        sentences = [
            'We should rotate mid before they collapse on us.',
            'Their jungler is top side, dragon is free.',
        ]
        sent_at: dict[str, float] = {}
        for index, text in enumerate(sentences, 1):
            seg_id = f'realtest-seg-{index}'
            sent_at[seg_id] = time.perf_counter()
            await ws.send(json.dumps({
                'type': 'caption.segment',
                'id': seg_id,
                'text': text,
                'start_ms': (index - 1) * 5000,
                'end_ms': index * 5000,
                'source': 'realtest',
            }))

        translations: list[tuple[str, str, float]] = []
        for seg_id in sent_at:
            hit = await collector.wait_for(
                lambda e, sid=seg_id: (
                    e.get('type') == 'transcript.translation'
                    and (e.get('payload') or {}).get('id') == sid
                ),
                timeout=30,
                since=sent_at[seg_id] - 0.01,
            )
            if hit:
                stamp, event = hit
                payload = event.get('payload') or {}
                translations.append((
                    payload.get('source_text', ''),
                    payload.get('target_text', ''),
                    (stamp - sent_at[seg_id]) * 1000,
                ))
            error_hit = await collector.wait_for(
                lambda e, sid=seg_id: (
                    e.get('type') == 'transcript.translation_error'
                    and (e.get('payload') or {}).get('id') == sid
                ),
                timeout=0.2,
                since=sent_at[seg_id] - 0.01,
            )
            if error_hit and not hit:
                print('  翻译错误:', str(error_hit[1].get('message'))[:200])

        check('真实 API 返回译文', len(translations) == len(sentences),
              f'{len(translations)}/{len(sentences)} 条')
        for source, target, elapsed in translations:
            has_han = any('\u4e00' <= ch <= '\u9fff' for ch in target)
            check('译文为中文且非空', bool(target.strip()) and has_han,
                  f'{elapsed:.0f} ms  EN={source[:38]!r}  ZH={target[:40]!r}')

        # 真实 Agent 问答
        ask_at = time.perf_counter()
        await ws.send(json.dumps({
            'type': 'chat.ask',
            'request_id': 'realtest-chat-1',
            'question': '这里的 rotate mid 在游戏里是什么意思？用中文简短解释。',
            'selected_text': sentences[0],
        }))
        answer_hit = await collector.wait_for(
            lambda e: e.get('type') in ('chat.answer', 'chat.error')
            and e.get('request_id') == 'realtest-chat-1',
            timeout=30,
            since=ask_at - 0.01,
        )
        if answer_hit:
            stamp, event = answer_hit
            ok = event.get('type') == 'chat.answer' and bool((event.get('answer') or '').strip())
            detail = (
                f'{(stamp - ask_at) * 1000:.0f} ms  '
                f"{str(event.get('answer') or event.get('message'))[:90]!r}"
            )
            check('真实 Agent 问答', ok, detail)
        else:
            check('真实 Agent 问答', False, '30 s 内无响应')

        await ws.send(json.dumps({'type': 'session.close'}))
        await collector.stop()


async def test_real_asr_session() -> None:
    """audio 会话 = 真实建立千问实时 ASR WebSocket 并送 1 秒 PCM。"""
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        session_id = await create_session(client, 'audio', '真实链路测试 · ASR')

    async with websockets.connect(f'{WS}/ws/sessions/{session_id}', open_timeout=15) as ws:
        collector = Collector(ws)
        collector.start()
        ready = await collector.wait_for(lambda e: e.get('type') == 'session.ready', 20)
        if not ready:
            err = await collector.wait_for(lambda e: e.get('type') == 'error', 1)
            check('真实 ASR 会话建立', False,
                  str(err[1].get('message'))[:180] if err else '无 session.ready')
            await collector.stop()
            return
        event = ready[1]
        check('真实 ASR 会话建立', True,
              f"model={event.get('model')}  sample_rate={event.get('sample_rate')}")

        # 1 秒 16 kHz 单声道静音，20 ms/帧；验证上行链路不报错
        frame = b'\x00\x00' * 320
        encoded = base64.b64encode(frame).decode('ascii')
        for _ in range(50):
            await ws.send(json.dumps({'type': 'audio.append', 'audio': encoded}))
            await asyncio.sleep(0.02)
        await asyncio.sleep(1.0)
        errors = [
            (stamp, e) for stamp, e in collector.events
            if e.get('type') in ('error', 'transcript.translation_error')
        ]
        check('ASR 音频上行无错误', not errors,
              f'收到 {len(collector.events)} 个事件，错误 {len(errors)} 个')
        if errors:
            print('  首个错误:', str(errors[0][1])[:200])
        kinds = sorted({e.get('type') for _, e in collector.events})
        print('  事件类型:', kinds)
        await ws.send(json.dumps({'type': 'session.close'}))
        await collector.stop()


async def test_live_real_mode() -> None:
    """真实模式：真实麦克风 -> ASR -> 翻译 -> 字幕状态机。"""
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        devices = (await client.get('/api/live/devices', params={'refresh': 'true'})).json()
        check('真实音频设备可用', bool(devices.get('available')),
              f"麦克风 {len(devices.get('microphones') or [])} 个 / "
              f"loopback {len(devices.get('loopbacks') or [])} 个")

        await client.post('/api/live/start', json={'mock': True})
        await client.post('/api/live/stop', json={})

        started = time.perf_counter()
        response = await client.post('/api/live/start', json={'mock': False})
        if response.status_code != 200:
            check('真实模式启动', False,
                  f'HTTP {response.status_code} {str(response.json().get("detail"))[:220]}')
            return
        check('真实模式启动', True, f'{(time.perf_counter() - started) * 1000:.0f} ms')

        await asyncio.sleep(4.0)
        status = (await client.get('/api/live/status')).json()
        metrics = status.get('metrics') or {}
        print('  运行 4 s 指标:', {
            k: metrics.get(k) for k in
            ('frames_captured', 'frames_total', 'frames_sent', 'frames_gated',
             'asr_seconds', 'published', 'last_error')
        })
        print('  完整 metrics:', json.dumps(metrics, ensure_ascii=False)[:400])
        check('真实麦克风确实出帧', int(metrics.get('frames_captured') or 0) > 0,
              f"frames_captured={metrics.get('frames_captured')}")
        check('采集/上行无致命错误', not status.get('last_error'),
              str(status.get('last_error') or '')[:160])

        stopped = await client.post('/api/live/stop', json={})
        after = stopped.json()
        check('真实模式干净停止', after.get('mode') == 'idle',
              f"mode={after.get('mode')}")


async def main() -> None:
    print(f'=== 真实链路测试 @ {BASE} ===')
    print('注意：会真实调用千问 API 并短暂打开本机麦克风。\n')
    async with httpx.AsyncClient(base_url=BASE, timeout=20.0) as client:
        await test_service_config(client)

    print('\n--- 1. 真实翻译 + Agent 问答 ---')
    await test_real_translation_and_chat()
    print('\n--- 2. 真实 ASR 会话 ---')
    await test_real_asr_session()
    print('\n--- 3. 直播真实模式 ---')
    await test_live_real_mode()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f'\n=== 汇总 {passed}/{len(RESULTS)} 通过 ===')
    for name, ok, detail in RESULTS:
        if not ok:
            print(f'  FAILED: {name}  {detail}')
    raise SystemExit(0 if passed == len(RESULTS) else 1)


if __name__ == '__main__':
    asyncio.run(main())
