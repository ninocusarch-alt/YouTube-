"""Native Win32 floating caption window - the desktop twin of the Chrome
extension's floating subtitle panel.

The visual spec is ported 1:1 from ``extension/src/content.ts``
(``.floating-panel`` / ``.panel-header`` / ``.live`` / ``.transcript-item``):

* white 0.96 surface, 1px ``#e7eae8`` dividers, 14px rounded corners
* 48px header with an 8px green status dot, 14px/680 title and 10px status
* deep-ink small type (``#151716`` / ``#252a27`` / ``#68706b``)
* green accents (``#19a66a`` / ``#16875a`` / ``#087b4c``)
* a "正在听" live row plus a bilingual transcript list

A dark cinema-strip theme remains available from the context menu for streams
where a light card would cover the game too much; OBS still captures either
with a display capture.
"""
from __future__ import annotations

import ctypes
import json
import queue
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from launcher.win32_types import LRESULT, WNDPROC, RECT, WNDCLASSEXW

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WM_DESTROY, WM_PAINT, WM_ERASEBKGND = 0x0002, 0x000F, 0x0014
WM_EXITSIZEMOVE = 0x0232
WM_NCHITTEST, WM_LBUTTONDBLCLK, WM_LBUTTONUP, WM_RBUTTONUP = 0x0084, 0x0203, 0x0202, 0x0205
HTCLIENT, HTCAPTION = 1, 2
WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00080000, 0x00000008, 0x000080, 0x08000000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
LWA_ALPHA = 0x00000002
CS_DROPSHADOW = 0x00020000
DT_LEFT, DT_CENTER, DT_RIGHT, DT_VCENTER, DT_SINGLELINE = 0x0000, 0x0001, 0x0002, 0x0004, 0x0020
DT_END_ELLIPSIS, DT_NOPREFIX = 0x8000, 0x0800
TRANSPARENT = 1
FW_BOLD, FW_NORMAL = 700, 400
SM_CXSCREEN, SM_CYSCREEN = 0, 1
MF_STRING, TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x0000, 0x0100, 0x0002
PS_SOLID, NULL_BRUSH, NULL_PEN = 0, 5, 8
ID_HIDE, ID_MINIMAL, ID_CHROMA, ID_ENGLISH, ID_FONT_UP, ID_FONT_DOWN = 301, 302, 303, 304, 305, 306
ID_THEME, ID_RESET = 307, 308

# extension/src/content.ts colours (kept as (r, g, b) so they read like CSS).
PALETTE = {
    'surface':    (0xFF, 0xFF, 0xFF),  # rgba(255,255,255,.96)
    'header':     (0xFA, 0xFB, 0xFA),  # rgba(255,255,255,.72) over white
    'live':       (0xF7, 0xF8, 0xF7),  # rgba(247,248,247,.86)
    'divider':    (0xE7, 0xEA, 0xE8),  # #e7eae8
    'divider_2':  (0xEE, 0xF0, 0xEF),  # #eef0ef
    'outline':    (0xE1, 0xE5, 0xE2),  # rgba(20,27,23,.12) over white
    'ink':        (0x15, 0x17, 0x16),  # #151716
    'ink_2':      (0x19, 0x1D, 0x1A),  # #191d1a
    'ink_soft':   (0x25, 0x2A, 0x27),  # #252a27
    'muted':      (0x68, 0x70, 0x6B),  # #68706b
    'faint':      (0x8B, 0x91, 0x8E),  # #8b918e
    'faint_2':    (0xA0, 0xA5, 0xA2),  # #a0a5a2
    'green':      (0x19, 0xA6, 0x6A),  # #19a66a
    'green_deep': (0x08, 0x7B, 0x4C),  # #087b4c
    'green_label': (0x16, 0x87, 0x5A),  # #16875a
    'halo':       (0xEA, 0xF7, 0xF1),  # rgba(25,166,106,.11)
    'item_bg':    (0xF0, 0xF9, 0xF5),  # #f0f9f5
    'item_border': (0xCB, 0xE9, 0xDA),  # #cbe9da
    'hover':      (0xF0, 0xF3, 0xF1),  # #f0f3f1
    'shadow':     (0xEC, 0xF0, 0xED),
    'idle_dot':   (0xA4, 0xAA, 0xA7),  # #a4aaa7
}

