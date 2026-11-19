"""Long-run live check: captions must still work AFTER a long quiet stretch.

Regression test for the bug where local VAD sent nothing during silence,
DashScope ended the ASR task, main.py closed the session WebSocket and the
whole caption stream silently died ~20 s into a broadcast.

Usage (from backend/, with the installed EXE already running):
    .venv\\Scripts\\python.exe scripts\\verify_live_longrun.py [quiet_seconds]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import winsound
from pathlib import Path

BASE = 'http://127.0.0.1:8000/api/live'
WAV = Path(__file__).resolve().parents[1] / 'data' / 'tts_en.wav'


def api(path: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'} if payload is not None else {},
        method='POST' if payload is not None else 'GET',
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def snap() -> dict:
    return api('/status')


def wait_for_segment(baseline: int, timeout: float, label: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = snap()
        if status['metrics'].get('segments', 0) > baseline:
            print(f'   {label}: new caption at +{timeout - (deadline - time.monotonic()):.1f}s; '
                  f'on_air={[line.get("text") for line in status.get("on_air", [])]}', flush=True)
            return True
        time.sleep(0.5)
    print(f'   {label}: FAIL - no new caption in {timeout:.0f}s', flush=True)
    return False


def main() -> int:
    quiet = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    print(f'0) TTS file: {WAV.name} exists={WAV.exists()}', flush=True)
    status = snap()
    print(f'   mode={status["mode"]} config mic/system='
          f'{status["config"]["source_microphone"]}/{status["config"]["source_system"]}', flush=True)
    if status['mode'] != 'live':
        print('   starting live mode ...', flush=True)
        api('/start', {'mock': False})
        time.sleep(2)
    base_segments = snap()['metrics'].get('segments', 0)
    base_sent = snap()['metrics'].get('frames_sent', 0)

    print('1) first English utterance ...', flush=True)
    winsound.PlaySound(str(WAV), winsound.SND_FILENAME | winsound.SND_ASYNC)
    if not wait_for_segment(base_segments, 12, 'first'):
        return 1

    print(f'2) staying quiet for {quiet:.0f}s, watching upstream frames ...', flush=True)
    start_sent = snap()['metrics'].get('frames_sent', 0)
    errors: list[str] = []
    for i in range(int(quiet / 10)):
        time.sleep(10)
        s = snap()
        m = s['metrics']
        err = s.get('last_error') or ''
        if err:
            errors.append(f'{(i + 1) * 10}s: {err[:120]}')
        print(f'   t={(i + 1) * 10:>3}s sent={m.get("frames_sent")} '
              f'keepalive={m.get("frames_keepalive")} reconnects={m.get("reconnects")} '
              f'last_error={err[:60]!r}', flush=True)
    end_sent = snap()['metrics'].get('frames_sent', 0)
    if end_sent <= start_sent:
        print('   FAIL: upstream stopped receiving frames during quiet period')
        return 1

    print('3) second English utterance AFTER the quiet stretch ...', flush=True)
    before = snap()['metrics'].get('segments', 0)
    winsound.PlaySound(str(WAV), winsound.SND_FILENAME | winsound.SND_ASYNC)
    if not wait_for_segment(before, 14, 'second'):
        return 1

    final = snap()
    m = final['metrics']
    print(f'4) final: sent {base_sent} -> {m.get("frames_sent")}, '
          f'keepalive={m.get("frames_keepalive")}, reconnects={m.get("reconnects")}, '
          f'segments={m.get("segments")}, last_error={final.get("last_error")!r}', flush=True)
    if errors:
        print('   transient errors seen (auto-recovery):', len(errors), flush=True)
    print('PASS: captions survive a long silent stretch', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
