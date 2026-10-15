"""macOS system controls: clipboard, media keys, volume, brightness, power.

Requires pyobjc-framework-Cocoa (AppKit) in addition to Quartz.
"""
from __future__ import annotations

import subprocess

import Quartz as Q
from AppKit import NSEvent, NSPasteboard, NSPasteboardTypeString

from . import input_mac

NSSystemDefined = 14
# NX_KEYTYPE_* codes from IOKit/hidsystem/ev_keymap.h
NX = {"volumeup": 0, "volumedown": 1, "brightnessup": 2, "brightnessdown": 3, "volumemute": 7,
      "playpause": 16, "nexttrack": 17, "prevtrack": 18}
MEDIA = set(NX) | {"mediastop"}


def thread_init():
    pass


# ---------------- clipboard ----------------

def _pb():
    return NSPasteboard.generalPasteboard()


def clipboard_seq() -> int:
    return int(_pb().changeCount())


def get_clipboard() -> str | None:
    s = _pb().stringForType_(NSPasteboardTypeString)
    return str(s) if s is not None else None


def set_clipboard(text: str) -> bool:
    pb = _pb()
    pb.clearContents()
    return bool(pb.setString_forType_(text, NSPasteboardTypeString))


# ---------------- media ----------------

def _special_key(code: int):
    """Media/brightness keys are 'system defined' events, not normal key codes."""
    for down in (True, False):
        state = 0xA if down else 0xB
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            NSSystemDefined, (0, 0), state << 8, 0, 0, None, 8, (code << 16) | (state << 8), -1)
        Q.CGEventPost(Q.kCGHIDEventTap, ev.CGEvent())


def media(key: str):
    if key == "mediastop":
        key = "playpause"   # macOS has no stop key
    if key in NX:
        _special_key(NX[key])


# ---------------- volume (AppleScript) ----------------

def _osa(script: str) -> str:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5).stdout.strip()


def get_volume() -> tuple[int | None, bool | None]:
    try:
        out = _osa("set s to get volume settings\nreturn (output volume of s as text) & \",\" & (output muted of s as text)")
        vol, muted = out.split(",")
        return int(vol), muted.strip() == "true"
    except Exception:
        return None, None


def set_volume(level: int | None = None, mute: bool | None = None):
    if level is not None:
        level = max(0, min(100, int(level)))
        _osa(f"set volume output volume {level}" + ("\nset volume output muted false" if level > 0 else ""))
    if mute is not None:
        _osa(f"set volume output muted {'true' if mute else 'false'}")


# ---------------- brightness ----------------

def get_brightness() -> int | None:
    return None   # no public API for the level; the phone shows -/+ buttons instead


def step_brightness(up: bool):
    _special_key(NX["brightnessup" if up else "brightnessdown"])


# ---------------- power ----------------

def power(action: str):
    if action == "lock":
        input_mac.hotkey("ctrl+cmd+q")      # macOS "Lock Screen" shortcut
    elif action == "display_off":
        subprocess.Popen(["pmset", "displaysleepnow"])
    elif action == "sleep":
        subprocess.Popen(["pmset", "sleepnow"])
    elif action in ("restart", "shutdown", "signout"):
        verb = {"restart": "restart", "shutdown": "shut down", "signout": "log out"}[action]
        subprocess.Popen(["osascript", "-e", f'tell application "System Events" to {verb}'])
