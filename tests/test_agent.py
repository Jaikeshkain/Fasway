"""Agent tests. Nothing here touches the real laptop or spends money: the laptop is a recording stand-in
and Claude is a scripted model. Run from the project root:  python -m unittest tests.test_agent -v
"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx2 as httpx

from fasway.agent import apps, intents, policy
from fasway.agent import runtime as R
from fasway.agent import tools as T
from fasway.agent.llm import ClaudeClient, LLMError, LLMReply, cost_usd
from fasway.agent.policy import BLOCKED, CONFIRM, SAFE
from fasway.agent.runtime import Agent
from fasway.agent.store import AgentStore, Task


class FakeLaptop:
    """Records every call instead of touching the machine."""

    def __init__(self):
        self.calls = []
        self.windows = [{"id": 1, "title": "Untitled - Notepad", "app": "Notepad", "active": True},
                        {"id": 2, "title": "Inbox - Chrome", "app": "Chrome", "active": False}]
        self.items = [{"id": "a", "name": "Open docs", "type": "open", "value": "https://example.com"},
                      {"id": "b", "name": "Clean", "type": "command", "value": "del x"}]

    def __getattr__(self, name):
        def record(*a):
            self.calls.append((name, *a))
            return True
        return record

    def list_windows(self, have=None):
        return {"windows": self.windows, "icons": {}}

    def get_volume(self):
        return 50, False

    def get_brightness(self):
        return 40

    def get_status(self):
        return {"battery": 80, "plugged": True, "cpu": 5, "ram": 30}

    async def get_state(self, have):
        return {"sessions": [], "current": None, "art": {}}

    def did(self, name):
        return [c for c in self.calls if c[0] == name]


class ScriptedLLM:
    """Plays back replies and remembers each request (a copy, as it was at that moment)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    async def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw)))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


USAGE = {"input_tokens": 100, "output_tokens": 50}


def say(text):
    return LLMReply("end_turn", [{"type": "text", "text": text}], USAGE)


def call(tool, tid="t1", **inp):
    return LLMReply("tool_use", [{"type": "tool_use", "id": tid, "name": tool, "input": inp}], USAGE)


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pc = FakeLaptop()
        self.sent = []
        self.llm = ScriptedLLM()
        self.key = "sk-test"
        self.key_for = {"anthropic", "openai"}
        self.agent = self.make_agent()

    def make_agent(self):
        async def run_sys(fn, *a):
            return fn(*a)

        async def broadcast(m):
            self.sent.append(json.loads(json.dumps(m)))   # must be JSON-safe, like the real socket

        pc = self.pc
        env = T.Env(inp=pc, sysctl=pc, nowplaying=pc, actions=pc, run_sys=run_sys, status=pc)
        return Agent(Path(self._tmp.name), env, broadcast, llm_factory=lambda model, key: self.llm,
                     key_source=lambda provider: self.key if provider in self.key_for else None)

    async def run_goal(self, goal, *replies, device="phone"):
        self.llm.replies.extend(replies)
        t = self.agent.start(device, goal)
        await self.agent._running[t.id]
        return t

    async def next_approval(self):
        for _ in range(500):
            cards = [m for m in self.sent if m["t"] == "agent_approval" and m["id"] in self.agent._approvals]
            if cards:
                return cards[-1]
            await asyncio.sleep(0.005)
        self.fail("no approval requested")


class Intents(unittest.TestCase):
    def test_phrases(self):
        cases = {
            "volume 30": ("set_volume", {"percent": 30}),
            "Volume 30 percent.": ("set_volume", {"percent": 30}),
            "volume 30%": ("set_volume", {"percent": 30}),
            "awaaz 40 karo": ("set_volume", {"percent": 40}),
            "आवाज़ 50 करो": ("set_volume", {"percent": 50}),
            "volume 500": ("set_volume", {"percent": 100}),
            "volume up": ("change_volume", {"direction": "up"}),
            "awaaz badhao": ("change_volume", {"direction": "up"}),
            "आवाज़ कम करो": ("change_volume", {"direction": "down"}),
            "mute": ("mute", {"muted": True}),
            "unmute karo": ("mute", {"muted": False}),
            "brightness 70": ("set_brightness", {"percent": 70}),
            "agla gaana": ("media", {"action": "next"}),
            "अगला गाना": ("media", {"action": "next"}),
            "pichla gaana": ("media", {"action": "previous"}),
            "pause": ("media", {"action": "play_pause"}),
            "lock": ("power", {"action": "lock"}),
            "laptop lock karo": ("power", {"action": "lock"}),
            "shutdown": ("power", {"action": "shutdown"}),
            "laptop band karo": ("power", {"action": "shutdown"}),
            "show desktop": ("press_keys", {"keys": "win+d"}),
            "open youtube": ("open_url", {"url": "https://www.youtube.com"}),
            "youtube kholo": ("open_url", {"url": "https://www.youtube.com"}),
            "यूट्यूब खोलो": ("open_url", {"url": "https://www.youtube.com"}),
            "notepad kholo": ("open_app", {"name": "notepad"}),
            "open settings": ("open_app", {"name": "ms-settings:"}),
        }
        for text, (tool, inp) in cases.items():
            with self.subTest(text):
                got = intents.match(text)
                self.assertIsNotNone(got)
                self.assertEqual((got.tool, got.input), (tool, inp))

    def test_longer_requests_go_to_the_ai(self):
        for text in ("volume 30 karke youtube kholo", "band karo", "what is the volume", "open my tax file",
                     "youtube pe arijit ke gaane chalao", "don't shutdown", "volume", ""):
            with self.subTest(text):
                self.assertIsNone(intents.match(text))

    def test_every_builtin_passes_the_policy_without_being_blocked(self):
        for name, target in intents.APPS.items():
            self.assertEqual(policy.check_app(target)[0], SAFE, name)
        for name, url in intents.SITES.items():
            self.assertIsNone(policy.check_url(url), name)


