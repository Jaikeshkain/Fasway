"""Safety rules, in code. Whatever the AI asks for (or a web page or window title tricks it into asking
for), these decide: run it, ask the user on the phone first, or refuse.

Generic tools are the dangerous ones: "type text" plus "press Enter" could run anything in a Run dialog or
terminal. So typing and shortcuts are judged by what is on screen, and unusual shortcuts always ask.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

SAFE, CONFIRM, BLOCKED = "safe", "confirm", "blocked"

SAFE_POWER = {"lock", "display_off"}

# Plain editing / navigation shortcuts. Anything else (win+r, alt+f4, ctrl+w...) asks first.
SAFE_KEYS = {
    "enter", "tab", "escape", "space", "backspace", "delete", "up", "down", "left", "right", "home", "end",
    "pageup", "pagedown", "f5", "f11", "shift+tab",
    *(f"{m}+{k}" for m in ("ctrl", "mod") for k in
      ("a", "c", "v", "x", "z", "y", "s", "f", "n", "t", "p", "b", "i", "u", "l", "backspace", "tab", "plus", "minus", "0")),
    "win+d", "win+e", "win+i", "win+shift+s", "alt+tab",
}

# Windows where typed text can run commands. Matched against the app name and the window title.
SHELL_WINDOW = re.compile(
    r"\b(cmd|command prompt|powershell|pwsh|windows ?terminal|terminal|bash|wsl|conhost|regedit|registry editor|run|python|py|node)\b", re.I)
# Windows where we must not type on the user's behalf without asking.
SENSITIVE_WINDOW = re.compile(
    r"password|passcode|\bsign[ -]?in\b|\blog[ -]?in\b|\bbank|netbanking|payment|checkout|\bupi\b|\bcvv\b|\botp\b", re.I)

# Buttons whose press is hard to take back: signing out, deleting, sending, paying, agreeing.
RISKY_BUTTON = re.compile(
    r"\b(log ?out|log ?off|sign ?out|delete|remove|erase|clear all|uninstall|reset|format|wipe|send|submit|post|"
    r"publish|share|pay|purchase|buy|order|place order|checkout|transfer|withdraw|confirm|accept|agree|allow|"
    r"approve|grant|deactivate|close account|discard|don'?t save|overwrite|replace all|shut ?down|restart|empty|"
    r"install|update now|run|execute|lock)\b", re.I)


def judge_button(name: str, window: str) -> tuple[str, str]:
    """Pressing a named control in an app."""
    if RISKY_BUTTON.search(name):
        return CONFIRM, f"'{name[:40]}' may sign out, delete, send, pay or agree to something"
    if SHELL_WINDOW.search(window):
        return CONFIRM, f"this is a command window ({window[:60]})"
    return SAFE, ""


# Programs that run other programs: never opened by the agent, even with approval.
BLOCKED_PROGRAMS = {
    "cmd", "command prompt", "powershell", "pwsh", "wt", "windows terminal", "terminal", "bash", "wsl", "regedit",
    "registry editor", "mshta", "wscript", "cscript", "rundll32", "regsvr32", "msiexec", "certutil", "bitsadmin",
    "schtasks", "sc", "taskkill", "format", "diskpart", "bcdedit", "reg", "net", "netsh", "gpedit", "secpol",
    "python", "python3", "pythonw", "py", "node", "perl", "ruby", "php", "java", "javaw", "git-bash", "sh", "zsh",
}
SAFE_APP_URIS = {"ms-settings:", "spotify:"}
SCRIPT_EXT = re.compile(r"\.(bat|cmd|ps1|vbs|vbe|js|jse|wsf|wsh|hta|msi|scr|com|cpl|lnk|reg|exe|dll|jar|py|sh)\s*$", re.I)
SIMPLE_APP_NAME = re.compile(r"^[\w .+&-]{1,40}$", re.U)


def normalize_keys(combo: str) -> str:
    return "+".join(p.strip().lower() for p in combo.split("+"))


def check_url(url: str) -> str | None:
    """Reason a link can't be opened, or None."""
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return "Only http(s) links can be opened"
    return None


def check_app(name: str) -> tuple[str, str]:
    """(verdict, reason) for opening a program by name."""
    n = name.strip().strip('"')
    low = n.lower().removesuffix(".exe")
    if low in SAFE_APP_URIS:
        return SAFE, ""
    if low in BLOCKED_PROGRAMS:
        return BLOCKED, f"The agent isn't allowed to open {n}"
    if not SIMPLE_APP_NAME.match(low) or SCRIPT_EXT.search(low):
        return BLOCKED, "The agent opens apps by name only, not paths or scripts"
    return SAFE, ""


def foreground_text(fg: dict | None) -> str:
    return f"{(fg or {}).get('app', '')} {(fg or {}).get('title', '')}".strip()


def judge_typing(fg: dict | None) -> tuple[str, str]:
    """Typing goes to the active window, so what that window is decides the risk."""
    who = foreground_text(fg)
    if SHELL_WINDOW.search(who):
        return CONFIRM, f"this would type into a command window ({who[:60]})"
    if SENSITIVE_WINDOW.search(who):
        return CONFIRM, f"this looks like a sign-in or payment window ({who[:60]})"
    return SAFE, ""


def judge_keys(combo: str, fg: dict | None) -> tuple[str, str]:
    keys = normalize_keys(combo)
    if keys not in SAFE_KEYS:
        return CONFIRM, f"unusual shortcut: {keys}"
    verdict, why = judge_typing(fg)   # Enter in a terminal runs whatever is typed there
    if verdict != SAFE and keys in ("enter", "ctrl+v", "mod+v"):
        return verdict, why
    return SAFE, ""


class Budget:
    """Hard money limits. The AI can't talk its way past these: the runtime checks before every request."""

    def __init__(self, task_usd: float, day_usd: float, spent_today_usd: float):
        self.task_usd, self.day_usd, self.spent_today = task_usd, day_usd, spent_today_usd
        self.task_spent = 0.0

    def add(self, usd: float):
        self.task_spent += usd
        self.spent_today += usd

    def exceeded(self) -> str | None:
        if self.spent_today >= self.day_usd:
            return "day"
        if self.task_spent >= self.task_usd:
            return "task"
        return None
