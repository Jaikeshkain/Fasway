"""Finds an installed app by the name a person would say, from Windows' own Start menu list."""
from __future__ import annotations

import difflib
import json
import logging
import re
import subprocess
import sys
import time

from . import policy

log = logging.getLogger("fasway")
_CACHE_SECONDS = 300
_cache: tuple[float, dict[str, str]] = (0.0, {})
# on top of the policy's list: Start menu names of things that run commands ("Anaconda Prompt", "Developer PowerShell")
_RUNS_COMMANDS = re.compile(r"prompt|shell|console|terminal|bash|python|registry|\bcmd\b", re.I)


def installed() -> dict[str, str]:
    """Lower-case display name -> Start menu app id. Empty if the list isn't available."""
    global _cache
    if sys.platform != "win32":
        return {}
    if time.time() - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    apps: dict[str, str] = {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        rows = json.loads(out.decode("utf-8", "replace") or "[]")
        for row in rows if isinstance(rows, list) else [rows]:
            apps[str(row["Name"]).lower()] = str(row["AppID"])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        log.warning("agent: couldn't list installed apps: %s", e)
    _cache = (time.time(), apps)
    return apps


def _allowed(display_name: str) -> bool:
    return not _RUNS_COMMANDS.search(display_name) and not policy.SHELL_WINDOW.search(display_name) \
        and policy.check_app(display_name)[0] != policy.BLOCKED


def find(name: str, apps: dict[str, str] | None = None) -> str | None:
    """The target to open for a spoken app name, or None. Never returns something that runs commands."""
    apps = installed() if apps is None else apps
    n = name.strip().lower()
    if not n:
        return None
    words = lambda s: set(re.findall(r"\w+", s))   # noqa: E731
    hit = n if n in apps else None
    if not hit:
        # whole words only, shortest name first: "word" is "Word", not "WordPad" or "Password Manager"
        partial = sorted((a for a in apps if words(n) <= words(a)), key=len)
        hit = partial[0] if partial else None
    if not hit:
        close = difflib.get_close_matches(n, list(apps), n=1, cutoff=0.8)
        hit = close[0] if close else None
    if not hit or not _allowed(hit):
        return None
    return "shell:AppsFolder\\" + apps[hit]
