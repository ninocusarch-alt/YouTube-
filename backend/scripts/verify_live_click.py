"""Reproduce the exact user path: start EXE -> click live button immediately.

Usage: python verify_live_click.py <pid>
"""
from __future__ import annotations

import ctypes
import json
import sys
import time
import urllib.request
from ctypes import wintypes

u = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
BM_CLICK = 0x00F5
PORT = 8000


def text(h: int) -> str:
    n = u.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, b, n + 1)
    return b.value


def find_window() -> int:
    found: list[int] = []

    @EnumWindowsProc
    def top(h, l):
        if text(h) == 'Real-time AI Video Companion' and u.IsWindowVisible(h):
            found.append(h)
        return True

    u.EnumWindows(top, 0)
    return found[0] if found else 0


def controls(h: int) -> dict[int, tuple[str, bool]]:
    out: dict[int, tuple[str, bool]] = {}

    @EnumChildProc
    def child(c, l):
        out[u.GetDlgCtrlID(c)] = (text(c), bool(u.IsWindowEnabled(c)))
        return True

    u.EnumChildWindows(h, child, 0)
    return out


def click(h: int, item: int) -> bool:
    hit = []

    @EnumChildProc
    def child(c, l):
        if u.GetDlgCtrlID(c) == item:
            hit.append(c)
        return True

    u.EnumChildWindows(h, child, 0)
    if not hit:
        return False
    u.SendMessageW(hit[0], BM_CLICK, 0, 0)
    return True


def api(path: str, payload: dict | None = None):
    url = f'http://127.0.0.1:{PORT}{path}'
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST'
        )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def main() -> int:
    print('waiting for launcher window ...', flush=True)
    deadline = time.monotonic() + 20
    hwnd = 0
    while time.monotonic() < deadline:
        hwnd = find_window()
        if hwnd:
            break
        time.sleep(0.2)
    if not hwnd:
        print('FAIL: no launcher window (process exited / crashed)')
        return 1
    print(f'window hwnd={hwnd}', flush=True)

    # Click as early as possible: the initial service start is still in flight,
    # which used to make the click silently disappear.
    time.sleep(0.45)
    ok = click(hwnd, 108)
    print(f'click ID_LIVE sent={ok}', flush=True)
    if not ok:
        print('FAIL: button not found')
        return 1
    time.sleep(0.3)
    print('button right after click:', controls(hwnd).get(108), flush=True)

    for i in range(40):
        time.sleep(0.5)
        if not u.IsWindow(hwnd) or not find_window():
            print(f'FAIL at t={i * 0.5:.1f}s: window disappeared (native crash)')
            return 1
        label = controls(hwnd).get(108, ('', False))[0]
        try:
            status = api('/api/live/status')
        except Exception:
            status = {'mode': 'unreachable'}
        if i in (1, 3, 7, 15, 39):
            print(f'  t={i * 0.5:>4.1f}s button={label!r} mode={status.get("mode")} '
                  f'frames={status.get("metrics", {}).get("frames_captured")}', flush=True)
        if label.startswith('■') and status.get('mode') == 'live' and status['metrics'].get('frames_captured', 0) > 0:
            print(f'PASS at t={i * 0.5:.1f}s: click path survived, real capture running', flush=True)
            print('final button:', controls(hwnd).get(108), flush=True)
            return 0
    print('FAIL: never reached live capture state', flush=True)
    print('final controls:', controls(hwnd), flush=True)
    return 1


if __name__ == '__main__':
    sys.exit(main())
