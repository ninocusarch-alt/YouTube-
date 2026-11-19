"""Grab a screen rectangle with plain Win32 GDI and save a 32-bit BMP."""
import ctypes
import os
import struct
import sys
from ctypes import wintypes
from pathlib import Path

u = ctypes.windll.user32
g = ctypes.windll.gdi32


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
    rect_file = Path(os.environ['TEMP']) / 'overlay_rect.txt'
    if not rect_file.exists():
        print('no rect file')
        return 1
    x, y, w, h = (int(v) for v in rect_file.read_text().strip().split(','))
    screen = u.GetDC(None)
    mem = g.CreateCompatibleDC(screen)
    bitmap = g.CreateCompatibleBitmap(screen, w, h)
    old = g.SelectObject(mem, bitmap)
    if not g.BitBlt(mem, 0, 0, w, h, screen, x, y, SRCCOPY):
        print('BitBlt failed')
        return 1
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h  # top-down
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    pixels = ctypes.create_string_buffer(w * h * 4)
    rows = g.GetDIBits(mem, bitmap, 0, h, pixels, ctypes.byref(info), 0)
    raw = pixels.raw[:w * h * 4]
    header = b'BM' + struct.pack('<IHHI', 14 + 40 + len(raw), 0, 0, 14 + 40)
    dib = struct.pack('<iiiHHIIiiII', 40, w, -h, 1, 32, 0, len(raw), 0, 0, 0, 0)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('overlay_preview.bmp')
    out.write_bytes(header + dib + raw)
    print(f'rows={rows} saved={out} ({w}x{h} at {x},{y})')
    g.SelectObject(mem, old)
    g.DeleteObject(bitmap)
    g.DeleteDC(mem)
    u.ReleaseDC(None, screen)
    return 0


if __name__ == '__main__':
    sys.exit(main())
