"""End-to-end check for the native desktop caption overlay (no browser).

Usage (from backend/):
    .venv\\Scripts\\python.exe scripts\\verify_desktop_overlay.py
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
import urllib.request
import winsound
from ctypes import wintypes
from pathlib import Path

class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                ('right', wintypes.LONG), ('bottom', wintypes.LONG)]


u = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.IsWindowVisible.argtypes = [wintypes.HWND]
u.IsWindowVisible.restype = wintypes.BOOL
u.SendMessageW.restype = ctypes.c_ssize_t
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
u.GetWindowRect.restype = wintypes.BOOL

BM_CLICK, BM_GETCHECK = 0x00F5, 0x00F0
PORT = 8000
BASE = f'http://127.0.0.1:{PORT}'
OVERLAY_CLASS = 'VideoCompanionCaptionOverlay'


def text(h: int) -> str:
    n = u.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, buf, n + 1)
    return buf.value


def main_window() -> int:
    found: list[int] = []

    @EnumWindowsProc
    def top(h, _):
        if text(h) == 'Real-time AI Video Companion' and u.IsWindowVisible(h):
            found.append(h)
        return True

    u.EnumWindows(top, 0)
    return found[0] if found else 0


def controls(h: int) -> dict[int, str]:
    out: dict[int, str] = {}

    @EnumChildProc
    def child(c, _):
        out[u.GetDlgCtrlID(c)] = text(c)
        return True

    u.EnumChildWindows(h, child, 0)
    return out


def click(h: int, item: int) -> None:
    @EnumChildProc
    def child(c, _):
        if u.GetDlgCtrlID(c) == item:
            u.SendMessageW(c, BM_CLICK, 0, 0)
        return True

    u.EnumChildWindows(h, child, 0)


def api(path: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'} if payload is not None else {},
        method='POST' if payload is not None else 'GET',
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def overlay_hwnd() -> int:
    return int(u.FindWindowW(OVERLAY_CLASS, None) or 0)


def main() -> int:
    print('1) waiting for the launcher window ...', flush=True)
    deadline = time.monotonic() + 25
    hwnd = 0
    while time.monotonic() < deadline:
        hwnd = main_window()
        if hwnd:
            break
        time.sleep(0.2)
    if not hwnd:
        print('FAIL: launcher window never appeared')
        return 1
    ctrl = controls(hwnd)
    buttons = {k: v for k, v in ctrl.items() if k >= 101}
    print(f'   controls: {len(buttons)} buttons/checkboxes -> {sorted(buttons)}', flush=True)
    for item in (109, 110, 111):
        if item not in buttons:
            print(f'FAIL: missing checkbox {item}')
            return 1
    print('   live button:', buttons.get(108), flush=True)

    print('2) clicking 开启跨境直播模式 ...', flush=True)
    click(hwnd, 108)

    live = False
    overlay_ok = False
    for i in range(50):
        time.sleep(0.4)
        if not u.IsWindow(hwnd):
            print(f'FAIL at t={i * 0.4:.1f}s: launcher window disappeared (native crash)')
            return 1
        try:
            status = api('/api/live/status')
        except Exception:
            status = {'mode': 'unreachable', 'metrics': {}}
        h_overlay = overlay_hwnd()
        overlay_visible = bool(h_overlay and u.IsWindowVisible(h_overlay))
        if overlay_visible:
            overlay_ok = True
        if status.get('mode') == 'live':
            live = True
        label = controls(hwnd).get(108, '')
        if i in (2, 6, 12, 49):
            print(f'   t={i * 0.4:>4.1f}s button={label!r} mode={status.get("mode")} '
                  f'overlay_visible={overlay_visible} levels={status.get("metrics", {}).get("levels")}', flush=True)
        if live and overlay_ok and label.startswith('■'):
            break
    if not live:
        print('FAIL: live mode never started')
        return 1
    if not overlay_ok:
        print('FAIL: native caption window never became visible')
        return 1
    print('   PASS: live mode + native overlay visible, no browser opened', flush=True)

    status = api('/api/live/status')
    config = status['config']
    print(f'3) sources: mic={config["source_microphone"]}, system={config["source_system"]}', flush=True)
    if not (config['source_microphone'] and config['source_system']):
        print('FAIL: both audio sources should be enabled by default')
        return 1
    levels = status['metrics'].get('levels') or {}
    print(f'   live input levels: {levels}', flush=True)
    if not levels:
        print('FAIL: no input level meters')
        return 1

    wav = Path(__file__).resolve().parents[1] / 'data' / 'tts_en.wav'
    print(f'4) playing English speech ({wav.name}) ...', flush=True)
    winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
    shown = False
    for i in range(45):
        time.sleep(0.5)
        status = api('/api/live/status')
        if status.get('on_air'):
            print(f'   caption on air at t={i * 0.5:.1f}s:', flush=True)
            for line in status['on_air']:
                print(f'     EN: {line.get("source_text")}')
                print(f'     ZH: {line.get("text")}')
            shown = True
            break
    if not shown:
        print('   FAIL: no caption produced', flush=True)
        return 1

    # Persist the overlay rectangle so a screenshot can be taken right after.
    h_overlay = overlay_hwnd()
    if h_overlay:
        rect = RECT()
        if u.GetWindowRect(h_overlay, ctypes.byref(rect)):
            Path(os.environ['TEMP'], 'overlay_rect.txt').write_text(
                f'{rect.left},{rect.top},{rect.right - rect.left},{rect.bottom - rect.top}'
            )
    print('PASS: native overlay + both audio sources + real EN->ZH caption', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
