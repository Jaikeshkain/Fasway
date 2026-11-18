"""Web pages in the user's own browser, read like app windows (appui).

Chromium browsers (Edge, Chrome, Brave) show a page's links, buttons and boxes to UI Automation only when
started with --force-renderer-accessibility. So when the assistant needs a page and the browser lacks it,
it asks the user once, then closes that browser and starts it again with the setting and the same profile
and tabs. Nothing system-wide is changed: only that browser's start.
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import tempfile
import time

log = logging.getLogger("fasway")

FLAG = "--force-renderer-accessibility"
BROWSERS = {"msedge.exe": "Edge", "chrome.exe": "Chrome", "brave.exe": "Brave"}
_PROG_IDS = {"MSEdgeHTM": "msedge.exe", "ChromeHTML": "chrome.exe", "BraveHTML": "brave.exe"}
_PATHS = {"msedge.exe": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"],
          "chrome.exe": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"],
          "brave.exe": [r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"]}
_USER_DATA = {"msedge.exe": r"%LOCALAPPDATA%\Microsoft\Edge\User Data", "chrome.exe": r"%LOCALAPPDATA%\Google\Chrome\User Data",
              "brave.exe": r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data"}
PAGE_READY = 4.0   # after a restart, pages take a few seconds before they show their contents
restarted_at = 0.0


def _user_data_dir(exe: str, cmdline: list[str] | None = None) -> str:
    """The browser's profile folder root: from its command line when started with one, else the usual place."""
    for a in cmdline or []:
        if a.startswith("--user-data-dir="):
            return a.split("=", 1)[1].strip('"')
    return os.path.expandvars(_USER_DATA.get(exe, ""))


def profiles(exe: str, cmdline: list[str] | None = None) -> tuple[list[str], dict[str, str]]:
    """(the profile folders the user had open, newest first, else the last used one; folder -> the name the
    browser shows). Read from the browser's own Local State, so a profile switched to inside the browser counts."""
    import json
    try:
        with open(os.path.join(_user_data_dir(exe, cmdline), "Local State"), encoding="utf-8") as f:
            state = json.load(f).get("profile", {})
    except (OSError, ValueError):
        return [], {}
    names = {d: (i or {}).get("name", d) for d, i in (state.get("info_cache") or {}).items()}
    open_now = [p for p in state.get("last_active_profiles") or [] if p in names or not names]
    last = state.get("last_used")
    order = ([last] if last in open_now else []) + [p for p in open_now if p != last]
    return (order or ([last] if last else [])), names


class BrowserAccessError(Exception):
    pass


def owner_of_window(hwnd: int) -> tuple[str | None, int]:
    """(the program a window belongs to, e.g. 'msedge.exe', and its process id)."""
    import psutil
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    try:
        return psutil.Process(pid.value).name().lower(), pid.value
    except Exception:
        return None, pid.value


def process_can_read_pages(pid: int) -> bool:
    import psutil
    try:
        return FLAG in (psutil.Process(pid).cmdline() or [])
    except Exception:
        return False


def default_browser() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            prog = winreg.QueryValueEx(k, "ProgId")[0]
    except OSError:
        return None
    return next((exe for p, exe in _PROG_IDS.items() if prog.startswith(p)), None)


def _main_processes(exe: str) -> list:
    """The browser's own process (one per profile folder): the one started without --type=."""
    import psutil
    found = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() == exe and not any(a.startswith("--type=") for a in (p.info["cmdline"] or [])):
                found.append(p)
        except Exception:
            continue
    return found


def can_read_pages(exe: str) -> bool | None:
    """True / False for a running browser; None when it isn't running."""
    procs = _main_processes(exe)
    if not procs:
        return None
    return all(FLAG in (p.cmdline() or []) for p in procs)


def _windows_of(pid: int) -> list[int]:
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            found.append(hwnd)
        return True
    user32.EnumWindows(each, 0)
    return found


def _quote(a: str) -> str:
    return f'"{a}"' if " " in a else a


