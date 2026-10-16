"""Windows app switcher: list Alt+Tab-style windows (with icons) and switch / minimize / maximize / close them."""
from __future__ import annotations

import base64
import ctypes
import io
from ctypes import wintypes

import numpy as np
from PIL import Image

from . import input_win

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

GW_OWNER, GWL_EXSTYLE = 4, -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000
DWMWA_CLOAKED = 14
WM_GETICON, WM_CLOSE = 0x7F, 0x0010
ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0, 1, 2
GCLP_HICON, GCLP_HICONSM = -14, -34
SMTO_ABORTIFHUNG = 0x2
SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DI_NORMAL = 3
ICON_PX = 40

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.IsIconic.argtypes = (wintypes.HWND,)
user32.IsZoomed.argtypes = (wintypes.HWND,)
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.SendMessageTimeoutW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
user32.GetClassLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.GetClassLongPtrW.restype = ctypes.c_size_t
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = (wintypes.HWND,)
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.DrawIconEx.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT, wintypes.HBRUSH, wintypes.UINT)
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
kernel32.OpenProcess.restype = wintypes.HANDLE
dwmapi.DwmGetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


gdi32.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)

_icon_cache: dict[str, str] = {}


def _title(h) -> str:
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def _exe(h) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    hp = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not hp:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        kernel32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n))
        return buf.value
    finally:
        kernel32.CloseHandle(hp)


def _is_switchable(h) -> bool:
    """Roughly the same rules Alt+Tab uses."""
    if not user32.IsWindowVisible(h) or user32.GetWindowTextLengthW(h) == 0:
        return False
    ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
    if user32.GetWindow(h, GW_OWNER) and not ex & WS_EX_APPWINDOW:
        return False
    if ex & WS_EX_TOOLWINDOW:
        return False
    cloaked = wintypes.DWORD()
    dwmapi.DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(cloaked), 4)
    if cloaked.value:          # hidden UWP windows, other virtual desktops
        return False
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(h, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return False
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    if not user32.IsIconic(h) and (r.right - r.left <= 1 or r.bottom - r.top <= 1):
        return False           # invisible 0x0 helper windows (e.g. UltraViewer)
    return True


def _hicon(h):
    res = ctypes.c_size_t()
    for kind in (ICON_BIG, ICON_SMALL2, ICON_SMALL):
        if user32.SendMessageTimeoutW(h, WM_GETICON, kind, 0, SMTO_ABORTIFHUNG, 80, ctypes.byref(res)) and res.value:
            return res.value
    return user32.GetClassLongPtrW(h, GCLP_HICON) or user32.GetClassLongPtrW(h, GCLP_HICONSM)


def _render(hicon, background: int) -> np.ndarray:
    """Draw the icon onto a solid background, return BGRA pixels."""
    hdc_screen = user32.GetDC(None)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=ICON_PX, biHeight=-ICON_PX,
                           biPlanes=1, biBitCount=32, biCompression=0)
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(hdc, hbmp)
    try:
        ctypes.memset(bits, background, ICON_PX * ICON_PX * 4)
        user32.DrawIconEx(hdc, 0, 0, hicon, ICON_PX, ICON_PX, 0, None, DI_NORMAL)
        return np.frombuffer(ctypes.string_at(bits, ICON_PX * ICON_PX * 4), np.uint8).reshape(ICON_PX, ICON_PX, 4).copy()
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(None, hdc_screen)


def _icon_png(hicon) -> str | None:
    """Icon -> base64 PNG. Drawing on black and on white recovers transparency for every icon format."""
    try:
        black = _render(hicon, 0x00).astype(np.int16)
        white = _render(hicon, 0xFF).astype(np.int16)
    except Exception:
        return None
    alpha = np.clip(255 - (white[:, :, :3] - black[:, :, :3]).max(axis=2), 0, 255)
    rgb = np.zeros((ICON_PX, ICON_PX, 3), np.float32)
    nz = alpha > 0
    rgb[nz] = black[:, :, 2::-1][nz] * 255.0 / alpha[nz, None]   # un-premultiply, BGR -> RGB
    img = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha.astype(np.uint8)])
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def list_windows(have_icons: set[str] | None = None) -> dict:
    """Open windows in Alt+Tab order. Icons are sent once per app (the phone caches them by key)."""
    have_icons = have_icons or set()
    found = []

    @WNDENUMPROC
    def cb(h, _):
        if _is_switchable(h):
            found.append(h)
        return True

    user32.EnumWindows(cb, 0)
    fg = user32.GetForegroundWindow()
    wins, icons = [], {}
    for h in found:
        exe = _exe(h)
        name = exe.rsplit("\\", 1)[-1].removesuffix(".exe") if exe else ""
        key = exe.lower() or f"hwnd{h}"
        if name.lower() == "applicationframehost":   # UWP apps share one host process: key icons by title
            key, name = "uwp:" + _title(h).lower(), ""
        if key not in _icon_cache:
            hi = _hicon(h)
            _icon_cache[key] = (_icon_png(hi) if hi else None) or ""
        if _icon_cache[key] and key not in have_icons:
            icons[key] = _icon_cache[key]
        wins.append({"id": int(h), "title": _title(h)[:120], "app": name, "icon": key if _icon_cache[key] else None,
                     "min": bool(user32.IsIconic(h)), "max": bool(user32.IsZoomed(h)), "active": h == fg})
    return {"windows": wins, "icons": icons}


def _activate(h):
    if user32.IsIconic(h):
        user32.ShowWindow(h, SW_RESTORE)
    # Windows only lets the foreground app hand over focus; briefly join its input queue to be allowed
    fg = user32.GetForegroundWindow()
    me = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(fg_tid and fg_tid != me and user32.AttachThreadInput(me, fg_tid, True))
    try:
        user32.BringWindowToTop(h)
        ok = user32.SetForegroundWindow(h)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_tid, False)
    if not ok or user32.GetForegroundWindow() != h:
        # fallback: a synthetic Alt press satisfies the foreground-lock rules
        input_win.hotkey("alt")
        user32.SetForegroundWindow(h)


def window_action(hwnd: int, action: str) -> bool:
    h = wintypes.HWND(hwnd)
    if not user32.IsWindow(h):
        return False
    if action == "focus":
        _activate(h)
    elif action == "min":
        user32.ShowWindow(h, SW_MINIMIZE)
    elif action == "max":
        user32.ShowWindow(h, SW_RESTORE if user32.IsZoomed(h) else SW_MAXIMIZE)
        _activate(h)
    elif action == "close":
        user32.PostMessageW(h, WM_CLOSE, 0, 0)   # polite close: apps can still ask to save
    return True
