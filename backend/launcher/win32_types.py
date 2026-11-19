"""Shared ctypes Win32 types.

Both the launcher main window and the caption overlay register window classes
through the SAME user32.RegisterClassExW function object.  Defining
WNDCLASSEXW twice made the second module overwrite ``argtypes`` with a
different (though layout-identical) structure type, and the overlay's
registration then raised a ctypes ArgumentError inside WM_CREATE - which a
windowed PyInstaller build silently swallows. Always use these shared types.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT), ('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR),
        ('hIconSm', wintypes.HICON),
    ]


class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                ('right', wintypes.LONG), ('bottom', wintypes.LONG)]
