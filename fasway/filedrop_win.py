"""Accept files dragged from Explorer onto a Tk window (Windows WM_DROPFILES; Tk has no file drop)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

WM_DROPFILES = 0x0233
WM_COPYDATA = 0x004A
WM_COPYGLOBALDATA = 0x0049
GWLP_WNDPROC = -4
MSGFLT_ALLOW = 1

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32.GetParent.argtypes = (wintypes.HWND,)
user32.GetParent.restype = wintypes.HWND
user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.CallWindowProcW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.CallWindowProcW.restype = LRESULT
user32.ChangeWindowMessageFilterEx.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p)
user32.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
shell32.DragQueryFileW.argtypes = (ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT)
shell32.DragQueryFileW.restype = wintypes.UINT
shell32.DragFinish.argtypes = (ctypes.c_void_p,)

_keep = []  # window procedures must stay alive as long as the window


def enable(tk_window, on_drop) -> bool:
    """Call on_drop(list_of_paths) when files are dropped anywhere on tk_window (a Tk / Toplevel).
    The window must have been shown once (Tk makes its outer frame window then); False = try later."""
    try:
        tk_window.update_idletasks()
        hwnd = user32.GetParent(tk_window.winfo_id())   # the outer frame window
        if not hwnd:
            return False
        # running as administrator: let Explorer (not elevated) deliver drops to us
        for msg in (WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA):
            user32.ChangeWindowMessageFilterEx(hwnd, msg, MSGFLT_ALLOW, None)

        old = None

        def proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                hdrop = ctypes.c_void_p(wparam)
                paths = []
                for i in range(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)):
                    n = shell32.DragQueryFileW(hdrop, i, None, 0)
                    buf = ctypes.create_unicode_buffer(n + 1)
                    shell32.DragQueryFileW(hdrop, i, buf, n + 1)
                    paths.append(buf.value)
                shell32.DragFinish(hdrop)
                try:
                    on_drop(paths)
                except Exception:
                    pass
                return 0
            return user32.CallWindowProcW(old, h, msg, wparam, lparam)

        cb = WNDPROC(proc)
        _keep.append(cb)
        old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
        shell32.DragAcceptFiles(hwnd, True)
        return True
    except Exception:
        return False
