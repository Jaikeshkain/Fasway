"""macOS input injection via Quartz CGEvents (mouse + Unicode keyboard).

Requires: pip install pyobjc-framework-Quartz pyobjc-framework-ApplicationServices
and Accessibility permission for the app running Python (System Settings →
Privacy & Security → Accessibility), otherwise macOS silently drops the events.
"""
from __future__ import annotations

import sys
import time

import Quartz as Q

_SRC = Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)
_TAP = Q.kCGHIDEventTap

_BTN = {
    "left": (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGEventLeftMouseDragged, Q.kCGMouseButtonLeft),
    "right": (Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, Q.kCGEventRightMouseDragged, Q.kCGMouseButtonRight),
    "middle": (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, Q.kCGEventOtherMouseDragged, Q.kCGMouseButtonCenter),
}
_held: list[str] = []                 # buttons currently pressed (drag needs *Dragged events)
_last_click = {"t": 0.0, "b": "", "n": 0, "x": 0.0, "y": 0.0}
DOUBLE_CLICK_S = 0.5


def permission_problem() -> str | None:
    """Returns a message if macOS hasn't granted Accessibility access (also triggers the system prompt)."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        if AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
            return None
    except Exception:
        return None
    who = "Fasway" if getattr(sys, "frozen", False) else "Terminal (or Python)"
    return ("Allow Accessibility: System Settings → Privacy & Security → Accessibility → "
            f"enable {who}, then restart Fasway")


# ---------------- mouse ----------------

def _pos():
    return Q.CGEventGetLocation(Q.CGEventCreate(None))


def _displays():
    err, ids, n = Q.CGGetActiveDisplayList(16, None, None)
    return [Q.CGDisplayBounds(i) for i in (ids or [])[:n]] or [Q.CGDisplayBounds(Q.CGMainDisplayID())]


def _inside(r, x, y):
    return r.origin.x <= x < r.origin.x + r.size.width and r.origin.y <= y < r.origin.y + r.size.height


def _clamp(old, x, y):
    """Keep the cursor on a screen (multi-monitor aware)."""
    rects = _displays()
    if any(_inside(r, x, y) for r in rects):
        return x, y
    r = next((r for r in rects if _inside(r, old.x, old.y)), rects[0])
    x = min(max(x, r.origin.x), r.origin.x + r.size.width - 1)
    y = min(max(y, r.origin.y), r.origin.y + r.size.height - 1)
    return x, y


def _post_mouse(etype, x, y, button, click_count=None, dx=0, dy=0):
    ev = Q.CGEventCreateMouseEvent(_SRC, etype, (x, y), button)
    if click_count is not None:
        Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, click_count)
    if dx or dy:
        Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventDeltaX, int(dx))
        Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventDeltaY, int(dy))
    Q.CGEventPost(_TAP, ev)


def move(dx: int, dy: int):
    p = _pos()
    x, y = _clamp(p, p.x + dx, p.y + dy)
    if _held:
        _, _, drag_type, btn = _BTN[_held[-1]]
        _post_mouse(drag_type, x, y, btn, dx=dx, dy=dy)
    else:
        _post_mouse(Q.kCGEventMouseMoved, x, y, Q.kCGMouseButtonLeft, dx=dx, dy=dy)


def cursor_pos() -> tuple[float, float]:
    p = _pos()
    return p.x, p.y


def move_to(x: float, y: float):
    """Absolute position in points (same coordinates mss uses for monitors)."""
    p = _pos()
    x, y = _clamp(p, x, y)
    if _held:
        _, _, drag_type, btn = _BTN[_held[-1]]
        _post_mouse(drag_type, x, y, btn)
    else:
        _post_mouse(Q.kCGEventMouseMoved, x, y, Q.kCGMouseButtonLeft)


def screen_permission_problem() -> str | None:
    """Screen Recording permission is needed for the live preview (else only the wallpaper is captured)."""
    try:
        if Q.CGPreflightScreenCaptureAccess():
            return None
        Q.CGRequestScreenCaptureAccess()  # shows the system prompt once
    except AttributeError:  # macOS < 10.15
        return None
    who = "Fasway" if getattr(sys, "frozen", False) else "Terminal (or Python)"
    return ("Allow Screen Recording: System Settings → Privacy & Security → Screen Recording → "
            f"enable {who}, then restart Fasway")


def _click_count(name, p):
    """macOS only treats clicks as double/triple clicks if the event says so."""
    now = time.monotonic()
    lc = _last_click
    if (lc["b"] == name and now - lc["t"] < DOUBLE_CLICK_S
            and abs(p.x - lc["x"]) < 6 and abs(p.y - lc["y"]) < 6):
        lc["n"] = min(lc["n"] + 1, 3)
    else:
        lc["n"] = 1
    lc.update(t=now, b=name, x=p.x, y=p.y)
    return lc["n"]


def button(name: str, action: str):
    """action: 'down' | 'up' | 'click'"""
    if name not in _BTN:
        name = "left"
    down, up, _, btn = _BTN[name]
    p = _pos()
    if action == "down":
        if name not in _held:
            _held.append(name)
        _post_mouse(down, p.x, p.y, btn, 1)
    elif action == "up":
        if name in _held:
            _held.remove(name)
        _post_mouse(up, p.x, p.y, btn, 1)
    else:
        n = _click_count(name, p)
        _post_mouse(down, p.x, p.y, btn, n)
        _post_mouse(up, p.x, p.y, btn, n)


_scroll_rem = [0.0, 0.0]
WHEEL_TO_PIXELS = 1 / 4  # phone sends Windows wheel units (120/notch); macOS gets smooth pixel scrolling


def scroll(dx: int, dy: int):
    """Positive dy scrolls up, positive dx scrolls right (same convention as Windows)."""
    _scroll_rem[0] += dy * WHEEL_TO_PIXELS
    _scroll_rem[1] += -dx * WHEEL_TO_PIXELS   # macOS: positive horizontal = scroll left
    py, px = int(_scroll_rem[0]), int(_scroll_rem[1])
    if not (py or px):
        return
    _scroll_rem[0] -= py
    _scroll_rem[1] -= px
    try:
        ev = Q.CGEventCreateScrollWheelEvent(_SRC, Q.kCGScrollEventUnitPixel, 2, py, px)
    except Exception:  # older PyObjC without variadic support
        ev = Q.CGEventCreateScrollWheelEvent2(_SRC, Q.kCGScrollEventUnitPixel, 2, py, px, 0)
    Q.CGEventPost(_TAP, ev)


# ---------------- keyboard ----------------

KEYCODE = {  # US layout virtual key codes
    "enter": 36, "tab": 48, "space": 49, "backspace": 51, "escape": 53, "delete": 117,
    "left": 123, "right": 124, "down": 125, "up": 126, "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121, "capslock": 57,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
    "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
    "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31,
    "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42,
    ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
}
MODS = {  # name -> (keycode, flag)
    "cmd": (55, Q.kCGEventFlagMaskCommand),
    "shift": (56, Q.kCGEventFlagMaskShift),
    "alt": (58, Q.kCGEventFlagMaskAlternate),
    "ctrl": (59, Q.kCGEventFlagMaskControl),
}
# 'mod' = the platform's main shortcut key (Cmd here, Ctrl on Windows)
ALIASES = {"mod": "cmd", "win": "cmd", "meta": "cmd", "option": "alt", "esc": "escape", "del": "delete"}
# Windows-style shortcuts the phone may send, translated to Mac equivalents
MAC_SHORTCUTS = {
    "ctrl+backspace": "alt+backspace",   # delete previous word
    "mod+y": "cmd+shift+z",              # redo
    "ctrl+left": "alt+left", "ctrl+right": "alt+right",                  # word jumps
    "ctrl+shift+left": "alt+shift+left", "ctrl+shift+right": "alt+shift+right",
}


def _post_key(code, down, flags=0):
    ev = Q.CGEventCreateKeyboardEvent(_SRC, code, down)
    Q.CGEventSetFlags(ev, flags)
    Q.CGEventPost(_TAP, ev)


def hotkey(combo: str):
    """e.g. 'enter', 'mod+z' (Cmd+Z), 'ctrl+backspace' (Option+Delete), 'shift+left', 'f5'."""
    combo = combo.lower()
    combo = MAC_SHORTCUTS.get(combo, combo)
    parts = ["+"] if combo == "+" else [ALIASES.get(p, p) for p in combo.split("+")]
    mods, key = parts[:-1], parts[-1]
    if key not in KEYCODE or any(m not in MODS for m in mods):
        return
    flags = 0
    for m in mods:
        flags |= MODS[m][1]
        _post_key(MODS[m][0], True, flags)
    _post_key(KEYCODE[key], True, flags)
    _post_key(KEYCODE[key], False, flags)
    for m in reversed(mods):
        flags &= ~MODS[m][1]
        _post_key(MODS[m][0], False, flags)


def delete_back(n: int):
    for _ in range(max(0, min(int(n), 2000))):
        _post_key(KEYCODE["backspace"], True)
        _post_key(KEYCODE["backspace"], False)


def type_text(text: str):
    """Type arbitrary Unicode (Devanagari, emoji, ...) into the focused app.

    One code point per event: some apps (Chrome, Electron) drop all but the first
    character when an event carries a longer string.
    """
    for i, ch in enumerate(text):
        if ch == "\n":
            _post_key(KEYCODE["enter"], True)
            _post_key(KEYCODE["enter"], False)
            continue
        if ch == "\r":
            continue
        units = len(ch.encode("utf-16-le")) // 2   # emoji = 2 UTF-16 units
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(_SRC, 0, down)
            Q.CGEventSetFlags(ev, 0)                # don't let a held modifier turn text into shortcuts
            Q.CGEventKeyboardSetUnicodeString(ev, units, ch)
            Q.CGEventPost(_TAP, ev)
        if i % 40 == 39:
            time.sleep(0.003)  # let slower apps keep up with long dictations
