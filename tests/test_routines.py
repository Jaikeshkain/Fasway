"""Routines: saved phrases that run several steps with no AI (fake laptop, nothing real is touched)."""
import json
import tempfile
import unittest
from pathlib import Path

from fasway.agent import tools as T
from fasway.agent.routines import RoutineError, Routines, phrase_key
from tests.test_agent import Base, call, say


class Store(unittest.TestCase):
    def setUp(self):
        self.r = Routines(Path(tempfile.mkdtemp()))

    def test_starts_with_examples(self):
        self.assertEqual([x["name"] for x in self.r.items], ["Good night", "Study mode", "Good morning"])

    def test_found_by_name_or_phrase_said_on_its_own(self):
        self.assertEqual(self.r.find("Good night!")["name"], "Good night")
        self.assertEqual(self.r.find("ok so raha hoon")["name"], "Good night")
        self.assertEqual(self.r.find("study mode on karo")["name"], "Study mode")
        self.assertEqual(self.r.find("start study mode please")["name"], "Study mode")
        self.assertIsNone(self.r.find("good night to everyone in the meeting"))
        self.assertIsNone(self.r.find("volume 30"))

    def test_only_everyday_tools_and_complete_inputs(self):
        ok = {"name": "Gym", "steps": [{"tool": "set_volume", "input": {"percent": 80}}]}
        self.r.save(ok, T.BY_NAME)
        for bad in ({"name": "X", "steps": [{"tool": "type_text", "input": {"text": "hi"}}]},
                    {"name": "X", "steps": [{"tool": "press_control", "input": {"item": 1}}]},
                    {"name": "X", "steps": [{"tool": "set_volume", "input": {}}]},
                    {"name": "X", "steps": []},
                    {"name": "", "steps": [{"tool": "mute", "input": {"muted": True}}]}):
            with self.assertRaises(RoutineError):
                self.r.save(bad, T.BY_NAME)

    def test_same_name_replaces_and_survives_restart(self):
        self.r.save({"name": "good night", "steps": [{"tool": "power", "input": {"action": "lock"}}]}, T.BY_NAME)
        names = [x["name"] for x in self.r.items]
        self.assertEqual(names.count("good night") + names.count("Good night"), 1)
        again = Routines(self.r.path.parent)
        self.assertEqual(again.find("good night")["steps"], [{"tool": "power", "input": {"action": "lock"}}])

    def test_a_phrase_never_starts_two_routines(self):
        r = self.r.save({"name": "Sleepy", "phrases": ["so raha hoon", "sleepy time"],
                         "steps": [{"tool": "mute", "input": {"muted": True}}]}, T.BY_NAME)
        self.assertEqual(r["phrases"], ["sleepy time"])
        self.assertEqual(self.r.find("so raha hoon")["name"], "Good night")
        with self.assertRaises(RoutineError):
            self.r.save({"name": "Study time", "steps": [{"tool": "mute", "input": {"muted": True}}]}, T.BY_NAME)

    def test_phrase_key(self):
        self.assertEqual(phrase_key("Hey, Good Night!"), "good night")
        self.assertEqual(phrase_key("study mode on karo"), "study mode")


class Running(Base):
    def setUp(self):
        super().setUp()
        old = T.top_youtube_video   # no network: YouTube's "top result" is made up
        T.top_youtube_video = lambda q: ("abc123xyz00", f"{q} mix")
        self.addCleanup(setattr, T, "top_youtube_video", old)

    async def test_phrase_runs_the_steps_without_ai(self):
        self.key = None   # no key at all: still works
        t = await self.run_goal("study mode")
        self.assertEqual(t.state, "done")
        self.assertEqual(t.source, "routine")
        self.assertEqual(self.llm.requests, [])
        self.assertTrue(self.pc.did("set_volume"))

    async def test_risky_step_still_asks_and_a_no_skips_only_that_step(self):
        import asyncio
        task = self.agent.start("phone", "good night")
        card = await self.next_approval()
        self.assertEqual(card["action"], "Put the laptop to sleep")
        self.agent.answer(card["id"], False)
        await self.agent._running[task.id]
        self.assertTrue(self.pc.did("set_brightness"))   # the steps after a failed one still ran
        self.assertFalse(self.pc.did("power"))
        self.assertIn("Put the laptop to sleep", task.reply.split("Not done:")[1])
        await asyncio.sleep(0)

    async def test_ai_can_make_a_routine_and_it_then_runs_by_itself(self):
        steps = [{"tool": "set_volume", "input": json.dumps({"percent": 80})},
                 {"tool": "play_youtube", "input": json.dumps({"query": "workout songs"})}]
        t = await self.run_goal("jab main gym time bolu to volume 80 aur workout songs",
                                call("save_routine", name="Gym time", phrases=["gym time", "workout karna hai"], steps=steps),
                                say("Done. Say gym time."))
        self.assertEqual(t.state, "done")
        self.assertEqual(self.agent.routines.find("workout karna hai")["name"], "Gym time")
        before = len(self.llm.requests)
        t = await self.run_goal("gym time")
        self.assertEqual(t.source, "routine")
        self.assertEqual(len(self.llm.requests), before)

    async def test_ai_cannot_put_typing_in_a_routine(self):
        await self.run_goal("make a routine that types my password",
                            call("save_routine", name="Bad", phrases=[],
                                 steps=[{"tool": "type_text", "input": json.dumps({"text": "x"})}]),
                            say("I couldn't."))
        self.assertIsNone(self.agent.routines.by_name("Bad"))

    async def test_phone_lists_saves_and_deletes(self):
        got = await self.agent.handle("phone", {"t": "agent_routines"})
        self.assertEqual(len(got["items"]), 3)
        await self.agent.handle("phone", {"t": "agent_routine_save", "routine": {
            "name": "Movie", "icon": "🎬", "phrases": ["movie time"],
            "steps": [{"tool": "set_brightness", "input": {"percent": 100}}]}})
        self.assertEqual(self.sent[-1]["t"], "agent_routines")
        movie = self.agent.routines.find("movie time")
        await self.agent.handle("phone", {"t": "agent_routine_del", "id": movie["id"]})
        self.assertIsNone(self.agent.routines.find("movie time"))
        bad = await self.agent.handle("phone", {"t": "agent_routine_save", "routine": {"name": "X", "steps": []}})
        self.assertEqual(bad["t"], "toast")


if __name__ == "__main__":
    unittest.main()