def _start_as_user(exe_path: str, args: list[str]):
    """Start a program as the signed-in user, even when Fasway runs as administrator: Explorer opens a
    shortcut with the user's own rights, so the browser never runs elevated."""
    lnk = os.path.join(tempfile.gettempdir(), "fasway-browser.lnk")
    arg_text = " ".join(_quote(a) for a in args).replace("'", "''")
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              f"$s.TargetPath='{exe_path}';$s.Arguments='{arg_text}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True, timeout=20,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.Popen(["explorer.exe", lnk], creationflags=subprocess.CREATE_NO_WINDOW)


def restart_with_page_reading(exe: str, only_pid: int | None = None) -> str:
    """Close the browser and start it again with page reading, its profile and its tabs. `only_pid`: just
    the browser process that owns a given window (others with their own profile folder are left alone).
    Returns what happened, for the AI."""
    global restarted_at
    import psutil
    name = BROWSERS.get(exe, exe)
    procs = [p for p in _main_processes(exe) if only_pid is None or p.pid == only_pid]
    starts = []
    for p in procs:
        try:
            cmd = p.cmdline()
        except psutil.Error:
            continue
        # the profile is chosen below from what the browser itself last had open, not from how it was started
        keep = [a for a in cmd[1:] if a.startswith("--") and not a.startswith(
            ("--type=", FLAG, "--restore-last-session", "--source-shortcut-location", "--no-startup-window",
             "--win-session-start", "--flag-switches", "--profile-directory"))]
        launched_with = next((a.split("=", 1)[1] for a in cmd if a.startswith("--profile-directory=")), None)
        starts.append((cmd[0], keep, cmd, launched_with))
    if not starts:   # not running: start it fresh, in the profile it last used
        path = next((os.path.expandvars(p) for p in _PATHS.get(exe, []) if os.path.exists(os.path.expandvars(p))), None)
        if not path:
            raise BrowserAccessError(f"{name} isn't installed")
        starts = [(path, [], None, None)]
    # close politely first (it saves the session); anything still running after that is ended
    for p in procs:
        for hwnd in _windows_of(p.pid):
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)   # WM_CLOSE
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and any(p.is_running() for p in procs):
        time.sleep(0.3)
    for p in procs:
        if p.is_running():   # kept alive in the background (startup boost) or asked "close all tabs?"
            try:
                for c in p.children(recursive=True):
                    c.kill()
                p.kill()
            except psutil.Error:
                pass
    time.sleep(0.5)

    def ready():
        return any(FLAG in (p.cmdline() or []) for p in _main_processes(exe))
    shown = []
    for path, keep, cmd, launched_with in starts:
        # read after closing: the browser writes which profiles were open as it shuts down
        open_profiles, names = profiles(exe, cmd)
        open_profiles = open_profiles or ([launched_with] if launched_with else [])
        first, *more = open_profiles or [None]
        _start_as_user(path, [*keep, *([f"--profile-directory={first}"] if first else []), FLAG, "--restore-last-session"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not ready():
            time.sleep(0.5)
        for p in more:   # the browser is running with page reading now: these open in it, as windows of their own
            _start_as_user(path, [*keep, f"--profile-directory={p}", "--restore-last-session"])
            time.sleep(1)
        shown += [names.get(p, p) for p in open_profiles if p]
    if not ready():
        raise BrowserAccessError(f"{name} didn't start again with page reading; open it once and try again")
    restarted_at = time.monotonic()
    which = f" ({', '.join(shown)} profile{'s' if len(shown) > 1 else ''})" if shown else ""
    log.info("agent: restarted %s with page reading%s", name, which)
    return f"{name} is open again with your tabs{which}, and the assistant can now read its web pages"


def wait_until_ready():
    """Pages show their contents a few seconds after a restart."""
    left = PAGE_READY - (time.monotonic() - restarted_at)
    if 0 < left <= PAGE_READY:
        time.sleep(left)
