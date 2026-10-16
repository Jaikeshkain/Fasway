"""Windows input injection via SendInput (mouse + Unicode keyboard)."""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetShellWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.IsIconic.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_fg_checked = 0.0


def _fix_foreground():
    """When every window is minimized, Windows may leave a minimized or invisible window active
    (e.g. UltraViewer's hidden 0x0 window). Some of those swallow injected input, and keystrokes
    sent to a minimized window go nowhere. Hand the focus to the desktop in that case."""
    global _fg_checked
    now = time.monotonic()
    if now - _fg_checked < 0.3:
        return
    _fg_checked = now
    fg = user32.GetForegroundWindow()
    if not fg:
        return
    r = wintypes.RECT()
    user32.GetWindowRect(fg, ctypes.byref(r))
    if user32.IsIconic(fg) or not user32.IsWindowVisible(fg) or r.right - r.left <= 1 or r.bottom - r.top <= 1:
        desktop = user32.GetShellWindow()
        if desktop and desktop != fg:
            user32.SetForegroundWindow(desktop)


# ---------------- administrator (UIPI) ----------------
# Windows silently drops injected input aimed at apps running as Administrator (Task Manager,
# admin terminals, installers...) unless Fasway runs as Administrator too.
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
_admin_cache: dict[int, tuple[float, str | None]] = {}


_elevated: bool | None = None


def is_elevated() -> bool:
    global _elevated
    if _elevated is None:
        try:
            _elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            _elevated = False
    return _elevated


def _process_admin_name(pid: int) -> str | None:
    """Exe name if the process runs elevated (admin), else None."""
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(512)
        n = wintypes.DWORD(512)
        kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        name = buf.value.rsplit("\\", 1)[-1] or "an admin app"
        tok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):   # TOKEN_QUERY
            return name   # a normal process may not read an elevated process's token
        try:
            elev, ret = wintypes.DWORD(), wintypes.DWORD()
            advapi32.GetTokenInformation(tok, 20, ctypes.byref(elev), 4, ctypes.byref(ret))  # TokenElevation
            return name if elev.value else None
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def blocking_admin_app() -> str | None:
    """Name of the active admin app that Windows won't let us control, or None."""
    if is_elevated():
        return None
    fg = user32.GetForegroundWindow()
    if not fg:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
    now = time.monotonic()
    hit = _admin_cache.get(pid.value)
    if hit and now - hit[0] < 5:
        name = hit[1]
    else:
        name = _process_admin_name(pid.value)
        _admin_cache[pid.value] = (now, name)
    if not name:
        return None
    title = ctypes.create_unicode_buffer(80)
    user32.GetWindowTextW(fg, title, 80)
    return title.value or name.removesuffix(".exe")   # "Task Manager" reads better than "Taskmgr.exe"


def _send(inputs):
    if not inputs:
        return
    _fix_foreground()
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, 0)
    return inp


def _key(vk=0, scan=0, flags=0):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


# ---------------- mouse ----------------

def move(dx: int, dy: int):
    _send([_mouse(MOUSEEVENTF_MOVE, int(dx), int(dy))])


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x: int, y: int):
    """Absolute position in virtual-screen pixels (same coordinates as screen capture)."""
    _fix_foreground()
    user32.SetCursorPos(int(x), int(y))


def enable_precise_timers():
    """Windows timers default to ~15.6 ms ticks, which caps smooth 30 fps streaming."""
    try:
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
    except (AttributeError, OSError):
        pass


def enable_dpi_awareness():
    """Use real pixels everywhere so cursor position and screen capture line up on scaled displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def button(name: str, action: str):
    """action: 'down' | 'up' | 'click'"""
    down, up = _BUTTONS.get(name, _BUTTONS["left"])
    if action == "down":
        _send([_mouse(down)])
    elif action == "up":
        _send([_mouse(up)])
    else:
        _send([_mouse(down), _mouse(up)])


def scroll(dx: int, dy: int):
    """Wheel deltas in Windows units (120 = one notch). Positive dy scrolls up."""
    inputs = []
    if dy:
        inputs.append(_mouse(MOUSEEVENTF_WHEEL, data=int(dy)))
    if dx:
        inputs.append(_mouse(MOUSEEVENTF_HWHEEL, data=int(dx)))
    _send(inputs)


# ---------------- keyboard ----------------

VK = {
    "enter": 0x0D, "backspace": 0x08, "tab": 0x09, "escape": 0x1B, "space": 0x20,
    "delete": 0x2E, "insert": 0x2D, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C,
    "capslock": 0x14, "menu": 0x5D,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "nexttrack": 0xB0, "prevtrack": 0xB1, "mediastop": 0xB2, "playpause": 0xB3,
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},  # F1 = 0x70
}
ALIASES = {"mod": "ctrl", "cmd": "win", "meta": "win", "option": "alt", "esc": "escape", "del": "delete"}
_EXTENDED = {0x2E, 0x2D, 0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22, 0x2C, 0x5B, 0x5D,
             0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}
KEYEVENTF_EXTENDEDKEY = 0x0001
user32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
user32.VkKeyScanW.restype = ctypes.c_short


def _vk_for(name: str):
    name = ALIASES.get(name, name)
    if name in VK:
        return VK[name]
    if len(name) == 1:  # letters, digits, punctuation on the current keyboard layout
        r = user32.VkKeyScanW(name)
        if r != -1 and (r & 0xFF) != 0xFF:
            return r & 0xFF
    return None


def _vk_event(vk, up=False):
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    return _key(vk=vk, flags=flags)


def hotkey(combo: str):
    """e.g. 'enter', 'ctrl+z', 'ctrl+shift+left', 'win+d', 'f5'. 'mod' = Ctrl on Windows."""
    combo = combo.lower()
    parts = ["+"] if combo == "+" else combo.split("+")
    vks = [_vk_for(k) for k in parts]
    if not vks or None in vks:
        return
    _send([_vk_event(v) for v in vks] + [_vk_event(v, up=True) for v in reversed(vks)])


def delete_back(n: int):
    n = max(0, min(int(n), 2000))
    for i in range(0, n, 100):
        _send([e for _ in range(min(100, n - i)) for e in (_vk_event(0x08), _vk_event(0x08, up=True))])


def type_text(text: str):
    """Type arbitrary Unicode (Devanagari, emoji, ...) into the focused window."""
    inputs = []
    for ch in text:
        if ch == "\n":
            inputs += [_vk_event(VK["enter"]), _vk_event(VK["enter"], up=True)]
            continue
        if ch == "\r":
            continue
        data = ch.encode("utf-16-le")
        units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
        for u in units:  # surrogate pairs are sent as two units
            inputs.append(_key(scan=u, flags=KEYEVENTF_UNICODE))
            inputs.append(_key(scan=u, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    # Send in chunks so very long dictations don't overflow the input queue
    for i in range(0, len(inputs), 200):
        _send(inputs[i:i + 200])
