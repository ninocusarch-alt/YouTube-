"""End-to-end smoke test for live mode (no API key, no microphone required).

Start the backend first, then run:

    .venv\\Scripts\\python.exe scripts\\live_smoke.py

It exercises the real HTTP + WebSocket surface in demo mode: start -> inject
an English line -> OBS overlay receives one whole Chinese caption -> console
chat.ask -> hide -> stop.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import websockets

# The installed EXE owns port 8000; use LIVE_SMOKE_PORT to validate the source
# checkout side by side without interrupting the running product.
PORT = int(os.environ.get('LIVE_SMOKE_PORT', '8000'))
BASE = f'http://127.0.0.1:{PORT}'
WS = f'ws://127.0.0.1:{PORT}'
ENGLISH = 'We should rotate mid before they collapse on us.'
CHINESE = '我们应该先转中路，别被他们包夹。'


async def until(websocket, wanted: str, timeout: float = 4.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(f'no {wanted} frame within {timeout}s')
        raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        message = json.loads(raw)
        if message.get('type') == wanted:
            return message


async def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    async with httpx.AsyncClient(timeout=10) as client:
        health = await client.get(f'{BASE}/api/health')
        checks.append(('backend health', health.status_code == 200, str(health.status_code)))

        page = await client.get(f'{BASE}/live/overlay.html')
        checks.append(('OBS overlay page served', page.status_code == 200 and 'id="lines"' in page.text, str(page.status_code)))
        console_page = await client.get(f'{BASE}/live/console.html')
        checks.append(('streamer console served', console_page.status_code == 200, str(console_page.status_code)))

        started = await client.post(f'{BASE}/api/live/start', json={'mock': True})
        checks.append(('demo mode started', started.status_code == 200 and started.json().get('mode') == 'mock', str(started.status_code)))

        async with websockets.connect(f'{WS}/ws/live/overlay') as overlay, \
                   websockets.connect(f'{WS}/ws/live/console') as console:
            hello = await until(overlay, 'hello')
            checks.append(('overlay hello', bool(hello.get('payload')), 'ok'))
            state = await until(console, 'state')
            checks.append(('console state', state['payload'].get('mode') == 'mock', 'ok'))

            injected = await client.post(
                f'{BASE}/api/live/inject',
                json={'source_text': ENGLISH, 'target_text': CHINESE},
            )
            checks.append(('English line injected', injected.status_code == 200, str(injected.status_code)))

            shown = await until(overlay, 'caption.show')
            checks.append(('one whole Chinese caption on air', shown.get('text') == CHINESE, shown.get('text', '')))
            checks.append(('AI label present (compliance)', shown.get('ai_label') is True, str(shown.get('ai_label'))))
            checks.append(('source text attached', shown.get('source_text') == ENGLISH, 'ok'))

            await console.send(json.dumps({
                'type': 'chat.ask',
                'question': 'rotate 在这句话里是什么意思？',
                'selected_text': ENGLISH,
                'request_id': 'smoke-1',
            }))
            answer = await until(console, 'chat.answer')
            checks.append(('Agent answer delivered', 'rotate' not in answer.get('answer', '') or ENGLISH in answer.get('answer', ''), answer.get('answer', '')[:40]))

            await console.send(json.dumps({'type': 'hide'}))
            cleared = await until(overlay, 'caption.clear')
            checks.append(('one-click hide', cleared.get('type') == 'caption.clear', 'ok'))

        srt = await client.get(f'{BASE}/api/live/srt')
        checks.append(('SRT export', '转中路' in srt.text, f'{len(srt.text)} chars'))
        stopped = await client.post(f'{BASE}/api/live/stop', json={})
        checks.append(('clean stop', stopped.json().get('mode') == 'idle', stopped.json().get('mode', '')))

    for name, ok, detail in checks:
        print(f'{"PASS" if ok else "FAIL"}  {name:38s} {detail}')
    failed = [name for name, ok, _ in checks if not ok]
    print(f'\n{len(checks) - len(failed)}/{len(checks)} checks passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
