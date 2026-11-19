"""Local audio bridge - a headless replacement for the Chrome extension.

It behaves exactly like the extension's background worker: open the existing
``/ws/sessions/{id}`` with ``input_mode='audio'``, stream 20 ms PCM frames as
``audio.append``, and forward upstream events into the live hub. The whole
ASR / segmentation / translation / chat / summary pipeline stays untouched.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
from contextlib import suppress
from typing import Any

import websockets

from .devices import capture_frames, list_devices
from .pcm import EnergyVAD, FrameAssembler, FrameMailbox, auto_gain, mix_frames, normalize, rms

BACKEND_PORT = int(os.environ.get('VIDEO_COMPANION_PORT', '8000'))
BACKEND_WS = f'ws://127.0.0.1:{BACKEND_PORT}/ws/sessions/{{session_id}}'
TICK_SECONDS = 0.02  # one 20 ms frame per tick keeps ASR input continuous
FRAME_BYTES = 640  # 20 ms @ 16 kHz mono int16
SILENCE_TAIL_SECONDS = 1.6  # continuous silence right after speech, so server VAD can close a sentence
KEEPALIVE_INTERVAL = 0.2  # sparse silence during long quiet stretches, keeps the ASR task alive


class LiveAudioBridge:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.session_id = ''
        self._ws: Any = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._tasks: list[asyncio.Task[Any]] = []
        self._session_tasks: list[asyncio.Task[Any]] = []
        self._mailboxes: dict[str, FrameMailbox] = {}
        self._outbox: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._vad = EnergyVAD()
        self._send_lock = asyncio.Lock()
        self._selected: list[tuple[str, int]] = []
        self._session_ready = asyncio.Event()
        self._first_error: Exception | None = None

    def _selected_sources(self) -> list[tuple[str, int]]:
        config = self.hub.config
        devices = list_devices()
        if not devices.get('available'):
            raise RuntimeError(devices.get('hint') or '本机音频设备不可用。')
        chosen: list[tuple[str, int]] = []
        if config.source_microphone:
            index = config.device_microphone
            if index is None:
                index = devices.get('default_microphone')
            if index is None:
                mics = devices.get('microphones') or []
                index = mics[0]['index'] if mics else None
            if index is None:
                raise RuntimeError('没有找到可用的麦克风设备。')
            chosen.append(('microphone', int(index)))
        if config.source_system:
            index = config.device_loopback
            if index is None:
                index = devices.get('default_loopback')
            if index is None:
                loops = devices.get('loopbacks') or []
                index = loops[0]['index'] if loops else None
            if index is None:
                raise RuntimeError('没有找到可用的系统声音 loopback 设备（可安装 VB-Cable / VoiceMeeter）。')
            chosen.append(('system', int(index)))
        if not chosen:
            raise RuntimeError('请至少启用一个音源：麦克风或系统声音。')
        return chosen

    async def start(self) -> None:
        self._stop.clear()
        self._selected = self._selected_sources()
        self._outbox = asyncio.Queue(maxsize=200)
        self._vad = EnergyVAD()
        self._session_ready = asyncio.Event()
        self._first_error = None
        for source, index in self._selected:
            mailbox = FrameMailbox()
            self._mailboxes[source] = mailbox
            thread = threading.Thread(
                target=self._capture_worker,
                args=(source, index, mailbox),
                name=f'LiveCapture-{source}',
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        self._tasks = [
            asyncio.create_task(self._mix_loop(), name='LiveMix'),
            asyncio.create_task(self._session_supervisor(), name='LiveSessionSupervisor'),
        ]
        # Surface a bad API key / dead upstream as a hard failure so the launcher
        # can offer demo mode instead of a silently dead session.
        await asyncio.wait_for(self._session_ready.wait(), timeout=15)
        if self._first_error is not None:
            raise self._first_error

    async def _open_session(self) -> Any:
        from app.main import sessions  # late import: main imports the live router

        subtitle_source = '+'.join(name for name, _ in self._selected)
        session = sessions.create(
            'live://local-audio',
            video_title=f'跨境直播 · {subtitle_source}',
            input_mode='audio',
            subtitle_source=subtitle_source,
        )
        self.session_id = session.session_id
        self.hub.session_id = session.session_id
        ws = await websockets.connect(
            BACKEND_WS.format(session_id=self.session_id),
            open_timeout=8,
            max_size=4 * 1024 * 1024,
        )
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=8)
            try:
                first_event = json.loads(first)
            except (TypeError, ValueError):
                first_event = {}
            if first_event.get('type') == 'error':
                raise RuntimeError(f"上游会话建立失败：{first_event.get('message') or '未知错误'}")
        except Exception:
            with suppress(Exception):
                await ws.close()
            raise
        self._ws = ws
        # Audio buffered while disconnected is stale; sending a burst into a
        # fresh ASR task would produce garbled captions.
        while True:
            try:
                self._outbox.get_nowait()
            except asyncio.QueueEmpty:
                break
        return ws

    async def _session_supervisor(self) -> None:
        """Keep one live ASR session alive; reconnect it if upstream ends.

        DashScope Streaming ASR ends a task when it receives no audio for a
        while.  main.py's session handler then closes our local WebSocket too,
        which used to kill the whole stream.  Reconnecting here keeps the
        capture threads and the desktop caption window running.
        """
        backoff = 0.4
        first = True
        while not self._stop.is_set():
            ws = None
            try:
                ws = await self._open_session()
                if first:
                    first = False
                    self._session_ready.set()
                self.hub.last_error = ''
                backoff = 0.4
                send_task = asyncio.create_task(self._send_loop(ws), name='LiveAudioSend')
                recv_task = asyncio.create_task(self._recv_loop(ws), name='LiveUpstreamRecv')
                self._session_tasks = [send_task, recv_task]
                done, pending = await asyncio.wait(
                    set(self._session_tasks), return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*self._session_tasks, return_exceptions=True)
                self._session_tasks = []
                for task in done:
                    if not task.cancelled():
                        # Exceptions are already reported by the loops.
                        _ = task.exception()
                if self._stop.is_set():
                    break
                self.hub.metrics['reconnects'] = int(self.hub.metrics.get('reconnects') or 0) + 1
                self.hub.last_error = 'ASR 会话结束，正在自动重连，字幕继续…'
                await asyncio.sleep(backoff)
                backoff = min(4.0, backoff * 1.6)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if first:
                    self._first_error = exc
                    self._session_ready.set()
                    return
                self.hub.last_error = f'ASR 会话重连中：{type(exc).__name__}: {exc}'
                await asyncio.sleep(backoff)
                backoff = min(4.0, backoff * 1.6)
            finally:
                if ws is not None:
                    with suppress(Exception):
                        await ws.close()

    def _capture_worker(self, source: str, index: int, mailbox: FrameMailbox) -> None:
        assembler = FrameAssembler()
        try:
            for raw, rate, channels in capture_frames(index):
                if self._stop.is_set():
                    break
                for frame in assembler.feed(normalize(raw, channels, rate)):
                    mailbox.push(frame)
                    self.hub.metrics['frames_captured'] += 1
        except Exception as exc:
            self.hub.last_error = f'{source} 采集中断：{type(exc).__name__}: {exc}'

    async def _mix_loop(self) -> None:
        last_voice = 0.0
        last_out = time.monotonic()
        while not self._stop.is_set():
            await asyncio.sleep(TICK_SECONDS)
            now = time.monotonic()
            sources = list(self._mailboxes.keys())
            parts = [self._mailboxes[source].pop() for source in sources]
            # Feed the launcher's input meters so the streamer can see which
            # source is actually delivering audio.
            self.hub.metrics['levels'] = {
                source: round(rms(part) if part else 0.0, 4)
                for source, part in zip(sources, parts)
            }
            frame = mix_frames(parts) if any(parts) else None
            if frame is not None:
                self.hub.metrics['frames_total'] += 1
            voice = frame is not None and self._vad.process(frame)
            if voice:
                last_voice = now
                try:
                    self._outbox.put_nowait(auto_gain(frame))
                    last_out = now
                except asyncio.QueueFull:
                    self.hub.metrics['frames_gated'] += 1
                continue
            if frame is not None:
                self.hub.metrics['frames_gated'] += 1

            # Sending nothing during a quiet stretch makes DashScope end the
            # ASR task, which then closes our whole session and stops captions.
            # Keep the upstream fed: continuous silence right after speech (so
            # server-side VAD can finalise the sentence), then sparse silence.
            tail = now - last_voice < SILENCE_TAIL_SECONDS
            if not tail and now - last_out < KEEPALIVE_INTERVAL:
                continue
            silence = b'\x00' * (len(frame) if frame else FRAME_BYTES)
            try:
                self._outbox.put_nowait(silence)
                self.hub.metrics['frames_keepalive'] = int(self.hub.metrics.get('frames_keepalive') or 0) + 1
                last_out = now
            except asyncio.QueueFull:
                pass

    async def _send_loop(self, ws: Any) -> None:
        while not self._stop.is_set():
            try:
                frame = await asyncio.wait_for(self._outbox.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            message = json.dumps({
                'type': 'audio.append',
                'audio': base64.b64encode(frame).decode('ascii'),
            })
            try:
                async with self._send_lock:
                    await ws.send(message)
                self.hub.metrics['frames_sent'] += 1
                self.hub.metrics['asr_seconds'] += TICK_SECONDS
            except Exception as exc:
                if not self._stop.is_set():
                    self.hub.last_error = f'音频上行中断：{type(exc).__name__}: {exc}'
                return

    async def _recv_loop(self, ws: Any) -> None:
        try:
            async for raw in ws:
                if self._stop.is_set():
                    break
                try:
                    event = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                await self.hub.on_upstream_event(event)
        except Exception as exc:
            if not self._stop.is_set():
                self.hub.last_error = f'上游连接断开：{type(exc).__name__}: {exc}'

    async def send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError('音频会话尚未建立。')
        async with self._send_lock:
            await self._ws.send(json.dumps(payload))

    async def stop(self) -> None:
        self._stop.set()
        all_tasks = self._tasks + self._session_tasks
        for task in all_tasks:
            task.cancel()
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._tasks = []
        self._session_tasks = []
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({'type': 'session.close'}))
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads = []
        self._mailboxes.clear()
        self.hub.metrics['vad'] = self._vad.stats
        self.hub.metrics['stopped_at'] = time.time()
