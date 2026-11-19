"""Verify the installed EXE really exposes the live-mode button.

Launches nothing itself; point it at a running VideoCompanionBackend.exe.
Enumerates native Win32 child windows and checks the button captions, then
probes the HTTP endpoints served by the frozen app.
"""
from __future__ import annotations

import ctypes
import json
import sys
import urllib.request
from ctypes import wintypes

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

TITLE = 'Real-time AI Video Companion'
EXPECTED_BUTTONS = [
    '启动服务', '停止服务', '重新启动', '开机启动', '配置 API Key',
    '打开健康检查', '安装 / 更新 Chrome 插件', '开启跨境直播模式',
]


def window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def find_main_window() -> int | None:
    found: list[int] = []

    def callback(hwnd, _):
        if TITLE in window_text(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None


def child_buttons(hwnd: int) -> list[str]:
    labels: list[str] = []

    def callback(child, _):
        if class_name(child) == 'Button':
            labels.append(window_text(child))
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(callback), 0)
    return labels


def get(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:8000{path}', timeout=5) as response:
            return response.status, response.read().decode('utf-8', 'ignore')[:300]
    except Exception as exc:
        return 0, f'{type(exc).__name__}: {exc}'


def main() -> int:
    hwnd = find_main_window()
    if hwnd is None:
        print('FAIL: main launcher window not found (is the EXE running?)')
        return 1
    print(f'main window hwnd={hwnd} title="{window_text(hwnd)}"')
    buttons = child_buttons(hwnd)
    print(f'buttons found ({len(buttons)}):')
    for label in buttons:
        print(f'   - {label}')

    missing = [name for name in EXPECTED_BUTTONS if not any(name in b for b in buttons)]
    live_button = [b for b in buttons if '跨境直播' in b]
    print(f'live button   : {live_button or "MISSING"}')
    print(f'missing legacy: {missing or "none"}')

    print('http probes:')
    for path in ['/api/health', '/api/live/status', '/live/overlay.html', '/live/console.html']:
        status, body = get(path)
        print(f'   {path:24s} {status}  {body[:80]}')

    ok = bool(live_button) and not missing and get('/api/live/status')[0] == 200
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
