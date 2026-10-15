"""Windows system controls: clipboard, media keys, volume, brightness, power.

Functions here may block (COM, WMI), so the server calls them on its system thread.
"""
from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes

from . import input_win

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = (wintypes.UINT,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)


def thread_init():
    """COM (volume control) must be initialised on the thread that uses it."""
    import comtypes
    comtypes.CoInitialize()


# ---------------- clipboard ----------------

def _open_clipboard(hwnd=None) -> bool:
    for _ in range(20):  # another app may be holding the clipboard for a moment
        if user32.OpenClipboard(hwnd):
            return True
        time.sleep(0.02)
    return False


def clipboard_seq() -> int:
    """Changes every time anything is copied; cheap to poll."""
    return user32.GetClipboardSequenceNumber()


def get_clipboard() -> str | None:
    if not _open_clipboard():
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None   # not text (image, files...)
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard(text: str) -> bool:
    data = text.encode("utf-16-le") + b"\x00\x00"
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        return False
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    # clipboard needs an owner window, otherwise SetClipboardData can fail after EmptyClipboard
    hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    try:
        if not _open_clipboard(hwnd):
            kernel32.GlobalFree(h)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                kernel32.GlobalFree(h)
                return False
            return True   # the system owns the memory now
        finally:
            user32.CloseClipboard()
    finally:
        if hwnd:
            user32.DestroyWindow(hwnd)


# ---------------- media ----------------

MEDIA = {"playpause", "nexttrack", "prevtrack", "mediastop", "volumeup", "volumedown", "volumemute"}


def media(key: str):
    if key in MEDIA:
        input_win.hotkey(key)


# ---------------- volume ----------------

def _endpoint():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume


def get_volume() -> tuple[int | None, bool | None]:
    try:
        ev = _endpoint()
        return round(ev.GetMasterVolumeLevelScalar() * 100), bool(ev.GetMute())
    except Exception:
        return None, None


def set_volume(level: int | None = None, mute: bool | None = None):
    ev = _endpoint()
    if level is not None:
        ev.SetMasterVolumeLevelScalar(max(0, min(100, int(level))) / 100, None)
        if level > 0 and ev.GetMute():
            ev.SetMute(0, None)   # dragging the slider up unmutes, like the Windows flyout
    if mute is not None:
        ev.SetMute(1 if mute else 0, None)


# ---------------- brightness ----------------

def get_brightness() -> int | None:
    try:
        import screen_brightness_control as sbc
        return int(sbc.get_brightness(display=0)[0])
    except Exception:
        return None   # e.g. external monitor without DDC/CI


def set_brightness(level: int):
    import screen_brightness_control as sbc
    sbc.set_brightness(max(0, min(100, int(level))), display=0)


def step_brightness(up: bool):
    cur = get_brightness()
    if cur is not None:
        set_brightness(cur + (10 if up else -10))


# ---------------- power ----------------

def power(action: str):
    if action == "lock":
        user32.LockWorkStation()
    elif action == "display_off":
        # HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2 = off (Post: Send can hang on busy apps)
        user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)
    elif action == "sleep":
        ctypes.WinDLL("powrprof").SetSuspendState(False, False, False)
    elif action == "restart":
        subprocess.Popen(["shutdown", "/r", "/t", "0"], creationflags=subprocess.CREATE_NO_WINDOW)
    elif action == "shutdown":
        subprocess.Popen(["shutdown", "/s", "/t", "0"], creationflags=subprocess.CREATE_NO_WINDOW)
    elif action == "signout":
        subprocess.Popen(["shutdown", "/l"], creationflags=subprocess.CREATE_NO_WINDOW)