class EverydaySentences(unittest.TestCase):
    def steps(self, text):
        got = intents.understand(text)
        return [(s.tool, s.input) for s in got] if got else None

    def test_understood(self):
        cases = {
            "can you turn the sound down a bit": [("change_volume", {"direction": "down"})],
            "please make it louder": [("change_volume", {"direction": "up"})],
            "it's too loud": [("change_volume", {"direction": "down"})],
            "thoda awaaz kam kar do yaar": [("change_volume", {"direction": "down"})],
            "set the volume to 40 please": [("set_volume", {"percent": 40})],
            "volume full kar do": [("set_volume", {"percent": 100})],
            "mute the sound": [("mute", {"muted": True})],
            "आवाज़ थोड़ी कम कर दो": [("change_volume", {"direction": "down"})],
            "make the screen brighter": [("change_brightness", {"direction": "up"})],
            "screen brightness thodi kam karo": [("change_brightness", {"direction": "down"})],
            "play the next song": [("media", {"action": "next"})],
            "gaana badlo": [("media", {"action": "next"})],
            "stop the music": [("media", {"action": "play_pause"})],
            "turn off the laptop": [("power", {"action": "shutdown"})],
            "turn off the screen": [("power", {"action": "display_off"})],
            "i want to lock my laptop": [("power", {"action": "lock"})],
            "can you open youtube for me": [("open_url", {"url": "https://www.youtube.com"})],
            "go to github": [("open_url", {"url": "https://github.com"})],
            "open amazon.in": [("open_url", {"url": "https://amazon.in"})],
            "open vlc": [("open_app", {"name": "vlc"})],
            "search tom and jerry on youtube": [("web_search", {"site": "youtube", "query": "tom and jerry"})],
            "play arijit singh on youtube": [("web_search", {"site": "youtube", "query": "arijit singh"})],
            "youtube pe arijit ke gaane chalao": [("web_search", {"site": "youtube", "query": "arijit ke gaane"})],
            "arijit ke gaane chalao": [("web_search", {"site": "youtube", "query": "arijit gaane"})],
            "open example.com": [("open_url", {"url": "https://example.com"})],
            "weather in delhi search karo": [("web_search", {"site": "google", "query": "weather in delhi"})],
            "how much battery is left": [("get_system_status", {})],
            "battery kitni hai": [("get_system_status", {})],
            "what's playing": [("get_now_playing", {})],
            "take a screenshot": [("press_keys", {"keys": "win+shift+s"})],
            "write Hello World in notepad": [("open_app", {"name": "notepad"}), ("type_text", {"text": "Hello World"})],
            "notepad me namaste likho": [("open_app", {"name": "notepad"}), ("type_text", {"text": "namaste"})],
            "volume 30 and open youtube": [("set_volume", {"percent": 30}), ("open_url", {"url": "https://www.youtube.com"})],
            "volume 30 karke youtube kholo": [("set_volume", {"percent": 30}), ("open_url", {"url": "https://www.youtube.com"})],
            "brightness kam karo aur gaana roko": [("change_brightness", {"direction": "down"}), ("media", {"action": "play_pause"})],
        }
        for text, want in cases.items():
            with self.subTest(text):
                self.assertEqual(self.steps(text), want)

    def test_how_people_actually_talk(self):
        yt = lambda q: [("web_search", {"site": "youtube", "query": q})]   # noqa: E731
        go = lambda u: [("open_url", {"url": u})]   # noqa: E731
        settings = [("open_app", {"name": "ms-settings:"})]
        down, up = [("change_volume", {"direction": "down"})], [("change_volume", {"direction": "up"})]
        nxt, pause = [("media", {"action": "next"})], [("media", {"action": "play_pause"})]
        cases = {
            # the sentences that failed on the phone
            "YouTube Arijit Singh ke gane chala de": yt("arijit singh ke gane"),
            "play songs on YouTube": yt("songs"),
            "setting App kholo": settings,
            # one request, any word order, any verb form
            "Arijit Singh ke gane YouTube pe chala de": yt("arijit singh ke gane"),
            "youtube pe arijit singh ke gaane laga do": yt("arijit singh ke gaane"),
            "youtube par kishore kumar baja do": yt("kishore kumar"),
            "you tube pe lo-fi music chalao": yt("lo-fi music"),
            "youtube per comedy videos dikhao": yt("comedy videos"),
            "yaar youtube pe koi comedy video laga de": yt("koi comedy video"),
            "kishore kumar ke gaane baja de": yt("kishore kumar gaane"),
            "sad songs chala do": yt("sad songs"),
            "arijit singh laga do": yt("arijit singh"),
            "play arijit singh": yt("arijit singh"),
            "can you play some old hindi songs on youtube": yt("some old hindi songs"),
            "youtube pe arijit": yt("arijit"),
            "youtube kholo": go("https://www.youtube.com"),
            "youtube khol de": go("https://www.youtube.com"),
            "youtube chala de": go("https://www.youtube.com"),
            "open you tube": go("https://www.youtube.com"),
            "whats app kholo": go("https://web.whatsapp.com"),
            "google pe weather dhundo": [("web_search", {"site": "google", "query": "weather"})],
            "google weather in delhi": [("web_search", {"site": "google", "query": "weather in delhi"})],
            "amazon pe shoes search kar do": [("web_search", {"site": "amazon", "query": "shoes"})],
            "delhi maps pe dikhao": [("web_search", {"site": "maps", "query": "delhi"})],
            "delhi ka mausam search kar de": [("web_search", {"site": "google", "query": "delhi ka mausam"})],
            # apps
            "settings kholo": settings,
            "setting khol de": settings,
            "settings app open karo": settings,
            "mera setting app khol do yaar": settings,
            "chrome chala de": [("open_app", {"name": "chrome"})],
            "google chrome kholo": [("open_app", {"name": "chrome"})],
            "calculator app kholo": [("open_app", {"name": "calc"})],
            "calculatr kholo": [("open_app", {"name": "calc"})],
            "task manager khol do": [("open_app", {"name": "taskmgr"})],
            "power bi kholo": [("open_app", {"name": "power bi"})],
            # volume and music, the way people say it
            "awaaz kam kar de": down,
            "aawaz thodi si kam karo bhai": down,
            "sound low kar do": down,
            "volume badha de": up,
            "awaaz tej karo": up,
            "आवाज़ बढ़ा दे": up,
            "gaana badal do": nxt,
            "agle gaane pe jao": nxt,
            "agla gaana chala de": nxt,
            "gaana rok do": pause,
            "gaana band kar de": pause,
            "song pause kar do": pause,
            "gaana chala de": pause,
            "play music": pause,
            "play the next song": nxt,
            "brightness badha de": [("change_brightness", {"direction": "up"})],
            "roshni kam kar de": [("change_brightness", {"direction": "down"})],
            "laptop band kar de": [("power", {"action": "shutdown"})],
            "laptop lock kar de": [("power", {"action": "lock"})],
            "screen band kar do": [("power", {"action": "display_off"})],
            # questions a voice assistant gets, answered on the laptop
            "time kya hai": [("get_time", {})],
            "kitne baje hain": [("get_time", {})],
            "what's the time": [("get_time", {})],
            "aaj ki date kya hai": [("get_time", {})],
            "what is the date today": [("get_time", {})],
            # from the laptop's real request history
            "battery percentage": [("get_system_status", {})],
            "open Cloud": go("https://claude.ai"),
            "open Raho Mel on edge": go("https://mail.zoho.com"),
            "open Zoho Mail on Edge": go("https://mail.zoho.com"),
            "open youtube on chrome": go("https://www.youtube.com"),
            "open irctc website": [("web_search", {"site": "google", "query": "irctc"})],
            "irctc on chrome kholo": [("web_search", {"site": "google", "query": "irctc"})],
            # a description of the problem, not a request for more
            "sound bahut tez hai": down,
            "ruk jao": pause,
            "ek gaana bajao": pause,
            "yeh gaana hatao": nxt,
            "tum hi ho play karo": yt("tum hi ho"),
            "arijit singh ka tum hi ho chalao": yt("arijit singh ka tum hi ho"),
            "shut it down": [("power", {"action": "shutdown"})],
            "new tab kholo": [("press_keys", {"keys": "ctrl+t"})],
            "paste kar do": [("press_keys", {"keys": "ctrl+v"})],
            "minimize everything": [("press_keys", {"keys": "win+d"})],
            "chrome band kar do": [("window_control", {"match": "chrome", "action": "close"})],
            "close chrome": [("window_control", {"match": "chrome", "action": "close"})],
            "aaj ka mausam kya hai": [("web_search", {"site": "google", "query": "aaj ka mausam kya hai"})],
            "what is the weather today": [("web_search", {"site": "google", "query": "what is the weather today"})],
            "best phones under 20000 google karo": [("web_search", {"site": "google", "query": "best phones under 20000"})],
            "flipkart kholo aur shoes search karo": [("web_search", {"site": "flipkart", "query": "shoes"})],
            # several at once
            "awaaz kam kar de aur youtube khol de": down + go("https://www.youtube.com"),
            "notepad kholo aur youtube pe arijit chalao": [("open_app", {"name": "notepad"})] + yt("arijit"),
            "gaana rok do phir laptop lock kar do": pause + [("power", {"action": "lock"})],
        }
        for text, want in cases.items():
            with self.subTest(text):
                self.assertEqual(self.steps(text), want)

    def test_it_gives_up_rather_than_guess(self):
        for text in ("don't shut down the laptop", "laptop band mat karo", "do not open youtube", "आवाज़ कम मत करो",
                     "how do I shut down my laptop", "laptop kaise band karte hain",
                     "write a poem in notepad", "write an email to my boss", "ek kahani likho",
                     "what is the capital of france", "send a message to rahul", "book a cab", "open my tax file",
                     "volume 30 youtube", "plan my day", "delete all my files",
                     "wapas jao", "wifi band kar do", "rahul ko message bhej do", "remind me at 5 pm",
                     "delete this file", "i don't want music", "kal ka meeting schedule karo",
                     "3 percentage", "aur kam karo",   # with nothing changed just before: about what?
                     "volume 30 and book a cab"):   # half-understood: nothing runs
            with self.subTest(text):
                self.assertIsNone(self.steps(text))

    def test_every_step_still_goes_through_the_safety_rules(self):
        for text in ("open cmd", "open powershell", "open regedit"):
            s = intents.understand(text)[0]
            self.assertEqual(policy.check_app(s.input["name"])[0], BLOCKED, text)
        # a file name is only ever treated as a web address, never run
        self.assertEqual(self.steps("run.bat kholo"), [("open_url", {"url": "https://run.bat"})])


