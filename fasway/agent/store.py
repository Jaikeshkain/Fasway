"""What the agent remembers on disk: settings, today's spending, and the recent task history."""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .llm import DEFAULT_MODEL, MODELS

log = logging.getLogger("fasway")
KEEP_TASKS = 50
INR_PER_USD = 85.0    # only for showing and limiting spending in rupees; approximate on purpose
DEFAULTS = {"model": DEFAULT_MODEL, "task_budget_inr": 30, "daily_budget_inr": 150}


@dataclass
class Task:
    id: str
    goal: str
    device: str = ""
    state: str = "running"   # running | waiting_approval | done | failed | stopped | over_budget
    source: str = "ai"       # builtin | routine | ai
    model: str = ""
    reply: str = ""
    steps: list[dict] = field(default_factory=list)   # {"text", "status": running|done|failed|declined}
    usd: float = 0.0
    created: float = field(default_factory=time.time)
    finished: float = 0.0

    @classmethod
    def new(cls, goal: str, device: str = "") -> "Task":
        return cls(id=uuid.uuid4().hex[:10], goal=goal[:2000], device=device)

    @property
    def active(self) -> bool:
        return self.state in ("running", "waiting_approval")

    def public(self) -> dict:
        d = asdict(self)
        d["inr"] = round(self.usd * INR_PER_USD, 2)
        return d


class AgentStore:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "agent"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings = {**DEFAULTS, **self._read("settings.json", {})}
        if self.settings["model"] not in MODELS:
            self.settings["model"] = DEFAULT_MODEL
        self.usage: dict = self._read("usage.json", {})
        self.tasks: list[Task] = []
        for t in self._read("tasks.json", []):
            try:
                task = Task(**t)
            except TypeError:
                continue
            if task.active:   # Fasway restarted mid-task: never carry on blindly
                task.state, task.reply = "stopped", "Stopped because Fasway restarted."
                task.finished = task.finished or time.time()
            self.tasks.append(task)

    def _read(self, name: str, default):
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, name: str, data):
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.dir / name)

    # ---- settings ----
    def set(self, **changes):
        for k, v in changes.items():
            if k == "model" and v in MODELS:
                self.settings["model"] = v
            elif k in ("task_budget_inr", "daily_budget_inr"):
                try:
                    self.settings[k] = max(1, min(100000, int(v)))
                except (TypeError, ValueError):
                    pass
        self._write("settings.json", self.settings)

    # ---- spending ----
    @staticmethod
    def _today() -> str:
        return dt.date.today().isoformat()

    def spent_today_usd(self) -> float:
        return float(self.usage.get(self._today(), {}).get("usd", 0.0))

    def commands_today(self) -> int:
        return int(self.usage.get(self._today(), {}).get("commands", 0))

    def add_usage(self, usd: float = 0.0, commands: int = 0):
        day = self.usage.setdefault(self._today(), {"usd": 0.0, "commands": 0})
        day["usd"] += usd
        day["commands"] += commands
        for old in sorted(self.usage)[:-60]:   # keep two months
            del self.usage[old]
        try:
            self._write("usage.json", self.usage)
        except OSError as e:
            log.warning("agent: couldn't save usage: %s", e)

    # ---- tasks ----
    def add(self, task: Task):
        self.tasks.append(task)
        self.tasks = self.tasks[-KEEP_TASKS:]
        self.save_tasks()

    def get(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def save_tasks(self):
        try:
            self._write("tasks.json", [asdict(t) for t in self.tasks])
        except OSError as e:
            log.warning("agent: couldn't save tasks: %s", e)
