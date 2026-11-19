"""Capture the real desktop caption overlay window with DPI awareness.

Usage: .venv\\Scripts\\python.exe capture_overlay_window.py <output.bmp>
"""
from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

u = ctypes.windll.user32
g = ctypes.windll.gdi32

# Make GetWindowRect / BitBlt agree on physical pixels on scaled displays.
try:
    u.SetProcessDPIAware()
except Exception:
    pass


class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                ('right', wintypes.LONG), ('bottom', wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
        ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', ctypes.c_long), ('biYPelsPerMeter', ctypes.c_long),
        ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [('rgbBlue', ctypes.c_ubyte), ('rgbGreen', ctypes.c_ubyte),
                ('rgbRed', ctypes.c_ubyte), ('rgbReserved', ctypes.c_ubyte)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', RGBQUAD * 1)]


u.GetDC.restype = wintypes.HDC
u.GetDC.argtypes = [wintypes.HWND]
u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
u.FindWindowW.restype = wintypes.HWND
u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
u.GetWindowRect.restype = wintypes.BOOL
g.CreateCompatibleDC.restype = wintypes.HDC
g.CreateCompatibleDC.argtypes = [wintypes.HDC]
g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
g.SelectObject.restype = wintypes.HGDIOBJ
g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
g.BitBlt.restype = wintypes.BOOL
g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                        ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
g.GetDIBits.restype = ctypes.c_int
g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
g.DeleteDC.argtypes = [wintypes.HDC]

SRCCOPY = 0x00CC0020


def main() -> int:
    hwnd = u.FindWindowW('VideoCompanionCaptionOverlay', None)
    if not hwnd:
        print('FAIL: overlay window not found')
        return 1
    rect = RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
        print('FAIL: GetWindowRect')
        return 1
    x, y = rect.left, rect.top
    w, h = rect.right - rect.left, rect.bottom - rect.top
    print(f'overlay hwnd={hwnd} rect={x},{y} {w}x{h} visible={bool(u.IsWindowVisible(hwnd))}')

    screen = u.GetDC(None)
    mem = g.CreateCompatibleDC(screen)
    bitmap = g.CreateCompatibleBitmap(screen, w, h)
    old = g.SelectObject(mem, bitmap)
    if not g.BitBlt(mem, 0, 0, w, h, screen, x, y, SRCCOPY):
        print('FAIL: BitBlt')
        return 1
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    pixels = ctypes.create_string_buffer(w * h * 4)
    rows = g.GetDIBits(mem, bitmap, 0, h, pixels, ctypes.byref(info), 0)
    raw = pixels.raw[:w * h * 4]
    header = b'BM' + struct.pack('<IHHI', 14 + 40 + len(raw), 0, 0, 14 + 40)
    dib = struct.pack('<iiiHHIIiiII', 40, w, -h, 1, 32, 0, len(raw), 0, 0, 0, 0)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('overlay_window.bmp')
    out.write_bytes(header + dib + raw)
    print(f'rows={rows} saved={out}')
    g.SelectObject(mem, old)
    g.DeleteObject(bitmap)
    g.DeleteDC(mem)
    u.ReleaseDC(None, screen)
    return 0


if __name__ == '__main__':
    sys.exit(main())