class Policy(unittest.TestCase):
    NOTEPAD = {"app": "Notepad", "title": "Untitled"}

    def test_apps(self):
        for bad in ("cmd", "CMD.EXE", "powershell", "pwsh.exe", "regedit", "wscript", "python", "mshta",
                    r"C:\Windows\System32\cmd.exe", "evil.bat", "run.ps1", "..\\x", "a/b", "https://x.test/a.exe",
                    "shell:startup", "file:///c:/x"):
            self.assertEqual(policy.check_app(bad)[0], BLOCKED, bad)
        for ok in ("notepad", "notepad.exe", "calc", "chrome", "Microsoft Edge", "ms-settings:"):
            self.assertEqual(policy.check_app(ok)[0], SAFE, ok)

    def test_urls(self):
        for bad in ("file:///c:/windows/system32/cmd.exe", "javascript:alert(1)", "ms-settings:", "cmd", "\\\\host\\share", "https://"):
            self.assertIsNotNone(policy.check_url(bad), bad)
        self.assertIsNone(policy.check_url("https://example.com/a?b=1"))

    def test_typing_depends_on_the_window(self):
        self.assertEqual(policy.judge_typing(self.NOTEPAD)[0], SAFE)
        for w in ({"app": "cmd", "title": "x"}, {"app": "powershell", "title": "x"}, {"app": "WindowsTerminal", "title": "Windows Terminal"},
                  {"app": "explorer", "title": "Run"}, {"app": "Chrome", "title": "Sign in - Google"},
                  {"app": "Chrome", "title": "HDFC NetBanking"}, {"app": "Chrome", "title": "Checkout - Amazon"}):
            self.assertEqual(policy.judge_typing(w)[0], CONFIRM, w)

    def test_shortcuts(self):
        for k in ("win+r", "alt+f4", "ctrl+shift+esc", "win", "win+x", "ctrl+w"):
            self.assertEqual(policy.judge_keys(k, self.NOTEPAD)[0], CONFIRM, k)
        for k in ("ctrl+s", "CTRL + A", "enter", "win+d"):
            self.assertEqual(policy.judge_keys(k, self.NOTEPAD)[0], SAFE, k)
        shell = {"app": "cmd", "title": "Command Prompt"}
        self.assertEqual(policy.judge_keys("enter", shell)[0], CONFIRM)
        self.assertEqual(policy.judge_keys("ctrl+v", shell)[0], CONFIRM)

    def test_no_shell_tool_exists(self):
        names = set(T.BY_NAME)
        self.assertFalse(names & {"run_command", "shell", "delete_file", "get_clipboard"})

    def test_tool_schemas_are_strict(self):
        for s in T.schemas():
            self.assertTrue(s["strict"])
            self.assertFalse(s["input_schema"]["additionalProperties"])
            self.assertEqual(sorted(s["input_schema"]["properties"]), s["input_schema"]["required"])

    def test_budget(self):
        b = policy.Budget(0.1, 1.0, 0.0)
        self.assertIsNone(b.exceeded())
        b.add(0.1)
        self.assertEqual(b.exceeded(), "task")
        self.assertEqual(policy.Budget(0.1, 1.0, 1.0).exceeded(), "day")


