"""App controls: the named buttons, menus, tabs and text boxes of a window, read through Windows UI
Automation (what screen readers use), and pressed or filled by the number they were listed under.

The AI never clicks positions on the screen: it reads a list ("[7] Button: Logout"), picks a number, and
Fasway presses that exact control. Works for most desktop apps and for pages in Chrome / Edge, in the
user's own browser with its logins. Windows only; elsewhere the tools say so.

All UI Automation work runs on one thread of its own: its objects belong to the thread that made them.
"""
from __future__ import annotations

import concurrent.futures
import logging
import re
import sys
import time
from dataclasses import dataclass, field

log = logging.getLogger("fasway")

MAX_ITEMS = 160        # a list longer than this is more than the AI can use, and costs more
MAX_SECONDS = 4.0      # some apps have huge trees: stop reading and say the list is partial
MAX_DEPTH = 40

# What people press, pick or type into. Text is listed too (as context, no number) so the AI can tell
# "Logged in as Priya" from "Sign in".
_ACTIONABLE = {"ButtonControl": "Button", "SplitButtonControl": "Button", "MenuItemControl": "Menu item",
               "TabItemControl": "Tab", "HyperlinkControl": "Link", "CheckBoxControl": "Checkbox",
               "RadioButtonControl": "Option", "ComboBoxControl": "Dropdown", "EditControl": "Text box",
               "ListItemControl": "List item", "TreeItemControl": "Tree item", "DataItemControl": "Row"}
_CONTEXT = {"TextControl": "Text", "HeaderControl": "Heading", "TitleBarControl": None, "StatusBarControl": "Status"}


class AppUIError(Exception):
    """Shown to the AI as the step's error."""


@dataclass
class Item:
    number: int
    kind: str          # "Button", "Text box"...
    name: str
    control: object = field(repr=False)
    password: bool = False


@dataclass
class Snapshot:
    """The last window read: its numbers stay valid until the next read."""
    hwnd: int
    title: str
    app: str
    items: list[Item]
    at: float = field(default_factory=time.time)
    has_page: bool = False   # a web page's contents were in the window (browsers fill them in a moment after asked)

    def item(self, number: int) -> Item:
        found = next((i for i in self.items if i.number == number), None)
        if found is None:
            raise AppUIError(f"There is no item {number} in the last list; read the app again")
        return found


_pool: concurrent.futures.ThreadPoolExecutor | None = None
_last: Snapshot | None = None


def _init_thread():
    import uiautomation as auto
    # kept for the thread's lifetime: UI Automation's COM objects live and die with this thread
    _init_thread.keep = auto.UIAutomationInitializerInThread()


def _run(fn, *args):
    """Run on the UI Automation thread and wait (callers are already off the event loop)."""
    global _pool
    if sys.platform != "win32":
        raise AppUIError("Reading app buttons only works on Windows for now")
    if _pool is None:
        _pool = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="appui", initializer=_init_thread)
    return _pool.submit(fn, *args).result(timeout=MAX_SECONDS + 10)


def last() -> Snapshot | None:
    return _last


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("​", "")).strip()


def _read(hwnd: int, app: str) -> Snapshot:
    import uiautomation as auto
    win = auto.ControlFromHandle(hwnd)
    if win is None:
        raise AppUIError("That window is gone")
    items: list[Item] = []
    lines_seen: set[tuple[str, str]] = set()
    deadline = time.monotonic() + MAX_SECONDS
    n = 0
    has_page = False
    for c, _depth in auto.WalkControl(win, maxDepth=MAX_DEPTH):
        if time.monotonic() > deadline or len(items) >= MAX_ITEMS:
            items.append(Item(0, "Note", "list cut short: the window has more", None))
            break
        try:
            kind_name = c.ControlTypeName
            name = _clean(c.Name)[:80]
            if kind_name == "DocumentControl" and not has_page:
                has_page = c.GetFirstChildControl() is not None
        except Exception:   # an element that vanished mid-walk
            continue
        if kind_name in _ACTIONABLE:
            kind = _ACTIONABLE[kind_name]
            try:
                password = kind == "Text box" and bool(c.IsPassword)
                if not c.IsEnabled:
                    kind += " (disabled)"
            except Exception:
                password = False
            if not name and not kind.startswith("Text box"):
                continue   # an unnamed button or row says nothing the AI could choose by
            n += 1
            items.append(Item(n, kind, name or "(no name)", c, password))
        elif _CONTEXT.get(kind_name) and name and (kind_name, name) not in lines_seen:
            lines_seen.add((kind_name, name))
            items.append(Item(0, _CONTEXT[kind_name], name, None))
    title = _clean(win.Name)[:120]
    return Snapshot(hwnd, title, app, items, has_page=has_page)


def read(hwnd: int, app: str) -> Snapshot:
    global _last
    _last = _run(_read, hwnd, app)
    return _last


def describe(s: Snapshot) -> str:
    """The list as the AI reads it. Words in it come from the app: data, never instructions."""
    lines = [f"Window: {s.title} [{s.app}]"]
    for i in s.items:
        extra = " (password field: never type here)" if i.password else ""
        lines.append(f"[{i.number}] {i.kind}: {i.name}{extra}" if i.number else f"    {i.kind}: {i.name}")
    if not any(i.number for i in s.items):
        lines.append("(no buttons or fields could be read in this window)")
    return "\n".join(lines)


def _value(c) -> str | None:
    import uiautomation as auto
    try:
        p = c.GetPattern(auto.PatternId.ValuePattern)
        return p.Value if p else None
    except Exception:
        return None


def _press(item: Item) -> str:
    import uiautomation as auto
    c = item.control
    if not c.Exists(0, 0):
        raise AppUIError(f"'{item.name}' is no longer there; read the app again")
    # the control's own action first: works without moving the user's mouse or needing the window in front
    for pid, act in ((auto.PatternId.InvokePattern, "Invoke"), (auto.PatternId.TogglePattern, "Toggle"),
                     (auto.PatternId.SelectionItemPattern, "Select")):
        try:
            p = c.GetPattern(pid)
        except Exception:
            p = None
        if p:
            getattr(p, act)()
            return f"Pressed '{item.name}'"
    try:
        p = c.GetPattern(auto.PatternId.ExpandCollapsePattern)
    except Exception:
        p = None
    if p:
        (p.Collapse if p.ExpandCollapseState == auto.ExpandCollapseState.Expanded else p.Expand)()
        return f"Opened '{item.name}'"
    try:
        c.GetLegacyIAccessiblePattern().DoDefaultAction()
        return f"Pressed '{item.name}'"
    except Exception:
        pass
    c.Click(simulateMove=False, waitTime=0.2)   # last resort: a real click on its centre
    return f"Clicked '{item.name}'"


def _fill(item: Item, text: str) -> str:
    import uiautomation as auto
    c = item.control
    if not c.Exists(0, 0):
        raise AppUIError(f"'{item.name}' is no longer there; read the app again")
    try:
        p = c.GetPattern(auto.PatternId.ValuePattern)
    except Exception:
        p = None
    if p is None or p.IsReadOnly:
        raise AppUIError(f"'{item.name}' can't be typed into")
    p.SetValue(text)
    return f"Typed into '{item.name}'"


def press(number: int) -> str:
    if _last is None:
        raise AppUIError("Read the app first")
    return _run(_press, _last.item(number))


def fill(number: int, text: str) -> str:
    if _last is None:
        raise AppUIError("Read the app first")
    item = _last.item(number)
    if item.password:
        raise AppUIError("That is a password field: the assistant never types passwords")
    return _run(_fill, item, text)
