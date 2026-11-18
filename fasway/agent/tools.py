"""What the agent can do on the laptop. Each tool wraps a function Fasway already has, and declares its risk.

There is deliberately no shell tool, no file deletion and no way to enter credentials. A model can only
call what is listed here, and every input is re-checked here: tool schemas can't enforce safety.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import quote_plus

from . import apps, appui, browser_access, policy
from .policy import BLOCKED, CONFIRM, SAFE

SEARCH_SITES = {
    "google": "https://www.google.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
}
MEDIA_KEYS = {"play_pause": "playpause", "next": "nexttrack", "previous": "prevtrack"}
POWER_LABEL = {"lock": "Lock the laptop", "display_off": "Turn the display off", "sleep": "Put the laptop to sleep",
               "signout": "Sign out of Windows (unsaved work will be lost)",
               "restart": "Restart the laptop (unsaved work will be lost)",
               "shutdown": "Shut down the laptop (unsaved work will be lost)"}


@dataclass
class Env:
    """The laptop, as the tools see it. Tests pass recording stand-ins."""
    inp: object
    sysctl: object
    nowplaying: object
    actions: object
    run_sys: Callable[..., Awaitable]   # runs a blocking function on the server's system thread
    status: object = None


@dataclass
class Tool:
    name: str
    description: str
    props: dict
    run: Callable[[Env, dict], Awaitable[str]]
    # risk(input, foreground window, env) -> (verdict, reason)
    risk: Callable[[dict, dict | None, Env], tuple[str, str]] = lambda i, f, e: (SAFE, "")
    # plain words for the phone: progress lines and approval cards
    label: Callable[[dict], str] = lambda i: ""

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "strict": True,
                "input_schema": {"type": "object", "properties": self.props, "required": sorted(self.props),
                                 "additionalProperties": False}}


def _find_window(windows: list[dict], match: str) -> dict | None:
    m = match.strip().lower()
    return next((w for w in windows if m and (m in w.get("title", "").lower() or m in w.get("app", "").lower())), None)


async def _windows(env: Env) -> list[dict]:
    return (await env.run_sys(env.sysctl.list_windows, set()))["windows"]


# ---------------- handlers ----------------

async def _get_windows(env: Env, i: dict) -> str:
    wins = await _windows(env)
    return "\n".join(f"- {w['title'][:80]} [{w.get('app', '')}]" + (" (active)" if w.get("active") else "")
                     + (" (minimized)" if w.get("min") else "") for w in wins) or "No open windows"


async def _get_now_playing(env: Env, i: dict) -> str:
    st = await env.nowplaying.get_state(set())
    if not st["sessions"]:
        return "Nothing is playing"
    return "\n".join(f"- {s['title']} by {s['artist']} in {s['app']}: {s['status']} at {int(s['pos'])}s of {int(s['dur'])}s"
                     for s in st["sessions"])


async def _get_system_status(env: Env, i: dict) -> str:
    vol, muted = await env.run_sys(env.sysctl.get_volume)
    bright = await env.run_sys(env.sysctl.get_brightness)
    s = await env.run_sys(env.status.get_status)
    parts = [f"Volume {vol}%{' (muted)' if muted else ''}" if vol is not None else "Volume unknown",
             f"brightness {bright}%" if bright is not None else "brightness unknown",
             f"battery {s['battery']}%{' charging' if s['plugged'] else ''}" if s["battery"] is not None else "no battery",
             f"CPU {s['cpu']}%", f"RAM {s['ram']}%"]
    return "; ".join(parts)


async def _get_time(env: Env, i: dict) -> str:
    return time.strftime("It's %I:%M %p on %A, %d %B %Y").replace(" 0", " ")


async def _open_url(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.open_target, i["url"].strip())
    return f"Opened {i['url']}"


async def _web_search(env: Env, i: dict) -> str:
    url = SEARCH_SITES[i["site"]].format(q=quote_plus(i["query"]))
    await env.run_sys(env.sysctl.open_target, url)
    return f"Opened {i['site']} search results for {i['query']} in the browser"


_YT_VIDEO = re.compile(r'"videoRenderer":\{"videoId":"([\w-]{11})"')   # a plain video: skips ads, shorts, channels
_YT_TITLE = re.compile(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"')


def top_youtube_video(query: str) -> tuple[str, str] | None:
    """(video id, title) of YouTube's first result for a search, read from its results page. None if it can't."""
    req = urllib.request.Request(SEARCH_SITES["youtube"].format(q=quote_plus(query)), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Accept-Language": "en-IN,en;q=0.9"})
    try:
        html = urllib.request.urlopen(req, timeout=8).read(4_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    m = _YT_VIDEO.search(html)
    if not m:
        return None
    t = _YT_TITLE.search(html, m.end(), m.end() + 4000)
    try:
        title = json.loads(f'"{t[1]}"') if t else query
    except ValueError:
        title = query
    return m[1], title


async def _play_youtube(env: Env, i: dict) -> str:
    q = i["query"].strip()
    found = await asyncio.to_thread(top_youtube_video, q)
    if not found:   # offline, or YouTube changed its page: the results are the next best thing
        await env.run_sys(env.sysctl.open_target, SEARCH_SITES["youtube"].format(q=quote_plus(q)))
        return f"Couldn't pick a video, so I opened the YouTube results for {q}"
    vid, title = found
    await env.run_sys(env.sysctl.open_target, f"https://www.youtube.com/watch?v={vid}")
    return f"Playing {title[:90]} on YouTube"


# Services with a desktop app as well as a website: the installed app when there is one, else the site.
APP_OR_SITE = {"chatgpt": "https://chatgpt.com", "claude": "https://claude.ai", "whatsapp": "https://web.whatsapp.com",
               "whatsappweb": "https://web.whatsapp.com", "spotify": "https://open.spotify.com",
               "netflix": "https://www.netflix.com", "instagram": "https://www.instagram.com",
               "facebook": "https://www.facebook.com", "telegram": "https://web.telegram.org",
               "discord": "https://discord.com/app", "teams": "https://teams.microsoft.com", "zoom": "https://app.zoom.us",
               "outlook": "https://outlook.live.com", "linkedin": "https://www.linkedin.com", "notion": "https://www.notion.so",
               "slack": "https://app.slack.com", "primevideo": "https://www.primevideo.com"}
APP_WAIT = 3.0   # seconds to watch for the app's window, so the reply says what really happened


async def _new_window(env: Env, before: set, name: str) -> tuple[dict | None, bool]:
    """(the window that opened, whether it was already open). Waits up to APP_WAIT."""
    deadline = time.monotonic() + APP_WAIT
    while time.monotonic() < deadline:
        await asyncio.sleep(0.4)
        wins = await _windows(env)
        new = next((w for w in wins if w["id"] not in before), None)
        if new:
            return new, False
    old = _find_window(await _windows(env), name)
    return old, old is not None


async def _open_app(env: Env, i: dict) -> str:
    name = i["name"].strip()
    before = {w["id"] for w in await _windows(env)}
    site = APP_OR_SITE.get(re.sub(r"[^a-z]", "", name.lower()))
    if site:
        target = await asyncio.to_thread(apps.find, name)
        if not target:
            await env.run_sys(env.sysctl.open_target, site)
            return f"The {name} app isn't installed on this laptop, so I opened {site} in the browser"
        await env.run_sys(env.sysctl.open_target, target)
    else:
        try:
            await env.run_sys(env.sysctl.open_target, name)
        except OSError:
            # not a command Windows knows: look through what's installed ("whatsapp", "power bi")
            target = await asyncio.to_thread(apps.find, name)
            if not target:
                raise ToolFailed(f"I couldn't find an app called {name} on this laptop") from None
            await env.run_sys(env.sysctl.open_target, target)
    w, already = await _new_window(env, before, name)   # also lets it appear before a next step types into it
    if w and not already:
        return f"Opened {name}: its window '{w['title'][:60]}' is up"
    if w:
        return f"{name} was already open: '{w['title'][:60]}'"
    return f"Asked Windows to open {name}, but no window has appeared yet (it may still be starting)"


async def _switch_window(env: Env, i: dict) -> str:
    w = _find_window(await _windows(env), i["match"])
    if not w:
        raise ToolFailed(f"No open window matches '{i['match']}'")
    await env.run_sys(env.sysctl.window_action, w["id"], "focus")
    await asyncio.sleep(0.2)
    return f"Switched to {w['title'][:80]}"


async def _window_control(env: Env, i: dict) -> str:
    w = _find_window(await _windows(env), i["match"])
    if not w:
        raise ToolFailed(f"No open window matches '{i['match']}'")
    if not await env.run_sys(env.sysctl.window_action, w["id"], {"minimize": "min", "maximize": "max", "close": "close"}[i["action"]]):
        raise ToolFailed("That window is gone")
    return f"{i['action'].capitalize()}d {w['title'][:80]}"


MEDIA_SETTLE = 0.8   # seconds for the player to switch before asking what's on


async def _media(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.media, MEDIA_KEYS[i["action"]])
    await asyncio.sleep(MEDIA_SETTLE)
    try:
        st = await env.nowplaying.get_state(set())
        s = next((x for x in st["sessions"] if x["id"] == st.get("current")), None) or (st["sessions"] or [None])[0]
    except Exception:
        s = None
    if not s or not s.get("title"):
        return f"Sent {i['action'].replace('_', '/')} to the media player"
    by = f" by {s['artist']}" if s.get("artist") else ""
    return f"{'Now playing' if s['status'] == 'playing' else 'Paused'}: {s['title']}{by} ({s['app']})"


async def _volume_report(env: Env, wanted: int | None) -> str:
    """What the laptop's volume really is now, so the reply never claims a level it didn't reach."""
    v, muted = await env.run_sys(env.sysctl.get_volume)
    if v is None:
        return f"Volume set to {wanted}%" if wanted is not None else "Done"
    off = f" (asked for {wanted}%)" if wanted is not None and abs(v - wanted) > 1 else ""
    return f"Volume is now {v}%{' and muted' if muted else ''}{off}"


async def _set_volume(env: Env, i: dict) -> str:
    v = max(0, min(100, int(i["percent"])))
    await env.run_sys(env.sysctl.set_volume, v, None)
    return await _volume_report(env, v)


async def _change_volume(env: Env, i: dict) -> str:
    cur, _ = await env.run_sys(env.sysctl.get_volume)
    if cur is None:
        raise ToolFailed("Couldn't read the current volume")
    v = max(0, min(100, cur + (10 if i["direction"] == "up" else -10)))
    await env.run_sys(env.sysctl.set_volume, v, None)
    return await _volume_report(env, v)


async def _mute(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.set_volume, None, bool(i["muted"]))
    _, muted = await env.run_sys(env.sysctl.get_volume)
    if muted is None or bool(muted) == bool(i["muted"]):
        return "Muted" if i["muted"] else "Unmuted"
    raise ToolFailed("The laptop didn't change its mute setting")


async def _brightness_report(env: Env, wanted: int | None) -> str:
    b = await env.run_sys(env.sysctl.get_brightness)
    if b is None:   # some screens (and external monitors) don't report it
        return f"Brightness set to {wanted}%" if wanted is not None else "Brightness changed"
    off = f" (asked for {wanted}%)" if wanted is not None and abs(b - wanted) > 2 else ""
    return f"Brightness is now {b}%{off}"


async def _set_brightness(env: Env, i: dict) -> str:
    v = max(0, min(100, int(i["percent"])))
    await env.run_sys(env.sysctl.set_brightness, v)
    return await _brightness_report(env, v)


async def _change_brightness(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.step_brightness, i["direction"] == "up")
    return await _brightness_report(env, None)


async def _type_text(env: Env, i: dict) -> str:
    await asyncio.to_thread(env.inp.type_text, i["text"][:10000])
    return f"Typed {len(i['text'])} characters into the active window"


async def _press_keys(env: Env, i: dict) -> str:
    env.inp.hotkey(policy.normalize_keys(i["keys"]))
    return f"Pressed {i['keys']}"


async def _run_quick_action(env: Env, i: dict) -> str:
    from ..actions import run_action
    a = _find_action(env, i["name"])
    if not a:
        raise ToolFailed(f"No quick action named '{i['name']}'. Available: " + ", ".join(x["name"] for x in env.actions.items))
    await run_action(a, env.inp, env.sysctl, env.run_sys)
    return f"Ran quick action {a['name']}"


async def _power(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.power, i["action"])
    return f"Done: {i['action']}"


async def _set_clipboard(env: Env, i: dict) -> str:
    ok = await env.run_sys(env.sysctl.set_clipboard, i["text"][:100000])
    if not ok:
        raise ToolFailed("Couldn't set the clipboard")
    return "Copied to the laptop clipboard"


async def _wait(env: Env, i: dict) -> str:
    s = max(0.0, min(10.0, float(i["seconds"])))
    await asyncio.sleep(s)
    return f"Waited {s:g}s"


_BROWSER_WORDS = {"browser", "web browser", "website", "web", "page", "web page", "the browser"}


def _default_browser_window(wins: list[dict]) -> dict | None:
    """The most recently used window of the Windows default browser (else of any browser): the profile the
    user has in front is the one acted on."""
    default = browser_access.default_browser()
    owned = [(w, browser_access.owner_of_window(int(w["id"]))[0]) for w in wins]
    return (next((w for w, exe in owned if exe and exe == default), None)
            or next((w for w, exe in owned if exe in browser_access.BROWSERS), None))


async def _read_app(env: Env, i: dict) -> str:
    wins = await _windows(env)
    want = i["window"].strip()
    if want.lower() in _BROWSER_WORDS and sys.platform == "win32":
        w = await asyncio.to_thread(_default_browser_window, wins)   # windows come newest first
    else:
        w = _find_window(wins, want) if want else next((x for x in wins if x.get("active")), None)
    if not w:
        raise ToolFailed(f"No open window matches '{want}'" if want else "No window is active")
    hwnd = int(w["id"])
    exe, pid = await asyncio.to_thread(browser_access.owner_of_window, hwnd) if sys.platform == "win32" else (None, 0)
    browser = exe in browser_access.BROWSERS
    if browser:
        _page_target.update(exe=exe, pid=pid)
        if browser_access.process_can_read_pages(pid):
            await asyncio.to_thread(browser_access.wait_until_ready)   # just restarted: let the page show itself
    try:
        snap = await asyncio.to_thread(appui.read, hwnd, w.get("app", ""))
        # a browser hides a page that's minimized or covered, and fills it in a moment after it's first asked:
        # bring it to the front, then ask again shortly
        for attempt in range(PAGE_RETRIES if browser and browser_access.process_can_read_pages(pid) else 0):
            if snap.has_page:
                break
            if attempt == 0:
                await env.run_sys(env.sysctl.window_action, hwnd, "focus")
            await asyncio.sleep(1.5)
            snap = await asyncio.to_thread(appui.read, hwnd, w.get("app", ""))
    except appui.AppUIError as e:
        raise ToolFailed(str(e)) from None
    text = appui.describe(snap)
    if browser and not browser_access.process_can_read_pages(pid):
        text += (f"\nNOTE: {browser_access.BROWSERS[exe]} was started without page reading, so only its own buttons are "
                 "listed, not the web page. Call enable_page_reading to restart it with the user's tabs (it asks them first).")
    return text


_page_target: dict = {}   # the browser of the last window read: the one enable_page_reading restarts
PAGE_RETRIES = 3


def _browser_target() -> tuple[str | None, int | None]:
    exe = _page_target.get("exe") or browser_access.default_browser()
    return exe, _page_target.get("pid") if _page_target.get("exe") == exe else None


async def _enable_page_reading(env: Env, i: dict) -> str:
    exe, pid = _browser_target()
    if not exe:
        raise ToolFailed("No supported browser (Edge, Chrome or Brave) was found")
    try:
        return await asyncio.to_thread(browser_access.restart_with_page_reading, exe, pid)
    except (browser_access.BrowserAccessError, OSError, subprocess.SubprocessError) as e:
        raise ToolFailed(str(e)) from None


def _browser_name() -> str:
    exe, _ = _browser_target()
    return browser_access.BROWSERS.get(exe or "", "the browser")


async def _press_control(env: Env, i: dict) -> str:
    try:
        return await asyncio.to_thread(appui.press, int(i["item"]))
    except appui.AppUIError as e:
        raise ToolFailed(str(e)) from None


async def _fill_control(env: Env, i: dict) -> str:
    try:
        return await asyncio.to_thread(appui.fill, int(i["item"]), i["text"][:5000])
    except appui.AppUIError as e:
        raise ToolFailed(str(e)) from None


def _last_item(i: dict):
    snap = appui.last()
    try:
        return snap, (snap.item(int(i["item"])) if snap else None)
    except appui.AppUIError:
        return snap, None


def _risk_read(i, f, e):
    # its list goes to the AI: a sign-in or payment window's contents need a yes first
    want = i["window"].strip()
    title = want or foreground_title(f)
    if policy.SENSITIVE_WINDOW.search(title):
        return CONFIRM, f"this looks like a sign-in or payment window ({title[:60]}): its contents would go to the AI"
    return SAFE, ""


def _risk_press(i, f, e):
    snap, item = _last_item(i)
    return policy.judge_button(item.name, f"{snap.app} {snap.title}") if item else (SAFE, "")


def _risk_fill(i, f, e):
    snap, item = _last_item(i)
    if not item:
        return SAFE, ""
    if item.password:
        return BLOCKED, "it's a password field: the assistant never types passwords"
    return policy.judge_typing({"app": snap.app, "title": f"{snap.title} {item.name}"})


def _label_press(i):
    snap, item = _last_item(i)
    return f"Press '{item.name}' in {snap.title[:50]}" if item else f"Pressing item {i['item']}"


def _label_fill(i):
    snap, item = _last_item(i)
    return f"Type into '{item.name}' in {snap.title[:50]}: {i['text'][:40]}" if item else f"Typing into item {i['item']}"


def foreground_title(fg: dict | None) -> str:
    return f"{(fg or {}).get('app', '')} {(fg or {}).get('title', '')}"


class ToolFailed(Exception):
    """Reported back to the AI as a tool error, which it can explain or work around."""


def _find_action(env: Env, name: str) -> dict | None:
    n = name.strip().lower()
    return next((a for a in env.actions.items if a["name"].lower() == n), None)


# ---------------- risk ----------------

def _risk_url(i, f, e):
    why = policy.check_url(i["url"])
    return (BLOCKED, why) if why else (SAFE, "")


def _risk_window(i, f, e):
    return (CONFIRM, "the app might lose unsaved work") if i["action"] == "close" else (SAFE, "")


def _risk_power(i, f, e):
    return (SAFE, "") if i["action"] in policy.SAFE_POWER else (CONFIRM, "this affects the whole laptop")


def _risk_action(i, f, e):
    a = _find_action(e, i["name"])
    if a and (a["type"] == "command" or (a["type"] == "macro" and "cmd " in a["value"].lower())):
        return CONFIRM, "this quick action runs a command"
    return SAFE, ""


_P = lambda t, d="": {"type": t, "description": d} if d else {"type": t}  # noqa: E731
_E = lambda *v: {"type": "string", "enum": list(v)}  # noqa: E731

TOOLS: list[Tool] = [
    Tool("get_windows", "List the windows open on the laptop and which one is active.", {}, _get_windows,
         label=lambda i: "Checking open windows"),
    Tool("get_now_playing", "What media is playing on the laptop.", {}, _get_now_playing,
         label=lambda i: "Checking what's playing"),
    Tool("get_system_status", "Current volume, brightness, battery, CPU and RAM.", {}, _get_system_status,
         label=lambda i: "Checking the laptop's status"),
    Tool("get_time", "The current time and date on the laptop.", {}, _get_time, label=lambda i: "Checking the time"),
    Tool("open_url", "Open an http(s) link in the laptop's default browser.", {"url": _P("string")}, _open_url,
         risk=_risk_url, label=lambda i: f"Opening {i['url'][:60]}"),
    Tool("web_search", "Open search results for a query on a site, in the laptop's browser.",
         {"site": _E(*SEARCH_SITES), "query": _P("string")}, _web_search,
         label=lambda i: f"Searching {i['site']} for {i['query'][:50]}"),
    Tool("play_youtube", "Play a song or video on YouTube: opens YouTube's top result for the query, so it starts "
                         "playing. Use this whenever the user wants something played, not web_search.",
         {"query": _P("string")}, _play_youtube, label=lambda i: f"Playing {i['query'][:50]} on YouTube"),
    Tool("open_app", "Open an installed app by its name, e.g. notepad, calc, chrome, excel. Names only, not paths. "
                     "Also for services with a desktop app (ChatGPT, Claude, WhatsApp, Spotify, Teams...): it opens the "
                     "installed app, or their website when the app isn't installed. Its result says which.",
         {"name": _P("string")}, _open_app,
         risk=lambda i, f, e: policy.check_app(i["name"]), label=lambda i: f"Opening {i['name']}"),
    Tool("switch_window", "Bring an open window to the front. `match` is part of its title or app name.",
         {"match": _P("string")}, _switch_window, label=lambda i: f"Switching to {i['match']}"),
    Tool("window_control", "Minimize, maximize or close an open window. `match` is part of its title or app name.",
         {"match": _P("string"), "action": _E("minimize", "maximize", "close")}, _window_control, risk=_risk_window,
         label=lambda i: f"{i['action'].capitalize()} {i['match']}"),
    Tool("media", "Control what is playing.", {"action": _E(*MEDIA_KEYS)}, _media,
         label=lambda i: f"Media: {i['action'].replace('_', '/')}"),
    Tool("set_volume", "Set the volume, 0 to 100.", {"percent": _P("integer")}, _set_volume,
         label=lambda i: f"Volume {i['percent']}%"),
    Tool("change_volume", "Raise or lower the volume a little.", {"direction": _E("up", "down")}, _change_volume,
         label=lambda i: f"Volume {i['direction']}"),
    Tool("mute", "Mute or unmute the laptop.", {"muted": _P("boolean")}, _mute,
         label=lambda i: "Mute" if i["muted"] else "Unmute"),
    Tool("set_brightness", "Set screen brightness, 0 to 100.", {"percent": _P("integer")}, _set_brightness,
         label=lambda i: f"Brightness {i['percent']}%"),
    Tool("change_brightness", "Raise or lower screen brightness a little.", {"direction": _E("up", "down")},
         _change_brightness, label=lambda i: f"Brightness {i['direction']}"),
    Tool("type_text", "Type text into the active window. Bring the right window to the front first.",
         {"text": _P("string")}, _type_text, risk=lambda i, f, e: policy.judge_typing(f),
         label=lambda i: f"Typing: {i['text'][:60]}"),
    Tool("press_keys", "Press a shortcut in the active window, e.g. enter, ctrl+s, ctrl+a, alt+tab.",
         {"keys": _P("string")}, _press_keys, risk=lambda i, f, e: policy.judge_keys(i["keys"], f),
         label=lambda i: f"Pressing {i['keys']}"),
    Tool("run_quick_action", "Run one of the user's saved quick actions by its exact name.", {"name": _P("string")},
         _run_quick_action, risk=_risk_action, label=lambda i: f"Quick action: {i['name']}"),
    Tool("power", "Lock, display off, sleep, sign out, restart or shut down the laptop.",
         {"action": _E(*POWER_LABEL)}, _power, risk=_risk_power, label=lambda i: POWER_LABEL[i["action"]]),
    Tool("set_clipboard", "Put text on the laptop's clipboard.", {"text": _P("string")}, _set_clipboard,
         label=lambda i: "Copying to the clipboard"),
    Tool("wait", "Pause between steps, up to 10 seconds, e.g. while an app opens.", {"seconds": _P("number")}, _wait,
         label=lambda i: f"Waiting {i['seconds']}s"),
    Tool("read_app", "List the buttons, menus, tabs, links and text boxes of a desktop app's window, each with a "
                     "number, plus the text it shows. `window` is part of its title or app name; \"\" = the active "
                     "window. Use the numbers with press_control and fill_control. Numbers change: read again after "
                     "anything changes the window. For a web page, use window \"browser\": the Windows default "
                     "browser's most recent window, in the profile the user has open.",
         {"window": _P("string")}, _read_app, risk=_risk_read,
         label=lambda i: f"Reading the buttons in {i['window'] or 'the active window'}"),
    Tool("enable_page_reading", "Restart the user's browser (the one last read, else their default) with web page "
                                "reading switched on, reopening their tabs, so read_app can list a page's links, "
                                "buttons and boxes. Asks the user first. Needed once per browser session.",
         {}, _enable_page_reading,
         risk=lambda i, f, e: (CONFIRM, f"this closes and reopens {_browser_name()} with your tabs; anything typed "
                                        f"into a page but not sent may be lost"),
         label=lambda i: f"Restart {_browser_name()} so the assistant can read web pages"),
    Tool("press_control", "Press, tick or open item number `item` from the last read_app list. Then read_app again to "
                          "check it worked.", {"item": _P("integer")}, _press_control, risk=_risk_press, label=_label_press),
    Tool("fill_control", "Type `text` into text box number `item` from the last read_app list (replaces what's there).",
         {"item": _P("integer"), "text": _P("string")}, _fill_control, risk=_risk_fill, label=_label_fill),
]
BY_NAME = {t.name: t for t in TOOLS}


def schemas() -> list[dict]:
    """Stable order and content: this list is part of the cached prompt prefix."""
    return [t.schema() for t in TOOLS]