class Builtins(Base):
    async def test_runs_without_key_or_ai(self):
        self.key = None
        t = await self.run_goal("volume 30")
        self.assertEqual((t.state, t.source), ("done", "builtin"))
        self.assertEqual(self.pc.did("set_volume"), [("set_volume", 30, None)])
        self.assertEqual(self.llm.requests, [])

    async def test_shutdown_asks_first(self):
        job = asyncio.create_task(self.run_goal("shutdown"))
        card = await self.next_approval()
        self.assertEqual(self.pc.did("power"), [])
        self.agent.answer(card["id"], True)
        t = await job
        self.assertEqual(t.state, "done")
        self.assertEqual(self.pc.did("power"), [("power", "shutdown")])

    async def test_shutdown_declined(self):
        job = asyncio.create_task(self.run_goal("restart"))
        card = await self.next_approval()
        self.agent.answer(card["id"], False)
        t = await job
        self.assertEqual(t.state, "failed")
        self.assertEqual(self.pc.did("power"), [])

    async def test_no_key_explains_itself(self):
        self.key = None
        t = await self.run_goal("write a poem in notepad")
        self.assertEqual(t.state, "failed")
        self.assertIn("API key", t.reply)


class InstalledApps(unittest.TestCase):
    APPS = {"microsoft word": "Word.App", "wordpad": "Pad.App", "whatsapp": "5319.WhatsApp!App", "power bi desktop": "Bi.App",
            "command prompt": "cmd.lnk", "windows powershell": "ps.lnk", "anaconda prompt": "ap.lnk", "git bash": "gb.lnk",
            "python 3.12": "py.lnk", "windows terminal": "wt.App", "registry editor": "re.lnk"}

    def find(self, name):
        return apps.find(name, self.APPS)

    def test_finds_by_what_people_say(self):
        self.assertEqual(self.find("whatsapp"), "shell:AppsFolder\\5319.WhatsApp!App")
        self.assertEqual(self.find("word"), "shell:AppsFolder\\Word.App")      # not WordPad
        self.assertEqual(self.find("power bi"), "shell:AppsFolder\\Bi.App")
        self.assertEqual(self.find("whatsap"), "shell:AppsFolder\\5319.WhatsApp!App")

    def test_never_finds_anything_that_runs_commands(self):
        for name in ("command prompt", "command", "prompt", "powershell", "windows powershell", "anaconda", "git bash", "python",
                     "terminal", "registry", "registry editor"):
            self.assertIsNone(self.find(name), name)

    def test_unknown(self):
        self.assertIsNone(self.find("nothing like this"))


