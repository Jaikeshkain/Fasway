"""Quick actions: user-defined one-tap buttons, stored on the laptop (actions.json in the data folder).

Types
  open     URL, file, folder or app            e.g. https://youtube.com · notepad · C:\\Users\\me\\Downloads
  text     type a saved snippet                e.g. my.email@example.com
  keys     shortcut(s), comma separated        e.g. ctrl+shift+esc · win+d · ctrl+c, ctrl+v
  macro    one step per line:                  key win+r / type notepad / wait 400 / key enter / open <target>
  command  run a shell command (no window)     e.g. shutdown /h
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

TYPES = ("open", "text", "keys", "macro", "command")

_WIN_DEFAULTS = [
    ("🗂️", "File Explorer", "keys", "win+e"),
    ("📊", "Task Manager", "keys", "ctrl+shift+esc"),
    ("✂️", "Screenshot", "keys", "win+shift+s"),
    ("🖥️", "Show desktop", "keys", "win+d"),
    ("⚙️", "Settings", "keys", "win+i"),
    ("📝", "Notepad", "open", "notepad"),
    ("▶️", "YouTube", "open", "https://www.youtube.com"),
    ("🔎", "Google", "open", "https://www.google.com"),
]
_MAC_DEFAULTS = [
    ("🗂️", "Finder", "open", "Finder"),
    ("📊", "Activity Monitor", "open", "Activity Monitor"),
    ("✂️", "Screenshot", "keys", "cmd+shift+4"),
    ("📝", "TextEdit", "open", "TextEdit"),
    ("▶️", "YouTube", "open", "https://www.youtube.com"),
    ("🔎", "Google", "open", "https://www.google.com"),
]


class QuickActions:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "actions.json"
        self.items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(items, list):
                return [a for a in items if isinstance(a, dict) and a.get("type") in TYPES]
        except (OSError, ValueError):
            pass
        defaults = _MAC_DEFAULTS if sys.platform == "darwin" else _WIN_DEFAULTS
        return [{"id": uuid.uuid4().hex[:8], "icon": i, "name": n, "type": t, "value": v} for i, n, t, v in defaults]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, aid: str) -> dict | None:
        return next((a for a in self.items if a["id"] == aid), None)

    def upsert(self, a: dict) -> dict:
        clean = {"id": str(a.get("id") or uuid.uuid4().hex[:8])[:16],
                 "icon": str(a.get("icon") or "⭐")[:8], "name": str(a.get("name") or "Action")[:40],
                 "type": a.get("type") if a.get("type") in TYPES else "open", "value": str(a.get("value", ""))[:4000]}
        old = self.get(clean["id"])
        if old:
            old.update(clean)
        else:
            self.items.append(clean)
        self._save()
        return clean

    def delete(self, aid: str):
        self.items = [a for a in self.items if a["id"] != aid]
        self._save()

    def move(self, aid: str, delta: int):
        i = next((n for n, a in enumerate(self.items) if a["id"] == aid), None)
        if i is None:
            return
        j = max(0, min(len(self.items) - 1, i + delta))
        self.items.insert(j, self.items.pop(i))
        self._save()


async def run_action(a: dict, inp, sysctl, run_sys):
    """Execute one action. `run_sys` runs a blocking function on the server's system thread."""
    t, v = a["type"], a["value"]
    if t == "open":
        await run_sys(sysctl.open_target, v.strip())
    elif t == "text":
        inp.type_text(v)
    elif t == "keys":
        for combo in v.split(","):
            if combo.strip():
                inp.hotkey(combo.strip())
                await asyncio.sleep(0.08)
    elif t == "command":
        await run_sys(sysctl.run_command, v)
    elif t == "macro":
        for line in v.splitlines():
            cmd, _, arg = line.strip().partition(" ")
            cmd = cmd.lower()
            if cmd == "key":
                inp.hotkey(arg.strip())
            elif cmd == "type":
                inp.type_text(arg)
            elif cmd == "wait":
                await asyncio.sleep(min(max(float(arg or 0), 0), 10000) / 1000)
                continue
            elif cmd == "open":
                await run_sys(sysctl.open_target, arg.strip())
            elif cmd in ("cmd", "run"):
                await run_sys(sysctl.run_command, arg)
            await asyncio.sleep(0.06)  # let the target app react between steps