HEADER_H, LIVE_H, SECTION_H = 48, 38, 30
EDGE_GAP = 18  # extension default: bottom margin 18px


class POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ('hdc', wintypes.HDC), ('fErase', wintypes.BOOL), ('rcPaint', RECT),
        ('fRestore', wintypes.BOOL), ('fIncUpdate', wintypes.BOOL),
        ('rgbReserved', ctypes.c_byte * 32),
    ]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
user32.BeginPaint.restype = wintypes.HDC
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(RECT), wintypes.UINT]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), wintypes.HBRUSH]
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
gdi32.CreatePen.restype = wintypes.HGDIOBJ
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetStockObject.restype = wintypes.HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SetTextColor.restype = wintypes.DWORD
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.RoundRect.argtypes = [wintypes.HDC] + [ctypes.c_int] * 6
gdi32.RoundRect.restype = wintypes.BOOL
gdi32.Ellipse.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4
gdi32.Ellipse.restype = wintypes.BOOL
gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SetForegroundWindow.argtypes = [wintypes.HWND]


def rgb(r: int, g: int, b: int) -> int:
    return r | (g << 8) | (b << 16)


def _c(name: str) -> int:
    return rgb(*PALETTE[name])


def _font(size: int, bold: bool = False, family: str = 'Microsoft YaHei UI'):
    # DEFAULT_CHARSET + CLEARTYPE_QUALITY: the old (134 / 3) combination forced
    # GB2312 and NONANTIALIASED, which makes 10-17px type look jagged and turns
    # the Segoe UI English text into a CJK fallback face.
    return gdi32.CreateFontW(-size, 0, 0, 0, FW_BOLD if bold else FW_NORMAL,
                             0, 0, 0, 0, 0, 0, 5, 0, family)


def _rect(left: int, top: int, right: int, bottom: int) -> RECT:
    return RECT(left, top, right, bottom)