class OpeningApps(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_installed_apps_and_explains_failure(self):
        opened = []

        def open_target(t):
            if not t.startswith("shell:"):
                raise FileNotFoundError(t)
            opened.append(t)

        async def run_sys(fn, *a):
            return fn(*a)

        class Sys:
            pass
        s = Sys()
        s.open_target = open_target
        env = T.Env(inp=None, sysctl=s, nowplaying=None, actions=None, run_sys=run_sys)
        old, apps.installed = apps.installed, lambda: {"whatsapp": "W!App", "command prompt": "cmd.lnk"}
        self.addCleanup(setattr, apps, "installed", old)
        await T.BY_NAME["open_app"].run(env, {"name": "whatsapp"})
        self.assertEqual(opened, ["shell:AppsFolder\\W!App"])
        with self.assertRaises(T.ToolFailed) as e:
            await T.BY_NAME["open_app"].run(env, {"name": "setting thing"})
        self.assertIn("couldn't find an app", str(e.exception))
        with self.assertRaises(T.ToolFailed):
            await T.BY_NAME["open_app"].run(env, {"name": "command prompt"})
        self.assertEqual(len(opened), 1)


class WithoutAi(Base):
    async def test_everyday_sentence_runs_all_steps(self):
        self.key = None
        t = await self.run_goal("volume 30 and open youtube")
        self.assertEqual((t.state, t.source), ("done", "builtin"))
        self.assertEqual(self.pc.did("set_volume"), [("set_volume", 30, None)])
        self.assertEqual(self.pc.did("open_target"), [("open_target", "https://www.youtube.com")])

    async def test_follow_ups_continue_what_was_just_changed(self):
        self.key = None
        await self.run_goal("brightness badha de bhai")
        t = await self.run_goal("3 percentage")
        self.assertEqual((t.state, self.pc.did("set_brightness")), ("done", [("set_brightness", 3)]))
        await self.run_goal("aur kam karo")
        self.assertEqual(len(self.pc.did("step_brightness")), 2)   # up, then down
        await self.run_goal("volume 40")
        await self.run_goal("aur badhao")
        self.assertEqual(self.pc.did("set_volume")[-1], ("set_volume", 60, None))   # the fake laptop reads 50; +10
        self.agent._recent["phone"] = ("volume", 0)                  # long ago
        t = await self.run_goal("30 percent")
        self.assertEqual(t.state, "failed")                          # too old to guess what it's about

    async def test_a_question_gets_the_real_answer(self):
        self.key = None
        t = await self.run_goal("battery kitni hai")
        self.assertIn("battery 80%", t.reply)
        t = await self.run_goal("time kya hai")
        self.assertRegex(t.reply, r"^It's \d{1,2}:\d\d [AP]M on \w+day, \d{1,2} \w+ \d{4}$")

    def test_the_ai_is_told_it_may_simply_answer_and_is_heard_aloud(self):
        from fasway.agent import prompts
        self.assertIn("read aloud", prompts.SYSTEM)
        self.assertIn("own knowledge", prompts.SYSTEM)

    async def test_shutdown_in_a_sentence_still_asks(self):
        self.key = None
        job = asyncio.create_task(self.run_goal("please turn off the laptop"))
        card = await self.next_approval()
        self.assertEqual(self.pc.did("power"), [])
        self.agent.answer(card["id"], False)
        t = await job
        self.assertEqual(t.state, "failed")
        self.assertEqual(self.pc.did("power"), [])

    async def test_stops_at_the_first_failed_step(self):
        self.key = None
        t = await self.run_goal("open cmd and volume 30")
        self.assertEqual(t.state, "failed")
        self.assertEqual(self.pc.did("set_volume"), [])
        self.assertEqual(self.pc.did("open_target"), [])

    async def test_with_a_key_the_ai_reads_everyday_sentences(self):
        t = await self.run_goal("can you turn the sound down a bit", say("Turned it down"))
        self.assertEqual(t.source, "ai")
        self.assertEqual(len(self.llm.requests), 1)
        self.assertEqual(self.pc.did("set_volume"), [])

    async def test_exact_commands_never_cost_anything(self):
        t = await self.run_goal("volume 30")
        self.assertEqual((t.source, self.llm.requests), ("builtin", []))


class Loop(Base):
    async def test_multi_step_task(self):
        t = await self.run_goal("write hello in notepad",
                                call("switch_window", match="notepad"), call("type_text", tid="t2", text="hello"), say("Done"))
        self.assertEqual((t.state, t.reply), ("done", "Done"))
        self.assertEqual(self.pc.did("type_text"), [("type_text", "hello")])
        self.assertEqual([s["status"] for s in t.steps], ["done", "done"])
        last = self.llm.requests[-1]["messages"]
        self.assertEqual([m["role"] for m in last], ["user", "assistant", "user", "assistant", "user"])
        self.assertEqual(last[-1]["content"][0]["tool_use_id"], "t2")

    async def test_history_is_append_only_and_prefix_is_stable(self):
        await self.run_goal("x", call("get_windows"), call("get_system_status", tid="t2"), say("ok"))
        a, b, c = self.llm.requests
        self.assertEqual(b["messages"][:len(a["messages"])], a["messages"])
        self.assertEqual(c["messages"][:len(b["messages"])], b["messages"])
        self.assertEqual(a["system"], c["system"])
        self.assertEqual(a["tools"], c["tools"])

    async def test_thinking_blocks_go_back_unchanged(self):
        thinking = {"type": "thinking", "thinking": "hmm", "signature": "sig"}
        first = LLMReply("tool_use", [thinking, {"type": "tool_use", "id": "t1", "name": "get_windows", "input": {}}], USAGE)
        await self.run_goal("x", first, say("ok"))
        self.assertEqual(self.llm.requests[1]["messages"][1]["content"][0], thinking)

    async def test_parallel_calls_answered_in_one_message(self):
        two = LLMReply("tool_use", [{"type": "tool_use", "id": "a", "name": "get_windows", "input": {}},
                                    {"type": "tool_use", "id": "b", "name": "nope", "input": {}}], USAGE)
        await self.run_goal("x", two, say("ok"))
        results = self.llm.requests[1]["messages"][-1]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b"])
        self.assertTrue(results[1]["is_error"])

    async def test_ai_cannot_open_a_shell_even_if_it_asks(self):
        t = await self.run_goal("x", call("open_app", name="cmd"), call("open_url", tid="t2", url="file:///c:/x.exe"), say("no"))
        self.assertEqual(self.pc.did("open_target"), [])
        self.assertEqual(t.steps[0]["status"], "declined")
        self.assertTrue(self.llm.requests[1]["messages"][-1]["content"][0]["is_error"])
        self.assertFalse([m for m in self.sent if m["t"] == "agent_approval"])   # refused outright, no approval offered

    async def test_run_dialog_shortcut_needs_approval(self):
        job = asyncio.create_task(self.run_goal("x", call("press_keys", keys="win+r"), say("ok")))
        card = await self.next_approval()
        self.assertEqual(self.pc.did("hotkey"), [])
        self.agent.answer(card["id"], False)
        await job
        self.assertEqual(self.pc.did("hotkey"), [])
        self.assertIn("declined", self.llm.requests[1]["messages"][-1]["content"][0]["content"])

    async def test_typing_into_terminal_needs_approval(self):
        self.pc.windows = [{"id": 9, "title": "Command Prompt", "app": "cmd", "active": True}]
        job = asyncio.create_task(self.run_goal("x", call("type_text", text="del *"), say("ok")))
        card = await self.next_approval()
        self.assertEqual(self.pc.did("type_text"), [])
        self.agent.answer(card["id"], False)
        await job
        self.assertEqual(self.pc.did("type_text"), [])

    async def test_window_change_during_approval_cancels_typing(self):
        self.pc.windows = [{"id": 9, "title": "Command Prompt", "app": "cmd", "active": True}]
        job = asyncio.create_task(self.run_goal("x", call("type_text", text="hi"), say("ok")))
        card = await self.next_approval()
        self.pc.windows = [{"id": 10, "title": "Bank", "app": "Chrome", "active": True}]
        self.agent.answer(card["id"], True)
        await job
        self.assertEqual(self.pc.did("type_text"), [])

    async def test_remember_covers_only_the_same_action(self):
        job = asyncio.create_task(self.run_goal(
            "x", call("press_keys", keys="ctrl+w"), call("press_keys", tid="t2", keys="ctrl+w"),
            call("press_keys", tid="t3", keys="win+r"), say("ok")))
        card = await self.next_approval()
        self.agent.answer(card["id"], True, remember=True)
        card2 = None
        for _ in range(500):
            cards = [m for m in self.sent if m["t"] == "agent_approval" and m["id"] != card["id"]]
            if cards:
                card2 = cards[0]
                break
            await asyncio.sleep(0.005)
        self.assertIsNotNone(card2)
        self.assertIn("win+r", card2["action"])
        self.assertEqual(len(self.pc.did("hotkey")), 2)
        self.agent.answer(card2["id"], False)
        await job
        self.assertEqual(len(self.pc.did("hotkey")), 2)

    async def test_approval_times_out_as_no(self):
        old, R.APPROVAL_SECONDS = R.APPROVAL_SECONDS, 0.05
        self.addCleanup(setattr, R, "APPROVAL_SECONDS", old)
        await self.run_goal("x", call("power", action="shutdown"), say("ok"))
        self.assertEqual(self.pc.did("power"), [])
        self.assertTrue([m for m in self.sent if m["t"] == "agent_approval_done"])

    async def test_first_answer_wins(self):
        job = asyncio.create_task(self.run_goal("shutdown"))
        card = await self.next_approval()
        self.agent.answer(card["id"], False)
        self.agent.answer(card["id"], True)
        await job
        self.assertEqual(self.pc.did("power"), [])

    async def test_stop_while_waiting_for_approval(self):
        job = asyncio.create_task(self.run_goal("x", call("power", action="shutdown"), say("ok")))
        card = await self.next_approval()
        self.agent.stop(card["task"])
        t = await job
        self.assertEqual(t.state, "stopped")
        self.assertEqual(self.pc.did("power"), [])
        self.assertEqual(self.agent._approvals, {})
        self.assertEqual(t.steps[0]["status"], "failed")

    async def test_refusal_and_max_tokens_run_nothing(self):
        cut = LLMReply("max_tokens", [{"type": "tool_use", "id": "t", "name": "power", "input": {"action": "lock"}}], USAGE)
        t = await self.run_goal("x", cut)
        self.assertEqual(t.state, "failed")
        self.assertEqual(self.pc.did("power"), [])
        t = await self.run_goal("y", LLMReply("refusal", [], USAGE, refusal="no"))
        self.assertEqual(t.state, "failed")

    async def test_pause_turn_continues(self):
        t = await self.run_goal("x", LLMReply("pause_turn", [{"type": "text", "text": "..."}], USAGE), say("ok"))
        self.assertEqual((t.state, len(self.llm.requests)), ("done", 2))

    async def test_step_limit(self):
        old, R.MAX_ROUNDS = R.MAX_ROUNDS, 3
        self.addCleanup(setattr, R, "MAX_ROUNDS", old)
        t = await self.run_goal("x", *[call("get_windows", tid=f"t{i}") for i in range(5)])
        self.assertEqual(t.state, "failed")
        self.assertEqual(len(self.llm.requests), 3)

    async def test_api_errors_reach_the_phone_in_plain_words(self):
        t = await self.run_goal("x", LLMError("network", "Can't reach the AI service (no internet?)"))
        self.assertEqual(t.state, "failed")
        self.assertIn("internet", t.reply)

    async def test_task_budget_stops_before_the_next_request(self):
        self.agent.store.set(task_budget_inr=1)
        pricey = {"input_tokens": 0, "output_tokens": 1_000_000}   # $20 on Opus
        t = await self.run_goal("x", LLMReply("tool_use", [{"type": "tool_use", "id": "t", "name": "get_windows", "input": {}}], pricey),
                                say("never"))
        self.assertEqual(t.state, "over_budget")
        self.assertEqual(len(self.llm.requests), 1)

    async def test_daily_budget_blocks_before_any_request(self):
        self.agent.store.add_usage(usd=1000)
        t = await self.run_goal("x", say("never"))
        self.assertEqual(t.state, "over_budget")
        self.assertEqual(self.llm.requests, [])

    async def test_spending_is_recorded(self):
        t = await self.run_goal("x", say("ok"))
        self.assertAlmostEqual(t.usd, cost_usd("claude-opus-5-5", USAGE))
        self.assertAlmostEqual(self.agent.store.spent_today_usd(), t.usd)
        self.assertGreater(self.sent[-1]["spent_today_inr"], 0)

    async def test_follow_up_continues_the_chat_then_model_switch_starts_fresh(self):
        await self.run_goal("volume kitna hai", say("50"))
        await self.run_goal("aur kam karo", say("ok"))
        self.assertEqual(len(self.llm.requests[1]["messages"]), 3)
        self.agent.store.set(model="claude-haiku-5-5")
        await self.run_goal("hello", say("hi"))
        self.assertEqual(len(self.llm.requests[2]["messages"]), 1)
        self.assertEqual(self.llm.requests[2]["model"], "claude-haiku-5-5")

    async def test_stale_chat_starts_fresh(self):
        await self.run_goal("a", say("1"))
        self.agent._chats["phone"]["at"] -= R.MEMORY_SECONDS + 1
        await self.run_goal("b", say("2"))
        self.assertEqual(len(self.llm.requests[1]["messages"]), 1)

    async def test_two_phones_have_separate_chats(self):
        await self.run_goal("a", say("1"), device="p1")
        await self.run_goal("b", say("2"), device="p2")
        self.assertEqual(len(self.llm.requests[1]["messages"]), 1)

    async def test_tasks_run_one_at_a_time(self):
        self.llm.replies.extend([say("1"), say("2")])
        a = self.agent.start("p", "first thing")
        b = self.agent.start("p", "second thing")
        await asyncio.gather(self.agent._running[a.id], self.agent._running[b.id])
        self.assertEqual((a.reply, b.reply), ("1", "2"))
        self.assertIn("first thing", self.llm.requests[0]["messages"][0]["content"])

    async def test_laptop_context_is_labelled_and_in_the_user_message(self):
        await self.run_goal("x", say("ok"))
        req = self.llm.requests[0]
        self.assertIn("Untitled - Notepad", req["messages"][0]["content"])
        self.assertNotIn("Untitled - Notepad", req["system"])


class Protocol(Base):
    async def test_messages(self):
        reply = await self.agent.handle("p", {"t": "agent_settings"})
        self.assertEqual(reply["model"], "claude-opus-5-5")
        self.assertEqual([m["id"] for m in reply["models"]], ["claude-opus-5-5", "claude-haiku-5-5", "gpt-6-luna", "gpt-6-sol"])
        self.assertTrue(reply["has_key"])
        self.assertNotIn("sk-test", json.dumps(reply))
        await self.agent.handle("p", {"t": "agent_set", "model": "claude-haiku-5-5", "task_budget_inr": "bad"})
        self.assertEqual(self.agent.store.settings["model"], "claude-haiku-5-5")
        self.assertEqual(self.agent.store.settings["task_budget_inr"], 30)
        await self.agent.handle("p", {"t": "agent_set", "model": "gpt-9"})
        self.assertEqual(self.agent.store.settings["model"], "claude-haiku-5-5")

    async def test_start_and_list(self):
        await self.agent.handle("p", {"t": "agent_start", "text": "volume 20"})
        await asyncio.gather(*self.agent._running.values())
        reply = await self.agent.handle("p", {"t": "agent_list"})
        self.assertEqual(reply["t"], "agent_list")
        self.assertEqual(reply["model"], "claude-opus-5-5")
        self.assertEqual(reply["tasks"][-1]["goal"], "volume 20")
        await self.agent.handle("p", {"t": "agent_start", "text": "   "})
        self.assertEqual(len(self.agent.store.tasks), 1)

    async def test_settings_and_history_survive_restart_but_tasks_do_not_resume(self):
        self.agent.store.set(model="claude-haiku-5-5")
        await self.run_goal("volume 20")
        running = Task.new("half done")
        self.agent.store.add(running)
        store = AgentStore(Path(self._tmp.name))
        self.assertEqual(store.settings["model"], "claude-haiku-5-5")
        self.assertEqual(store.get(running.id).state, "stopped")
        self.assertEqual(store.commands_today(), 1)

    async def test_corrupt_files_dont_stop_startup(self):
        d = Path(self._tmp.name) / "agent"
        for f in ("settings.json", "tasks.json", "usage.json"):
            (d / f).write_text("{not json", encoding="utf-8")
        self.assertEqual(AgentStore(Path(self._tmp.name)).tasks, [])


class RealSdkShape(unittest.IsolatedAsyncioTestCase):
    """Runs the real Anthropic SDK against a fake network, so call shapes are checked for free."""

    def client(self, handler):
        c = ClaudeClient("sk-test")
        from anthropic import AsyncAnthropic
        c._c = AsyncAnthropic(api_key="sk-test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return c

    async def send(self, model, handler):
        return await self.client(handler).create(model=model, system="s", tools=T.schemas()[:1],
                                                 messages=[{"role": "user", "content": "hi"}], effort="low")

    @staticmethod
    def ok(body_out):
        def handler(req):
            body_out["url"] = str(req.url)
            body_out["beta"] = req.headers.get("anthropic-beta")
            body_out["body"] = json.loads(req.content)
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "x", "stop_reason": "tool_use",
                "content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "id": "t", "name": "get_windows", "input": {}}],
                "usage": {"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 6}})
        return handler

    async def test_opus_uses_fallback_and_cache(self):
        seen = {}
        r = await self.send("claude-opus-5-5", self.ok(seen))
        self.assertIn("server-side-fallback-2026-07-01", seen["beta"])
        b = seen["body"]
        self.assertEqual(b["fallbacks"], "default")
        self.assertEqual(b["cache_control"], {"type": "ephemeral"})
        self.assertEqual(b["output_config"], {"effort": "low"})
        for banned in ("temperature", "thinking", "tool_choice"):
            self.assertNotIn(banned, b)
        self.assertEqual(r.stop_reason, "tool_use")
        self.assertEqual(r.content[1]["name"], "get_windows")
        self.assertEqual(r.usage["cache_read_input_tokens"], 5)
        json.dumps(r.content)

    async def test_haiku_has_no_fallback(self):
        seen = {}
        await self.send("claude-haiku-5-5", self.ok(seen))
        self.assertNotIn("fallbacks", seen["body"])
        self.assertFalse(seen["beta"])

    async def test_errors_become_plain_kinds(self):
        for status, kind in ((401, "auth"), (403, "auth"), (429, "rate"), (400, "bad_request"), (500, "server")):
            def handler(req, s=status):
                return httpx.Response(s, json={"type": "error", "error": {"type": "x", "message": "m"}})
            with self.assertRaises(LLMError) as e:
                await self.send("claude-haiku-5-5", handler)
            self.assertEqual(e.exception.kind, kind)

        def offline(req):
            raise httpx.ConnectError("no network")
        with self.assertRaises(LLMError) as e:
            await self.send("claude-haiku-5-5", offline)
        self.assertEqual(e.exception.kind, "network")


class ChoosingProviders(Base):
    async def test_each_model_uses_its_own_companys_key(self):
        self.key_for = {"anthropic"}
        self.agent.store.set(model="gpt-6-luna")
        msg = self.agent.settings_msg()
        self.assertFalse(msg["has_key"])
        self.assertEqual({m["id"]: m["has_key"] for m in msg["models"]},
                         {"claude-opus-5-5": True, "claude-haiku-5-5": True, "gpt-6-luna": False, "gpt-6-sol": False})
        t = await self.run_goal("plan my day")     # would need the AI, and there's no OpenAI key
        self.assertIn("OpenAI API key", t.reply)
        self.assertEqual(self.llm.requests, [])
        self.key_for = {"openai"}
        t = await self.run_goal("plan my day", say("Okay"))
        self.assertEqual((t.state, self.llm.requests[0]["model"]), ("done", "gpt-6-luna"))

    async def test_real_client_is_chosen_by_model(self):
        from fasway.agent.llm import OpenAIClient, make_client
        self.assertIsInstance(make_client("gpt-6-sol", "sk-x"), OpenAIClient)
        self.assertIsInstance(make_client("claude-haiku-5-5", "sk-x"), ClaudeClient)

    def test_keys_are_told_apart(self):
        from fasway.agent import keystore
        self.assertEqual(keystore.provider_of("sk-ant-api03-abc"), "anthropic")
        self.assertEqual(keystore.provider_of("sk-proj-abc"), "openai")


class OpenAiShape(unittest.IsolatedAsyncioTestCase):
    """The real OpenAI SDK against a fake network, so the request and reply shapes are checked for free."""

    REASONING = {"id": "rs_1", "type": "reasoning", "summary": [], "encrypted_content": "secret-blob"}
    CALL = {"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "set_volume",
            "arguments": "{\"percent\": 30}", "status": "completed"}

    def reply(self, output, status="completed", incomplete=None):
        return {"id": "r", "object": "response", "created_at": 1, "model": "gpt-6-luna", "status": status, "output": output,
                "incomplete_details": incomplete, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "error": None,
                "usage": {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050,
                          "input_tokens_details": {"cached_tokens": 600, "cache_write_tokens": 100},
                          "output_tokens_details": {"reasoning_tokens": 10}}}

    def client(self, handler):
        from openai import AsyncOpenAI
        from fasway.agent.llm import OpenAIClient
        c = OpenAIClient("sk-test")
        c._c = AsyncOpenAI(api_key="sk-test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return c

    async def send(self, handler, messages=None):
        return await self.client(handler).create(
            model="gpt-6-luna", system="be helpful", tools=T.schemas()[:2], effort="low",
            messages=messages or [{"role": "user", "content": "hi"}])

    async def test_request_shape(self):
        seen = {}

        def handler(req):
            seen["url"], seen["body"] = str(req.url), json.loads(req.content)
            return httpx.Response(200, json=self.reply([self.REASONING, self.CALL]))
        r = await self.send(handler)
        b = seen["body"]
        self.assertTrue(seen["url"].endswith("/responses"))
        self.assertEqual((b["model"], b["instructions"], b["store"]), ("gpt-6-luna", "be helpful", False))
        self.assertEqual(b["reasoning"], {"effort": "low"})
        self.assertEqual(b["prompt_cache_options"], {"mode": "implicit"})
        self.assertEqual(b["input"], [{"role": "user", "content": "hi"}])
        tool = b["tools"][0]
        self.assertEqual((tool["type"], tool["strict"], tool["parameters"]["additionalProperties"]), ("function", True, False))
        self.assertNotIn("input_schema", tool)
        self.assertEqual(r.stop_reason, "tool_use")
        use = next(x for x in r.content if x["type"] == "tool_use")
        self.assertEqual((use["id"], use["name"], use["input"]), ("call_1", "set_volume", {"percent": 30}))
        json.dumps(r.content)

    async def test_reasoning_and_results_go_back_as_the_api_requires(self):
        seen = []

        def handler(req):
            seen.append(json.loads(req.content))
            return httpx.Response(200, json=self.reply(
                [self.REASONING, self.CALL] if len(seen) == 1 else
                [{"id": "m", "type": "message", "role": "assistant", "status": "completed",
                  "content": [{"type": "output_text", "text": "Done", "annotations": []}]}]))
        msgs = [{"role": "user", "content": "volume 30"}]
        r = await self.send(handler, msgs)
        msgs.append({"role": "assistant", "content": r.content})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "Volume set"},
            {"type": "tool_result", "tool_use_id": "call_2", "content": "No", "is_error": True}]})
        r2 = await self.send(handler, msgs)
        items = seen[1]["input"]
        self.assertEqual(items[1]["encrypted_content"], "secret-blob")
        self.assertEqual(items[2]["call_id"], "call_1")
        self.assertEqual(items[3], {"type": "function_call_output", "call_id": "call_1", "output": "Volume set"})
        self.assertEqual(items[4]["output"], "ERROR: No")
        self.assertEqual((r2.stop_reason, r2.content[0]["text"]), ("end_turn", "Done"))

    async def test_cost_counts_each_kind_of_token_once(self):
        r = await self.send(lambda req: httpx.Response(200, json=self.reply([self.CALL])))
        self.assertEqual(r.usage, {"input_tokens": 300, "output_tokens": 50, "cache_read_input_tokens": 600,
                                   "cache_creation_input_tokens": 100})
        want = (300 * 0.10 + 50 * 0.50 + 600 * 0.01 + 100 * 0.125) / 1_000_000
        self.assertAlmostEqual(cost_usd("gpt-6-luna", r.usage), want)

    async def test_stopping_reasons(self):
        cut = self.reply([self.CALL], "incomplete", {"reason": "max_output_tokens"})
        r = await self.send(lambda req: httpx.Response(200, json=cut))
        self.assertEqual(r.stop_reason, "max_tokens")      # the runtime won't run a possibly cut-off call
        no = self.reply([{"id": "m", "type": "message", "role": "assistant", "status": "completed",
                          "content": [{"type": "refusal", "refusal": "can't"}]}])
        r = await self.send(lambda req: httpx.Response(200, json=no))
        self.assertEqual((r.stop_reason, r.refusal), ("refusal", "can't"))
        with self.assertRaises(LLMError):
            await self.send(lambda req: httpx.Response(200, json=self.reply([], "failed")))

    async def test_errors_become_plain_kinds(self):
        for status, kind in ((401, "auth"), (403, "auth"), (429, "rate"), (400, "bad_request"), (500, "server")):
            def handler(req, s=status):
                return httpx.Response(s, json={"error": {"type": "x", "message": "m"}})
            with self.assertRaises(LLMError) as e:
                await self.send(handler)
            self.assertEqual(e.exception.kind, kind)

        def offline(req):
            raise httpx.ConnectError("no network")
        with self.assertRaises(LLMError) as e:
            await self.send(offline)
        self.assertEqual(e.exception.kind, "network")


class Costs(unittest.TestCase):
    def test_costs(self):
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", {"input_tokens": 1_000_000}), 4.0)
        self.assertAlmostEqual(cost_usd("claude-haiku-5-5", {"output_tokens": 1_000_000}), 0.5)
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", {"cache_read_input_tokens": 1_000_000}), 0.2)


if __name__ == "__main__":
    unittest.main()
