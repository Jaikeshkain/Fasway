"""Routines: one phrase ("good night", "study mode") runs several steps, with no AI and no cost.

Stored on the laptop (data/routines.json). Each step is an ordinary assistant tool call, so it goes through
the same gate as everything else: shutting down still asks on the phone, blocked things stay blocked.
Made on the phone (Apps tab), or by asking the assistant ("make a routine called gym time that ...").
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path

# what a routine step may do: the assistant's everyday tools, never typing or reading/pressing app controls
STEP_TOOLS = {"set_volume", "change_volume", "mute", "set_brightness", "change_brightness", "media", "open_app",
              "open_url", "web_search", "play_youtube", "power", "press_keys", "run_quick_action", "wait",
              "switch_window", "window_control", "get_time", "get_system_status", "get_now_playing"}
MAX_STEPS = 12
MAX_ROUTINES = 40

DEFAULTS = [
    {"icon": "🌙", "name": "Good night", "phrases": ["good night", "goodnight", "gn", "shubh ratri", "so raha hoon",
                                                     "sone ja raha hoon", "sone ja rahi hoon", "शुभ रात्रि"],
     "steps": [{"tool": "mute", "input": {"muted": True}},
               {"tool": "set_brightness", "input": {"percent": 10}},
               {"tool": "power", "input": {"action": "sleep"}}]},
    {"icon": "📚", "name": "Study mode", "phrases": ["study mode", "study time", "padhai mode", "padhai karni hai"],
     "steps": [{"tool": "play_youtube", "input": {"query": "lofi study music"}},
               {"tool": "wait", "input": {"seconds": 3}},
               {"tool": "set_volume", "input": {"percent": 30}}]},
    {"icon": "☀️", "name": "Good morning", "phrases": ["good morning", "gm", "suprabhat", "शुभ प्रभात"],
     "steps": [{"tool": "mute", "input": {"muted": False}},
               {"tool": "set_volume", "input": {"percent": 40}},
               {"tool": "set_brightness", "input": {"percent": 80}},
               {"tool": "get_time", "input": {}},
               {"tool": "get_system_status", "input": {}}]},
]


class RoutineError(ValueError):
    pass


def phrase_key(text: str) -> str:
    """How a phrase is compared: lower case, no punctuation, single spaces, no "please" or "mode on"."""
    t = re.sub(r"[.,!?;:।\"']+", " ", text.lower())
    t = re.sub(r"^(?:hey |hi |ok |okay |please |plz |start |run |chalu karo |shuru karo )+", "", f"{t.strip()} ")
    t = re.sub(r"(?: (?:please|plz|karo|kar do|chalu|shuru|on|start|routine|now|abhi))+ ?$", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def clean(r: dict, tools: dict) -> dict:
    """A routine from the phone or the AI, checked. `tools`: the assistant's tools by name (to check inputs)."""
    name = str(r.get("name") or "").strip()[:40]
    if not name:
        raise RoutineError("a routine needs a name")
    phrases = [str(p).strip()[:60] for p in (r.get("phrases") or []) if str(p).strip()][:10]
    steps = []
    for s in (r.get("steps") or [])[:MAX_STEPS + 1]:
        tool, inp = str(s.get("tool", "")), s.get("input") or {}
        if tool not in STEP_TOOLS or tool not in tools:
            raise RoutineError(f"a routine can't use '{tool}'")
        if not isinstance(inp, dict):
            raise RoutineError(f"bad input for {tool}")
        need = tools[tool].props
        missing = [k for k in need if k not in inp]
        if missing:
            raise RoutineError(f"{tool} needs {', '.join(missing)}")
        steps.append({"tool": tool, "input": {k: inp[k] for k in need}})
    if not steps:
        raise RoutineError("a routine needs at least one step")
    if len(steps) > MAX_STEPS:
        raise RoutineError(f"a routine can have at most {MAX_STEPS} steps")
    return {"id": str(r.get("id") or uuid.uuid4().hex[:8])[:16], "icon": str(r.get("icon") or "⚡")[:8],
            "name": name, "phrases": phrases, "steps": steps}


class Routines:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "routines.json"
        self._lock = threading.Lock()
        self.items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(items, list):
                return [r for r in items if isinstance(r, dict) and r.get("name") and r.get("steps")]
        except (OSError, ValueError):
            pass
        return [{"id": uuid.uuid4().hex[:8], **r} for r in DEFAULTS]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")

    def find(self, text: str) -> dict | None:
        """The routine this sentence asks for: its name or one of its phrases, said on its own."""
        key = phrase_key(text)
        if not key:
            return None
        for r in self.items:
            if key in {phrase_key(p) for p in [r["name"], *r.get("phrases", [])]}:
                return r
        return None

    def get(self, rid: str) -> dict | None:
        return next((r for r in self.items if r["id"] == rid), None)

    def save(self, r: dict, tools: dict) -> dict:
        c = clean(r, tools)
        with self._lock:
            # the same name replaces that routine (the AI says "make good night also lock the laptop")
            old = self.get(c["id"]) or next((x for x in self.items if x["name"].lower() == c["name"].lower()), None)
            if old:
                c["id"] = old["id"]
                self.items[self.items.index(old)] = c
            else:
                if len(self.items) >= MAX_ROUTINES:
                    raise RoutineError(f"there are already {MAX_ROUTINES} routines")
                self.items.append(c)
            taken = {phrase_key(p) for x in self.items if x is not c for p in [x["name"], *x.get("phrases", [])]}
            clash = [p for p in [c["name"], *c["phrases"]] if phrase_key(p) in taken]
            if clash:   # one phrase must never start two routines
                c["phrases"] = [p for p in c["phrases"] if p not in clash]
                if phrase_key(c["name"]) in taken:
                    self.items.remove(c)
                    raise RoutineError(f"another routine already uses the name '{c['name']}'")
            self._save()
        return c

    def delete(self, rid: str) -> bool:
        with self._lock:
            n = len(self.items)
            self.items = [r for r in self.items if r["id"] != rid]
            if len(self.items) != n:
                self._save()
                return True
        return False

    def by_name(self, name: str) -> dict | None:
        n = name.strip().lower()
        return next((r for r in self.items if r["name"].lower() == n), None) or self.find(name)