class CaptionOverlay:
    """Always-on-top layered window driven by the live hub's overlay events."""

    CLASS_NAME = 'VideoCompanionCaptionOverlay'

    def __init__(self, runtime_dir: Path, hub: Any) -> None:
        self.hub = hub
        self.config_path = Path(runtime_dir) / 'data' / 'caption_overlay.json'
        self.hwnd = 0
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.lines: list[dict[str, str]] = []
        self.visible = False
        self.minimal = False
        self.chroma = False
        self.theme = 'light'          # 'light' = extension card, 'dark' = cinema strip
        self.show_english = True
        self.font_size = 17           # extension default content size
        self.levels: dict[str, float] = {}
        self.running = False
        self.last_level_at = 0.0
        self._x = self._y = 0
        self.callback = WNDPROC(self._proc)
        self._load()

    # ------------------------------------------------------------------ config
    def _load(self) -> None:
        try:
            data = json.loads(self.config_path.read_text(encoding='utf-8'))
            # Legacy configs used a 20-52px cinema-strip font scale. The card
            # theme has its own 12-30px scale, so reset it on first upgrade.
            legacy = 'theme' not in data
            self.minimal = bool(data.get('minimal', False))
            self.chroma = bool(data.get('chroma', False))
            self.theme = data.get('theme', 'light') if data.get('theme') in ('light', 'dark') else 'light'
            self.show_english = bool(data.get('show_english', True))
            self.font_size = 17 if legacy else max(12, min(30, int(data.get('font_size', 17))))
            self._x, self._y = int(data.get('x', 0)), int(data.get('y', 0))
        except (OSError, ValueError, TypeError):
            pass

    def _save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps({
                'x': self._x, 'y': self._y, 'minimal': self.minimal,
                'chroma': self.chroma, 'theme': self.theme,
                'show_english': self.show_english, 'font_size': self.font_size,
            }, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    # ---------------------------------------------------------------- lifecycle
    def create(self) -> None:
        if self.hwnd:
            return
        window_class = WNDCLASSEXW(
            ctypes.sizeof(WNDCLASSEXW), CS_DROPSHADOW, self.callback, 0, 0,
            kernel32.GetModuleHandleW(None), None,
            user32.LoadCursorW(None, 32512), 0, None, self.CLASS_NAME, None,
        )
        user32.RegisterClassExW(ctypes.byref(window_class))
        width = self._width()
        height = self._height()
        screen_w = user32.GetSystemMetrics(SM_CXSCREEN)
        screen_h = user32.GetSystemMetrics(SM_CYSCREEN)
        x = self._x or max(0, (screen_w - width) // 2)
        y = self._y or max(0, screen_h - height - EDGE_GAP)
        # A stale/negative saved position must not strand the window off-screen.
        if not (0 <= x <= screen_w - 120) or not (0 <= y <= screen_h - 80):
            x = max(0, (screen_w - width) // 2)
            y = max(0, screen_h - height - EDGE_GAP)
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            self.CLASS_NAME, 'Video Companion 双语字幕', WS_POPUP,
            x, y, width, height, None, None, kernel32.GetModuleHandleW(None), None,
        )
        if not self.hwnd:
            return
        self._x, self._y = x, y
        self._apply_window_style()
        self.hub.register_local_overlay_sink(self.enqueue)
        user32.ShowWindow(self.hwnd, SW_HIDE)

    def _place_window(self) -> None:
        """Force the card back into the visible screen on every show.

        A frozen windowed EXE can have its popup relocated by the shell (and a
        stale config can hold negative coordinates), which silently leaves the
        caption card off-screen even though IsWindowVisible() is true.
        """
        if not self.hwnd:
            return
        screen_w = user32.GetSystemMetrics(SM_CXSCREEN)
        screen_h = user32.GetSystemMetrics(SM_CYSCREEN)
        width, height = self._width(), self._height()
        x = self._x if 0 <= self._x <= screen_w - 120 else max(0, (screen_w - width) // 2)
        y = self._y if 0 <= self._y <= screen_h - 80 else max(0, screen_h - height - EDGE_GAP)
        self._x, self._y = x, y
        user32.SetWindowPos(self.hwnd, ctypes.c_void_p(-1), x, y, width, height,
                            0x0010 | 0x0020)  # SWP_NOACTIVATE | SWP_FRAMECHANGED

    def _apply_window_style(self) -> None:
        if not self.hwnd:
            return
        self._place_window()
        width, height = self._width(), self._height()
        radius = 14 if self._light() else 18
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius * 2, radius * 2)
        user32.SetWindowRgn(self.hwnd, region, True)
        # CSS uses .96 white + backdrop blur. Win32 layered alpha cannot blur,
        # so the light card is fully opaque; a translucent white would let the
        # game/desktop text bleed through and look dirty on stream.
        alpha = 255 if (self.chroma or self._light()) else 232
        user32.SetLayeredWindowAttributes(self.hwnd, 0, alpha, LWA_ALPHA)

    def _light(self) -> bool:
        return self.theme == 'light' and not self.chroma

    def show(self) -> None:
        self.create()
        if not self.hwnd:
            return
        self.visible = True
        self.running = True
        self._place_window()
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.InvalidateRect(self.hwnd, None, True)

    def hide(self) -> None:
        self.visible = False
        self.running = False
        self.lines.clear()
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_HIDE)

    def destroy(self) -> None:
        self._save()
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = 0

    def enqueue(self, event: dict[str, Any]) -> None:
        """Called from the uvicorn thread; only a thread-safe queue put."""
        try:
            self.events.put_nowait(event)
        except queue.Full:
            pass

    def tick(self) -> None:
        """Called on the launcher UI thread every 200 ms."""
        changed = False
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event.get('type')
            if kind == 'caption.show':
                self.lines.append({
                    'id': str(event.get('id') or ''),
                    'text': str(event.get('text') or ''),
                    'source_text': str(event.get('source_text') or ''),
                })
                self.lines = self.lines[-3:]
                changed = True
            elif kind == 'caption.clear':
                self.lines.clear()
                changed = True
            elif kind == 'caption.hide':
                cid = str(event.get('id') or '')
                self.lines = [line for line in self.lines if line['id'] != cid]
                changed = True
        levels = (getattr(self.hub, 'metrics', {}) or {}).get('levels')
        if isinstance(levels, dict) and levels != self.levels:
            self.levels = dict(levels)
            changed = True
        if changed and self.hwnd and self.visible:
            user32.InvalidateRect(self.hwnd, None, True)

    # ------------------------------------------------------------------ drawing
    def _width(self) -> int:
        return 940  # extension: Math.max(480, Math.min(940, innerWidth - 32))

    def _item_h(self) -> int:
        return max(56, self.font_size * 2 + 24)

    def _height(self) -> int:
        if self.minimal:
            return HEADER_H + 46
        return HEADER_H + LIVE_H + SECTION_H + self._item_h() * 2 + 10

    def _header_buttons(self, width: int) -> list[tuple[int, str, tuple[int, int, int, int]]]:
        right = width - 10
        out = []
        for ident, label in ((ID_HIDE, '×'), (ID_MINIMAL, '−'), (ID_RESET, '↺')):
            left = right - 30
            out.append((ident, label, (left, 9, right, 39)))
            right = left - 3
        return out

    def _proc(self, hwnd: int, msg: int, wp: int, lp: int) -> int:
        if msg == WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_NCHITTEST:
            x, y = self._client_point(hwnd, lp)
            if self._hit_button(self._width(), x, y):
                return HTCLIENT
            return HTCAPTION  # drag anywhere else on the card
        if msg == WM_LBUTTONUP:
            x, y = self._client_point(hwnd, lp)
            hit = self._hit_button(self._width(), x, y)
            if hit:
                self._on_button(hit)
                return 0
        if msg == WM_LBUTTONDBLCLK:
            x, y = self._client_point(hwnd, lp)
            if not self._hit_button(self._width(), x, y):
                self._set_minimal(not self.minimal)
            return 0
        if msg == WM_RBUTTONUP:
            self._context_menu(hwnd)
            return 0
        if msg == WM_EXITSIZEMOVE:
            # Use the real window rect instead of parsing WM_MOVE's lParam;
            # DPI scaling / signed shorts can otherwise persist bogus coords.
            self._remember_position(hwnd)
            return 0
        if msg == WM_DESTROY:
            self.hwnd = 0
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    @staticmethod
    def _client_point(hwnd: int, lp: int) -> tuple[int, int]:
        point = POINT(ctypes.c_short(lp & 0xFFFF).value,
                      ctypes.c_short((lp >> 16) & 0xFFFF).value)
        user32.ScreenToClient(hwnd, ctypes.byref(point))
        return point.x, point.y

    def _hit_button(self, width: int, x: int, y: int) -> int:
        for ident, _label, (left, top, right, bottom) in self._header_buttons(width):
            if left <= x <= right and top <= y <= bottom:
                return ident
        return 0

    def _on_button(self, ident: int) -> None:
        if ident == ID_HIDE:
            self._remember_position(self.hwnd)
            self.hide()
        elif ident == ID_MINIMAL:
            self._set_minimal(not self.minimal)
        elif ident == ID_RESET:
            screen_w = user32.GetSystemMetrics(SM_CXSCREEN)
            screen_h = user32.GetSystemMetrics(SM_CYSCREEN)
            self._x = max(0, (screen_w - self._width()) // 2)
            self._y = max(0, screen_h - self._height() - EDGE_GAP)
            self._apply_window_style()
            self._save()

    # -------------------------------------------------------------- GDI helpers
    def _fill(self, hdc: int, box: tuple[int, int, int, int], color: int) -> None:
        brush = gdi32.CreateSolidBrush(color)
        user32.FillRect(hdc, ctypes.byref(_rect(*box)), brush)
        gdi32.DeleteObject(brush)

    def _line(self, hdc: int, box: tuple[int, int, int, int], color: int) -> None:
        self._fill(hdc, box, color)

    def _round(self, hdc: int, box: tuple[int, int, int, int], radius: int,
               fill: int | None, stroke: int | None) -> None:
        old_brush = old_pen = None
        if fill is None:
            old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_BRUSH))
        else:
            brush = gdi32.CreateSolidBrush(fill)
            old_brush = gdi32.SelectObject(hdc, brush)
        if stroke is None:
            old_pen = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_PEN))
        else:
            pen = gdi32.CreatePen(PS_SOLID, 1, stroke)
            old_pen = gdi32.SelectObject(hdc, pen)
        gdi32.RoundRect(hdc, box[0], box[1], box[2], box[3], radius * 2, radius * 2)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        if stroke is not None:
            gdi32.DeleteObject(pen)
        if fill is not None:
            gdi32.DeleteObject(brush)

    def _circle(self, hdc: int, cx: int, cy: int, radius: int, color: int) -> None:
        brush = gdi32.CreateSolidBrush(color)
        pen = gdi32.CreatePen(PS_SOLID, 1, color)
        old_brush = gdi32.SelectObject(hdc, brush)
        old_pen = gdi32.SelectObject(hdc, pen)
        gdi32.Ellipse(hdc, cx - radius, cy - radius, cx + radius, cy + radius)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.DeleteObject(pen)
        gdi32.DeleteObject(brush)

    def _draw_text(self, hdc: int, text: str, box: tuple[int, int, int, int],
                   size: int, color: int, *, bold: bool = False,
                   family: str = 'Microsoft YaHei UI', align: str = 'left',
                   outline: bool = False) -> None:
        if not text:
            return
        font = _font(size, bold, family)
        old = gdi32.SelectObject(hdc, font)
        gdi32.SetBkMode(hdc, TRANSPARENT)
        flags = DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX
        flags |= DT_CENTER if align == 'center' else DT_RIGHT if align == 'right' else DT_LEFT
        buffer = ctypes.create_unicode_buffer(text)
        if outline:
            gdi32.SetTextColor(hdc, rgb(0, 0, 0))
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1)):
                r = _rect(box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
                user32.DrawTextW(hdc, buffer, -1, ctypes.byref(r), flags)
        gdi32.SetTextColor(hdc, color)
        r = _rect(*box)
        user32.DrawTextW(hdc, buffer, -1, ctypes.byref(r), flags)
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(font)

    def _level_bar(self, hdc: int, x: int, y: int, width: int, height: int) -> None:
        """Two hairline meters, matching the extension's quiet status styling."""
        parts = [('microphone', _c('green')), ('system', rgb(0x60, 0xB0, 0xF0))]
        segment = width // 2 - 6
        for index, (key, color) in enumerate(parts):
            left = x + index * (segment + 12)
            self._fill(hdc, (left, y, left + segment, y + height), _c('divider'))
            level = float(self.levels.get(key, 0.0) or 0.0)
            filled = max(0, min(segment, int(segment * min(1.0, level * 12))))
            if filled:
                self._fill(hdc, (left, y, left + filled, y + height), color)

    # ------------------------------------------------------------------- themes
    def _paint(self, hwnd: int) -> None:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        if not hdc:
            return
        try:
            client = RECT()
            user32.GetClientRect(hwnd, ctypes.byref(client))
            w, h = client.right, client.bottom
            if self._light():
                self._paint_card(hdc, w, h)
            else:
                self._paint_strip(hdc, w, h)
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))

    def _paint_card(self, hdc: int, w: int, h: int) -> None:
        """1:1 desktop port of .floating-panel / .subtitle-panel."""
        self._fill(hdc, (0, 0, w, h), _c('surface'))
        self._fill(hdc, (0, 0, w, HEADER_H), _c('header'))

        # status dot + halo, header title and status copy
        self._circle(hdc, 20, 24, 8, _c('halo'))
        self._circle(hdc, 20, 24, 4, _c('green') if self.running else _c('idle_dot'))
        self._draw_text(hdc, 'Video Companion', (36, 7, 320, 27), 14, _c('ink'),
                        bold=True, family='Segoe UI')
        status = '实时翻译中 · English → 中文' if self.running else '等待启动'
        self._draw_text(hdc, status, (36, 27, w - 140, 45), 10, _c('faint'))

        # header icon buttons: ↺  −  × (transparent until hovered, like the CSS)
        for _ident, label, (left, top, right, bottom) in self._header_buttons(w):
            self._draw_text(hdc, label, (left, top, right, bottom), 17,
                            rgb(0x5E, 0x65, 0x61), family='Segoe UI', align='center')

        self._line(hdc, (0, HEADER_H - 1, w, HEADER_H), _c('divider'))

        # "正在听" live row with the newest English line and hairline meters
        live_bottom = HEADER_H + LIVE_H
        if not self.minimal:
            self._fill(hdc, (0, HEADER_H, w, live_bottom), _c('live'))
            self._draw_text(hdc, '正在听', (15, HEADER_H + 7, 56, live_bottom - 3),
                            10, _c('green_label'))
            live_text = (self.lines[-1].get('source_text') if self.lines else '') or '等待语音…'
            self._draw_text(hdc, live_text, (62, HEADER_H + 4, w - 120, live_bottom - 3),
                            max(12, min(16, self.font_size)), _c('ink_soft'),
                            family='Segoe UI')
            self._level_bar(hdc, w - 15 - 88, HEADER_H + 17, 88, 4)
            self._line(hdc, (0, live_bottom - 1, w, live_bottom), _c('divider_2'))
        else:
            # collapsed: one compact Chinese line, like a docked caption strip
            latest = self.lines[-1].get('text') if self.lines else ''
            self._draw_text(hdc, latest or '等待英文语音…',
                            (16, HEADER_H + 2, w - 16, HEADER_H + 42),
                            max(16, self.font_size + 4), _c('ink'), bold=bool(latest))

        if self.minimal:
            self._draw_border(hdc, w, h)
            return

        # "双语记录" section head
        section_top = live_bottom
        self._draw_text(hdc, '双语记录', (14, section_top + 5, 200, section_top + 27),
                        12, _c('ink'), bold=True)
        self._draw_text(hdc, '麦克风 + 系统声音', (w - 170, section_top + 6, w - 14, section_top + 26),
                        10, _c('faint'), align='right')

        items = self.lines[-2:]
        item_h = self._item_h()
        y = section_top + SECTION_H
        if not items:
            self._draw_text(hdc, '双语内容将在这里持续累积',
                            (14, y + 12, w - 14, y + 48), 11, _c('faint_2'), align='center')
        for index, line in enumerate(items):
            latest = index == len(items) - 1
            box = (8, y, w - 8, y + item_h - 4)
            if latest:
                self._round(hdc, box, 10, _c('item_bg'), _c('item_border'))
                self._fill(hdc, (11, y + 10, 14, y + item_h - 14), _c('green'))
            en = line.get('source_text', '') if self.show_english else ''
            zh = line.get('text', '')
            if en:
                self._draw_text(hdc, en, (22, y + 6, w - 22, y + 28),
                                self.font_size, _c('ink_2'), family='Segoe UI')
                self._draw_text(hdc, zh, (22, y + 29, w - 22, y + item_h - 10),
                                max(12, self.font_size - 1),
                                _c('ink_soft') if latest else _c('muted'), bold=latest)
            else:
                self._draw_text(hdc, zh, (22, y + 6, w - 22, y + item_h - 10),
                                self.font_size + 1, _c('ink'), bold=latest)
            y += item_h

        self._draw_border(hdc, w, h)

    def _draw_border(self, hdc: int, w: int, h: int) -> None:
        self._fill(hdc, (2, h - 3, w - 2, h), _c('shadow'))
        self._round(hdc, (0, 0, w - 1, h - 1), 14, None, _c('outline'))

    def _paint_strip(self, hdc: int, w: int, h: int) -> None:
        """Dark cinema-strip theme kept for OBS chroma-key / low-light games."""
        bg = rgb(0, 0, 0) if self.chroma else rgb(14, 19, 26)
        self._fill(hdc, (0, 0, w, h), bg)
        zh_lines = [line['text'] for line in self.lines if line.get('text')][-2:]
        en_line = self.lines[-1].get('source_text', '') if self.lines else ''
        if not self.minimal:
            label = '● AI 实时翻译 · English → 中文' if self.running else '○ 跨境直播字幕'
            self._draw_text(hdc, label, (18, 6, 380, 28), 13, rgb(126, 214, 173))
            self._level_bar(hdc, w - 176, 14, 158, 10)
            if not zh_lines:
                self._draw_text(hdc, '等待英文语音…', (18, 34, w - 18, h - 34),
                                20, rgb(120, 132, 142))
        top = 12 if self.minimal else 34
        big = max(20, self.font_size + 12)
        line_h = big + 12
        for index, text in enumerate(zh_lines):
            box = (18, top + index * line_h, w - 18, top + (index + 1) * line_h)
            self._draw_text(hdc, text, box, big, rgb(255, 255, 255),
                            bold=True, outline=True)
        if not self.minimal and self.show_english and en_line:
            y = top + max(1, len(zh_lines)) * line_h + 2
            self._draw_text(hdc, en_line, (18, y, w - 18, y + 28),
                            16, rgb(176, 189, 199))

    # ------------------------------------------------------------------- menu
    def _context_menu(self, hwnd: int) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        entries = [
            (ID_THEME, '切换：插件白卡片 / 深色字幕条'),
            (ID_HIDE, '隐藏字幕浮层（重新开启直播可再显示）'),
            (ID_MINIMAL, '切换：收起 / 完整卡片'),
            (ID_CHROMA, '切换：透明 / OBS 色键黑底'),
            (ID_ENGLISH, '切换：显示英文原文'),
            (ID_FONT_UP, '字号 +'),
            (ID_FONT_DOWN, '字号 −'),
        ]
        for item, label in entries:
            user32.AppendMenuW(menu, MF_STRING, item, label)
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        command = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                        point.x, point.y, 0, hwnd, None)
        user32.DestroyMenu(menu)
        if command == ID_HIDE:
            self._remember_position(hwnd)
            self.hide()
        elif command == ID_MINIMAL:
            self._set_minimal(not self.minimal)
        elif command == ID_THEME:
            self.theme = 'dark' if self.theme == 'light' else 'light'
            self._apply_window_style()
            self._save()
            user32.InvalidateRect(hwnd, None, True)
        elif command == ID_CHROMA:
            self.chroma = not self.chroma
            self._apply_window_style()
            self._save()
            user32.InvalidateRect(hwnd, None, True)
        elif command == ID_ENGLISH:
            self.show_english = not self.show_english
            self._save()
            user32.InvalidateRect(hwnd, None, True)
        elif command in (ID_FONT_UP, ID_FONT_DOWN):
            self.font_size = max(12, min(30, self.font_size + (2 if command == ID_FONT_UP else -2)))
            self._apply_window_style()
            self._save()
            user32.InvalidateRect(hwnd, None, True)

    def _set_minimal(self, value: bool) -> None:
        self.minimal = value
        if self.hwnd:
            self._apply_window_style()
            self._save()
            user32.InvalidateRect(self.hwnd, None, True)

    def _remember_position(self, hwnd: int) -> None:
        rect = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            self._x, self._y = rect.left, rect.top
            self._save()
