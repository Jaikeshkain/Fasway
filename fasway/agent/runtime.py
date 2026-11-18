"""The agent: built-in commands first, then the Claude loop. Every step goes through one gate (_act):
safety rules, approval on the phone if needed, then the tool. Phones get live updates through `broadcast`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Awaitable, Callable

from . import intents, keystore, prompts
from . import tools as T
from .llm import MODELS, PROVIDER_NAMES, LLMError, LLMReply, cost_usd, make_client
from .policy import BLOCKED, CONFIRM, Budget
from .store import INR_PER_USD, AgentStore, Task

log = logging.getLogger("fasway")

MAX_ROUNDS = 20            # requests to Claude per task
MAX_TASK_SECONDS = 600     # time limit per task, including time spent waiting for approvals
APPROVAL_SECONDS = 120     # no answer counts as "no"
MEMORY_SECONDS = 300       # a follow-up ("aur kam karo") within this time continues the conversation
MEMORY_TURNS = 6
EFFORT = "low"             # commands should feel quick; raised for longer tasks in a later milestone
FOCUS_TOOLS = {"type_text", "press_keys"}   # these act on whichever window is in front
# after these, "aur kam karo" or "30 percent" on its own continues the same thing
FOLLOWS = {"set_volume": "volume", "change_volume": "volume", "mute": "volume",
           "set_brightness": "brightness", "change_brightness": "brightness"}
FOLLOW_UP_SECONDS = 120
# their result text says what really happened, so a built-in command replies with it
REPORTS_RESULT = {"set_volume", "change_volume", "set_brightness", "change_brightness", "media", "open_app",
                  "play_youtube", "get_system_status", "get_now_playing", "get_time", "get_windows"}


class Agent:
    def __init__(self, data_dir, env: T.Env, broadcast: Callable[[dict], Awaitable], llm_factory=None, key_source=None):
        self.store = AgentStore(data_dir)
        self.env = env
        self.broadcast = broadcast
        self._llm_factory = llm_factory or make_client       # tests pass a scripted model
        self._key = key_source or keystore.get_key
        self._queue_lock = asyncio.Lock()                    # one task at a time: there is one mouse
        self._running: dict[str, asyncio.Task] = {}
        self._approvals: dict[str, dict] = {}                # id -> {future, task, tool, card}
        # task id -> exact actions the user said yes to for the rest of the task. Never a whole tool:
        # "yes to ctrl+w" must not become "yes to any shortcut".
        self._allowed: dict[str, set] = {}
        self._chats: dict[str, dict] = {}                    # device -> {messages, at, turns, model}
        self._recent: dict[str, tuple[str, float]] = {}      # device -> (what was just changed, when), for follow-ups

    # ---------- messages from the phone ----------
    async def handle(self, device: str, m: dict) -> dict | None:
        t = m.get("t")
        if t == "agent_start":
            text = str(m.get("text", "")).strip()
            if text:
                self.start(device, text)
            return None
        if t == "agent_approve":
            self.answer(str(m.get("id")), bool(m.get("ok")), bool(m.get("remember")))
            return None
        if t == "agent_stop":
            self.stop(str(m.get("task")))
            return None
        if t == "agent_list":
            return {**self.settings_msg(), "t": "agent_list", "tasks": [x.public() for x in self.store.tasks[-30:]],
                    "approvals": [a["card"] for a in self._approvals.values()]}
        if t == "agent_settings":
            return self.settings_msg()
        if t == "agent_set":
            self.store.set(**{k: m[k] for k in ("model", "task_budget_inr", "daily_budget_inr") if k in m})
            await self.broadcast(self.settings_msg())
            return None
        if t == "agent_reset":
            self._chats.pop(device, None)
            return None
        return None

    def settings_msg(self) -> dict:
        s = self.store.settings
        return {"t": "agent_settings", "model": s["model"], "has_key": bool(self._key(MODELS[s["model"]]["provider"])),
                "models": [{"id": k, "label": v["label"], "hint": v["hint"], "has_key": bool(self._key(v["provider"]))}
                           for k, v in MODELS.items()],
                "task_budget_inr": s["task_budget_inr"], "daily_budget_inr": s["daily_budget_inr"],
                "spent_today_inr": round(self.store.spent_today_usd() * INR_PER_USD, 2),
                "commands_today": self.store.commands_today()}

    # ---------- starting and stopping ----------
    def start(self, device: str, goal: str) -> Task:
        task = Task.new(goal, device)
        self.store.add(task)
        self._running[task.id] = asyncio.create_task(self._run(task))
        return task

    def stop(self, task_id: str):
        job = self._running.get(task_id)
        if job:
            job.cancel()

    def answer(self, approval_id: str, ok: bool, remember: bool = False):
        a = self._approvals.get(approval_id)
        if not a or a["future"].done():
            return
        if ok and remember:
            self._allowed.setdefault(a["task"].id, set()).add(a["card"]["action"])
        a["future"].set_result(ok)

    # ---------- one task ----------
    async def _run(self, task: Task):
        await self._emit(task)
        try:
            async with self._queue_lock:
                await asyncio.wait_for(self._work(task), MAX_TASK_SECONDS)
        except asyncio.CancelledError:
            self._finish(task, "stopped", "Stopped.")
            self._chats.pop(task.device, None)   # the conversation ended mid-step: start fresh next time
        except asyncio.TimeoutError:
            self._finish(task, "failed", "That took too long, so I stopped.")
            self._chats.pop(task.device, None)
        except LLMError as e:
            self._finish(task, "failed", str(e))
            self._chats.pop(task.device, None)
        except Exception:
            log.exception("agent: task failed")
            self._finish(task, "failed", "Something went wrong on the laptop.")
            self._chats.pop(task.device, None)
        finally:
            self._running.pop(task.id, None)
            self._allowed.pop(task.id, None)
            for s in task.steps:
                if s["status"] == "running":
                    s["status"] = "failed"
            task.finished = task.finished or time.time()
            self.store.save_tasks()
            self.store.add_usage(commands=1)
            await self._emit(task)
            await self._safe_broadcast(self.settings_msg())

    def _finish(self, task: Task, state: str, reply: str):
        task.state, task.reply, task.finished = state, reply, time.time()

    async def _work(self, task: Task):
        model = self.store.settings["model"]
        key = self._key(MODELS[model]["provider"])
        exact = intents.match(task.goal)
        # With a key, the AI reads anything that isn't an exact command: it understands far better than word rules
        recent = self._recent.get(task.device)
        last = recent[0] if recent and time.time() - recent[1] < FOLLOW_UP_SECONDS else None
        plan = [exact] if exact else (None if key else intents.understand(task.goal, last))
        if plan:
            task.source = "builtin"
            replies = []
            for step in plan:
                text, failed = await self._act(task, step.tool, step.input)
                if failed:   # later steps may depend on this one
                    self._finish(task, "failed", text)
                    return
                # what the laptop reports (the level reached, the video found) beats a fixed phrase
                replies.append(text if step.tool in REPORTS_RESULT or not step.reply else step.reply)
                if step.tool in FOLLOWS:
                    self._recent[task.device] = (FOLLOWS[step.tool], time.time())
            self._finish(task, "done", ". ".join(replies))
            return
        if not key:
            self._finish(task, "failed", "I didn't understand that without the AI. Try saying it simply, like \"turn the "
                                         f"volume down\" or \"search cats on YouTube\". For anything more, add an "
                                         f"{PROVIDER_NAMES[MODELS[model]['provider']]} API key in Fasway on the laptop, "
                                         f"for {MODELS[model]['label']}.")
            return
        await self._ai_loop(task, self._llm_factory(model, key))

    # ---------- Claude ----------
    def _chat(self, task: Task, model: str) -> dict:
        chat = self._chats.get(task.device)
        fresh = (not chat or chat["model"] != model or chat["turns"] >= MEMORY_TURNS
                 or time.time() - chat["at"] > MEMORY_SECONDS)
        if fresh:   # history is only ever appended to (the API requires it): a new chat replaces it whole
            chat = self._chats[task.device] = {"messages": [], "turns": 0, "at": time.time(), "model": model}
        return chat

    async def _foreground(self) -> dict | None:
        try:
            wins = await self.env.run_sys(self.env.sysctl.list_windows, set())
            return next((w for w in wins["windows"] if w.get("active")), None)
        except Exception:
            return None

    async def _ai_loop(self, task: Task, llm):
        model = self.store.settings["model"]
        task.model = model
        budget = Budget(self.store.settings["task_budget_inr"] / INR_PER_USD,
                        self.store.settings["daily_budget_inr"] / INR_PER_USD, self.store.spent_today_usd())
        chat = self._chat(task, model)
        messages = chat["messages"]
        fg = await self._foreground()
        ctx = prompts.turn_context(time.strftime("%A %d %B %Y, %H:%M"), f"{fg['title'][:80]}" if fg else "")
        messages.append({"role": "user", "content": f"{ctx}\n\n{task.goal}"})

        for _ in range(MAX_ROUNDS):
            over = budget.exceeded()
            if over:
                self._finish(task, "over_budget", "Stopped: today's AI budget is used up." if over == "day"
                             else "Stopped: this task reached its budget limit.")
                self._chats.pop(task.device, None)
                return
            reply: LLMReply = await llm.create(model=model, system=prompts.SYSTEM, tools=T.schemas(),
                                               messages=messages, effort=EFFORT)
            usd = cost_usd(model, reply.usage)
            task.usd += usd
            budget.add(usd)
            self.store.add_usage(usd=usd)
            log.info("agent: %s stop=%s in=%s cached=%s out=%s", model, reply.stop_reason, reply.usage.get("input_tokens"),
                     reply.usage.get("cache_read_input_tokens"), reply.usage.get("output_tokens"))

            if reply.stop_reason == "refusal":
                log.info("agent: declined: %s", reply.refusal)
                self._finish(task, "failed", "I can't help with that one.")
                self._chats.pop(task.device, None)
                return
            if reply.stop_reason == "max_tokens":   # any tool call in here may be cut off: don't run it
                self._finish(task, "failed", "That answer got too long, so I stopped.")
                self._chats.pop(task.device, None)
                return

            messages.append({"role": "assistant", "content": reply.content})
            if reply.stop_reason == "pause_turn":
                continue
            calls = [b for b in reply.content if b.get("type") == "tool_use"]
            if not calls:
                text = " ".join(b.get("text", "") for b in reply.content if b.get("type") == "text").strip()
                self._finish(task, "done", text or "Done.")
                chat["turns"] += 1
                chat["at"] = time.time()
                return

            results = []
            for call in calls:      # in order: "open Notepad, then type" must not race
                text, is_error = await self._act(task, call["name"], call.get("input") or {})
                r = {"type": "tool_result", "tool_use_id": call["id"], "content": text}
                if is_error:
                    r["is_error"] = True
                results.append(r)
            messages.append({"role": "user", "content": results})   # all results together, in one message

        self._finish(task, "failed", "I couldn't finish that within the step limit.")
        self._chats.pop(task.device, None)

    # ---------- the one gate every action goes through ----------
    async def _act(self, task: Task, name: str, inp: dict) -> tuple[str, bool]:
        """Returns (result text for the AI, is_error)."""
        tool = T.BY_NAME.get(name)
        if not tool:
            return f"Unknown tool: {name}", True
        try:
            label = tool.label(inp) or name
            fg = await self._foreground()
            verdict, why = tool.risk(inp, fg, self.env)
        except (KeyError, TypeError, ValueError) as e:
            return f"Invalid input for {name}: {e}", True

        step = {"text": label, "status": "running"}
        task.steps.append(step)
        await self._emit(task)

        if verdict == BLOCKED:
            step["status"] = "declined"
            log.info("agent: blocked %s %s: %s", name, json.dumps(inp, ensure_ascii=False)[:200], why)
            await self._emit(task)
            return f"Not allowed: {why}", True
        if verdict == CONFIRM and label not in self._allowed.get(task.id, ()):
            if not await self._ask(task, tool, label, why):
                step["status"] = "declined"
                await self._emit(task)
                return "The user declined this step, so it was not done.", True
            if name in FOCUS_TOOLS:     # the yes was for the window shown when we asked
                now = await self._foreground()
                if (now or {}).get("id") != (fg or {}).get("id"):
                    step["status"] = "declined"
                    await self._emit(task)
                    return "The active window changed while waiting for approval, so this was not done.", True
        try:
            text = await tool.run(self.env, inp)
            step["status"] = "done"
            log.info("agent: did %s %s", name, json.dumps(inp, ensure_ascii=False)[:200])
            return text, False
        except asyncio.CancelledError:
            raise
        except T.ToolFailed as e:
            step["status"] = "failed"
            return str(e), True
        except Exception as e:
            log.warning("agent: %s failed: %s", name, e)
            step["status"] = "failed"
            return f"That step failed: {e}", True
        finally:
            await self._emit(task)

    async def _ask(self, task: Task, tool: T.Tool, label: str, why: str) -> bool:
        aid = uuid.uuid4().hex[:10]
        fut = asyncio.get_running_loop().create_future()
        card = {"id": aid, "task": task.id, "tool": tool.name, "action": label, "why": why, "seconds": APPROVAL_SECONDS}
        self._approvals[aid] = {"future": fut, "task": task, "tool": tool.name, "card": card}
        task.state = "waiting_approval"
        await self._emit(task)
        await self.broadcast({"t": "agent_approval", **card})
        try:
            ok = await asyncio.wait_for(fut, APPROVAL_SECONDS)   # no answer = no
        except asyncio.TimeoutError:
            ok = False
        finally:
            self._approvals.pop(aid, None)
            await self._safe_broadcast({"t": "agent_approval_done", "id": aid})
        log.info("agent: approval for %s: %s", label, "yes" if ok else "no")
        task.state = "running"
        return ok

    async def _safe_broadcast(self, msg: dict):
        try:
            await self.broadcast(msg)
        except Exception:
            pass

    async def _emit(self, task: Task):
        await self._safe_broadcast({"t": "agent_task", "task": task.public()})
