"""What the agent can do on the laptop. Each tool wraps a function Fasway already has, and declares its risk.

There is deliberately no shell tool, no file deletion and no way to enter credentials. A model can only
call what is listed here, and every input is re-checked here: tool schemas can't enforce safety.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import quote_plus

from . import apps, policy
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


async def _open_app(env: Env, i: dict) -> str:
    name = i["name"].strip()
    try:
        await env.run_sys(env.sysctl.open_target, name)
    except OSError:
        # not a command Windows knows: look through what's installed ("whatsapp", "power bi")
        target = await asyncio.to_thread(apps.find, name)
        if not target:
            raise ToolFailed(f"I couldn't find an app called {name} on this laptop") from None
        await env.run_sys(env.sysctl.open_target, target)
    await asyncio.sleep(0.8)    # let it appear before the next step types into it
    return f"Opened {name}"


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


async def _media(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.media, MEDIA_KEYS[i["action"]])
    return f"Media: {i['action']}"


async def _set_volume(env: Env, i: dict) -> str:
    v = max(0, min(100, int(i["percent"])))
    await env.run_sys(env.sysctl.set_volume, v, None)
    return f"Volume set to {v}%"


async def _change_volume(env: Env, i: dict) -> str:
    cur, _ = await env.run_sys(env.sysctl.get_volume)
    if cur is None:
        raise ToolFailed("Couldn't read the current volume")
    v = max(0, min(100, cur + (10 if i["direction"] == "up" else -10)))
    await env.run_sys(env.sysctl.set_volume, v, None)
    return f"Volume now {v}%"


async def _mute(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.set_volume, None, bool(i["muted"]))
    return "Muted" if i["muted"] else "Unmuted"


async def _set_brightness(env: Env, i: dict) -> str:
    v = max(0, min(100, int(i["percent"])))
    await env.run_sys(env.sysctl.set_brightness, v)
    return f"Brightness set to {v}%"


async def _change_brightness(env: Env, i: dict) -> str:
    await env.run_sys(env.sysctl.step_brightness, i["direction"] == "up")
    return "Brightness changed"


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
    Tool("open_app", "Open an installed app by its name, e.g. notepad, calc, chrome, excel. Names only, not paths.",
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
]
BY_NAME = {t.name: t for t in TOOLS}


def schemas() -> list[dict]:
    """Stable order and content: this list is part of the cached prompt prefix."""
    return [t.schema() for t in TOOLS]
