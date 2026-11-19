"""HTTP + WebSocket surface for live mode.

Mounting is a one-line change in ``app/main.py``; every existing endpoint
(``/api/sessions``, ``/ws/sessions/{id}``, ...) keeps its original behaviour.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .hub import hub

router = APIRouter(prefix='/api/live')
ws_router = APIRouter()


class StartRequest(BaseModel):
    mock: bool = False


class InjectRequest(BaseModel):
    source_text: str = ''
    target_text: str = ''


def live_web_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'live' / 'web'
    return Path(__file__).resolve().parents[2] / 'live' / 'web'


_devices_cache: dict[str, Any] = {'at': 0.0, 'value': None}


def cached_devices(force: bool = False) -> dict[str, Any]:
    from .devices import list_devices

    now = time.time()
    if force or _devices_cache['value'] is None or now - float(_devices_cache['at']) > 30:
        _devices_cache['value'] = list_devices()
        _devices_cache['at'] = now
    return _devices_cache['value']


def mount_live(app: FastAPI) -> None:
    app.include_router(router)
    app.include_router(ws_router)
    web_dir = live_web_dir()
    web_dir.mkdir(parents=True, exist_ok=True)
    app.mount('/live', StaticFiles(directory=str(web_dir), html=True), name='live')


@router.get('/status')
async def status() -> dict[str, Any]:
    result = hub.status()
    result['devices'] = cached_devices()
    return result


@router.get('/devices')
async def devices(refresh: bool = False) -> dict[str, Any]:
    return cached_devices(force=refresh)


@router.post('/start')
async def start(payload: StartRequest) -> dict[str, Any]:
    try:
        await hub.start(mock=payload.mock)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = hub.status()
    result['devices'] = cached_devices()
    return result


@router.post('/stop')
async def stop() -> dict[str, Any]:
    await hub.stop()
    result = hub.status()
    result['devices'] = cached_devices()
    return result


@router.post('/config')
async def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    hub.config.update(payload)
    hub.state.config = hub.config
    await hub.broadcast_console({'type': 'state', 'payload': hub.status()})
    result = hub.status()
    result['devices'] = cached_devices()
    return result


@router.post('/inject')
async def inject(payload: InjectRequest) -> dict[str, Any]:
    if hub.mode != 'mock':
        raise HTTPException(status_code=409, detail='只有演示模式允许注入字幕。')
    return await hub.inject_demo(payload.source_text or None, payload.target_text or None)


@router.get('/srt')
async def export_srt() -> PlainTextResponse:
    return PlainTextResponse(
        hub.state.srt() or '',
        media_type='application/x-subrip; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="live-captions.srt"'},
    )


@ws_router.websocket('/ws/live/overlay')
async def overlay_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    hub.attach_overlay(websocket)
    try:
        await websocket.send_json({'type': 'hello', 'payload': hub.status()['config']})
        for caption in hub.state.lines:
            await websocket.send_json(caption.to_event(
                ai_label=hub.config.ai_label,
                label_text=f'AI 实时翻译 · {hub.config.language_name}',
            ))
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.detach_overlay(websocket)


@ws_router.websocket('/ws/live/console')
async def console_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    hub.attach_console(websocket)
    try:
        await websocket.send_json({'type': 'state', 'payload': hub.status()})
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                await hub.handle_console_message(message)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.detach_console(websocket)
