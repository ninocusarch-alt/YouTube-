"""Broadcast hub for live mode.

Single process-wide hub: the local audio bridge pushes upstream events here,
the caption state machine decides what is allowed on air, and two WebSocket
channels fan out - a read-only OBS overlay and a bidirectional streamer
console.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Any

from fastapi import WebSocket

from .caption import AI_LABEL_TEXT, CaptionState, LiveConfig

BACKEND_PORT = int(os.environ.get('VIDEO_COMPANION_PORT', '8000'))
OVERLAY_URL = f'http://127.0.0.1:{BACKEND_PORT}/live/overlay.html'
CONSOLE_URL = f'http://127.0.0.1:{BACKEND_PORT}/live/console.html'

DEMO_LINES = [
    ('We should rotate mid before they collapse on us.', '我们应该在他们包夹之前先转中路。'),
    ('I need ten seconds for my ultimate, play it slow.', '我的大招还要十秒，先稳一点别急。'),
    ('Their jungler is top side, dragon is free.', '他们打野在上半区，小龙可以直接拿。'),
    ('Nice peel, I will push the wave and recall.', '保护得漂亮，我把这波线推了就回城。'),
]


class LiveHub:
    def __init__(self) -> None:
        self.config = LiveConfig()
        self.state = CaptionState(self.config)
        self.mode = 'idle'  # idle | live | mock
        self.session_id = ''
        self.started_at = 0.0
        self.last_error = ''
        self.bridge: Any = None
        self.overlay_clients: set[WebSocket] = set()
        self.console_clients: set[WebSocket] = set()
        # Sinks run in this process (the Win32 caption window registers one).
        # They receive the exact same events as OBS browser-source clients.
        self.local_overlay_sinks: list[Any] = []
        self.metrics: dict[str, Any] = {
            'frames_captured': 0, 'frames_total': 0, 'frames_gated': 0,
            'frames_sent': 0, 'frames_keepalive': 0, 'reconnects': 0,
            'asr_seconds': 0.0, 'segments': 0, 'levels': {},
        }
        self._tasks: list[asyncio.Task[Any]] = []
        self._demo_index = 0

    # ---------------------------------------------------------------- lifecycle
    async def start(self, *, mock: bool = False) -> None:
        await self.stop()
        self.last_error = ''
        self.started_at = time.time()
        self._demo_index = 0
        if mock:
            self.mode = 'mock'
            self.session_id = 'demo-session'
        else:
            from .bridge import LiveAudioBridge  # late import avoids an import cycle

            bridge = LiveAudioBridge(self)
            try:
                await bridge.start()
            except Exception as exc:
                # A failed ASR connect can leave capture threads / sockets alive.
                await bridge.stop()
                self.mode = 'idle'
                self.last_error = f'{type(exc).__name__}: {exc}'
                raise
            self.bridge = bridge
            self.mode = 'live'
            self.session_id = bridge.session_id
        self._tasks = [asyncio.create_task(self._flush_loop(), name='LiveCaptionFlush')]
        await self.broadcast_console({'type': 'state', 'payload': self.status()})

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self.bridge is not None:
            try:
                await self.bridge.stop()
            except Exception as exc:  # pragma: no cover - device teardown
                self.last_error = f'采集停止异常：{exc}'
            self.bridge = None
        self.mode = 'idle'
        self.session_id = ''
        self.metrics['levels'] = {}
        # A previous "hide all" must not silently swallow captions of the next
        # stream. Keep the bilingual records (for SRT / replay) but reset on-air.
        await self.broadcast_overlay(self.state.clear_all())
        await self.broadcast_console({'type': 'state', 'payload': self.status()})

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(0.04)
            for event in self.state.flush():
                await self.broadcast_overlay(event)
                await self.broadcast_console({'type': 'caption.on_air', 'payload': event})

    # ------------------------------------------------------------------ upstream
    async def on_upstream_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get('type') or '')
        payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
        if kind == 'transcript.translation':
            self.metrics['segments'] += 1
            caption = self.state.submit(payload)
            if caption:
                await self.broadcast_console({
                    'type': 'caption.record',
                    'payload': caption.as_record(),
                    'pending': True,
                })
        elif kind == 'transcript.segment':
            await self.broadcast_console({'type': 'caption.partial', 'payload': payload})
        elif kind == 'transcript.translation_error':
            await self.broadcast_console({
                'type': 'notice',
                'text': str(event.get('message') or '本段翻译失败，已跳过上屏。'),
            })
        elif kind in {'chat.answer', 'chat.error'}:
            await self.broadcast_console(event)
        elif kind == 'session.summary':
            await self.broadcast_console({
                'type': 'summary',
                'payload': payload,
            })
        elif kind == 'error':
            await self.broadcast_console({'type': 'notice', 'text': str(event.get('message') or '上游服务报错。')})

    async def inject_demo(self, source_text: str | None = None, target_text: str | None = None) -> dict[str, Any]:
        """Offline demo: feed one English line through the same publish path."""
        if source_text is None:
            source_text, target_text = DEMO_LINES[self._demo_index % len(DEMO_LINES)]
            self._demo_index += 1
        segment = {
            'id': f'demo-{int(time.time() * 1000)}-{self._demo_index}',
            'source_text': source_text,
            'target_text': target_text or f'［译文］{source_text}',
            'status': 'final',
            'timestamp': time.time() - 0.18,
        }
        await self.on_upstream_event({'type': 'transcript.translation', 'payload': segment})
        return segment

    async def ask(self, question: str, selected_text: str = '', request_id: str = '') -> None:
        if self.mode == 'mock':
            answer = (
                '演示模式下的本地回答：这一句来自外服对局语音。'
                + (f'你选中的原句是「{selected_text}」。' if selected_text else '')
                + '填入千问 API Key 并启动真实模式后，这里会走原有的 Agent 问答管线（chat.ask → qwen-plus）。'
            )
            await self.broadcast_console({'type': 'chat.answer', 'request_id': request_id, 'answer': answer})
            return
        if self.bridge is None:
            await self.broadcast_console({
                'type': 'chat.error', 'request_id': request_id, 'message': '直播模式尚未启动。',
            })
            return
        await self.bridge.send({
            'type': 'chat.ask',
            'request_id': request_id,
            'question': question,
            'selected_segment_id': '',
            'selected_text': selected_text,
        })

    # ----------------------------------------------------------------- broadcast
    async def _fanout(self, clients: set[WebSocket], payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for client in list(clients):
            try:
                await client.send_json(payload)
            except Exception:
                dead.append(client)
        for client in dead:
            clients.discard(client)

    def register_local_overlay_sink(self, sink: Any) -> None:
        """Desktop caption window subscribes without a browser or WebSocket."""
        if sink not in self.local_overlay_sinks:
            self.local_overlay_sinks.append(sink)

    async def broadcast_overlay(self, payload: dict[str, Any]) -> None:
        await self._fanout(self.overlay_clients, payload)
        for sink in list(self.local_overlay_sinks):
            try:
                sink(payload)
            except Exception:  # a dead window must not break the ASR pipeline
                self.local_overlay_sinks.remove(sink)

    async def broadcast_console(self, payload: dict[str, Any]) -> None:
        await self._fanout(self.console_clients, payload)

    def attach_overlay(self, websocket: WebSocket) -> None:
        self.overlay_clients.add(websocket)

    def detach_overlay(self, websocket: WebSocket) -> None:
        self.overlay_clients.discard(websocket)

    def attach_console(self, websocket: WebSocket) -> None:
        self.console_clients.add(websocket)

    def detach_console(self, websocket: WebSocket) -> None:
        self.console_clients.discard(websocket)

    # ------------------------------------------------------------------- console
    async def handle_console_message(self, message: dict[str, Any]) -> None:
        kind = str(message.get('type') or '')
        payload = message.get('payload') if isinstance(message.get('payload'), dict) else {}
        if kind == 'set_config':
            self.config.update(payload)
            self.state.config = self.config
            self.state.lines = deque(self.state.lines, maxlen=self.config.max_lines)
            await self.broadcast_console({'type': 'state', 'payload': self.status()})
        elif kind == 'hide':
            await self.broadcast_overlay(self.state.hide_all())
            await self.broadcast_console({'type': 'state', 'payload': self.status()})
        elif kind == 'clear':
            await self.broadcast_overlay(self.state.clear_all())
            await self.broadcast_console({'type': 'state', 'payload': self.status()})
        elif kind == 'resume':
            self.state.resume()
            await self.broadcast_console({'type': 'state', 'payload': self.status()})
        elif kind == 'recall':
            for event in self.state.recall(payload.get('id')):
                await self.broadcast_overlay(event)
        elif kind == 'chat.ask':
            await self.ask(
                str(message.get('question') or '').strip(),
                str(message.get('selected_text') or '').strip(),
                str(message.get('request_id') or ''),
            )
        elif kind == 'inject' and self.mode == 'mock':
            await self.inject_demo(
                str(message.get('source_text') or '') or None,
                str(message.get('target_text') or '') or None,
            )
        elif kind == 'request_state':
            await self.broadcast_console({'type': 'state', 'payload': self.status()})

    # --------------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        # Device enumeration opens the WASAPI stack, so it is done only by the
        # REST layer (cached); state broadcasts stay cheap.
        return {
            'mode': self.mode,
            'running': self.mode != 'idle',
            'session_id': self.session_id,
            'uptime_seconds': round(time.time() - self.started_at, 1) if self.started_at else 0,
            'last_error': self.last_error,
            'config': self.config.as_dict(),
            'metrics': {**self.metrics, 'caption': self.state.metrics()},
            'hidden': self.state.hidden,
            'on_air': [line.as_record() for line in self.state.lines],
            'pending_count': len(self.state.pending),
            'records': self.state.records[-60:],
            'devices': None,
            'overlay_url': OVERLAY_URL,
            'console_url': CONSOLE_URL,
            'ai_label_text': AI_LABEL_TEXT,
            'obs_hint': '桌面悬浮字幕窗已自动显示，可拖动到游戏画面上；OBS 用「显示器采集」捕获，或在浮层上右键切换色键黑底后用色度键抠背景。',
        }


hub = LiveHub()
