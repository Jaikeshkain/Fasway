"""HTTPS + WebSocket server: serves the phone web app and executes its input commands."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aiohttp import web, WSMsgType
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from . import audio, status
from .actions import QuickActions, run_action
from .platform_input import inp, screen_permission_problem, sysctl
from .screen import ScreenGrabber, ScreenTrack

SYSTEM_MSGS = {"media", "vol", "bright", "power", "clip_set", "clip_get", "sys_get",
               "wins", "win", "open_url", "actions", "action_run", "action_save", "action_del", "action_move"}
POWER_ACTIONS = {"lock", "display_off", "sleep", "restart", "shutdown", "signout"}
CLIP_MAX = 20000  # chars pushed to the phone

log = logging.getLogger("fasway")
# Packaged apps (PyInstaller) unpack bundled files under sys._MEIPASS
WEB_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "web"


class FaswayServer:
    def __init__(self, token: str, port: int, cert: Path, key: Path, on_clients=None, data_dir: Path | None = None):
        self.token = token
        if data_dir is None:  # tests construct the server without a data folder
            import tempfile
            data_dir = Path(cert).parent if cert else Path(tempfile.gettempdir()) / "fasway-test"
        self.actions = QuickActions(data_dir)
        self._alerts = status.BatteryAlerts()
        self._status_task: asyncio.Task | None = None
        self.port = port
        self.cert, self.key = cert, key
        self.on_clients = on_clients or (lambda n: None)
        self.clients: set[web.WebSocketResponse] = set()
        self.grabber = ScreenGrabber()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        # clipboard/volume/brightness/power calls can block (COM, WMI, AppleScript): own thread
        self._sys_pool = ThreadPoolExecutor(1, thread_name_prefix="system", initializer=sysctl.thread_init)
        self._clip_task: asyncio.Task | None = None
        self._clip_from_phone: str | None = None  # don't echo the phone's own clipboard back to it

    # ---------- http ----------
    async def index(self, request):
        return self._file("index.html")

    async def static(self, request):
        name = request.match_info["name"]
        if "/" in name or "\\" in name or name.startswith("."):
            raise web.HTTPNotFound()
        return self._file(name)

    def _file(self, name):
        path = WEB_DIR / name
        if not path.is_file():
            raise web.HTTPNotFound()
        resp = web.FileResponse(path)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # ---------- websocket ----------
    async def ws(self, request):
        given = request.query.get("t", "")
        if not hmac.compare_digest(given, self.token):
            raise web.HTTPForbidden(text="bad token")

        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=1 << 20)
        await ws.prepare(request)
        self.clients.add(ws)
        self.on_clients(len(self.clients))
        log.info("phone connected from %s", request.remote)
        sess = {"pc": None, "track": None, "ws": ws, "cur_task": None, "rx": 0.0, "ry": 0.0,
                "held": set()}  # mouse buttons the phone is holding down
        await ws.send_str(json.dumps({"t": "hello", "os": "mac" if sys.platform == "darwin" else "win"}))
        if self._clip_task is None:
            self._clip_task = asyncio.create_task(self._watch_clipboard())
            self._status_task = asyncio.create_task(self._watch_battery())
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                    t = str(m.get("t", ""))
                    if t in ("b", "point") and m.get("a") in ("down", "up"):
                        btn = m.get("b", "left")
                        (sess["held"].add if m["a"] == "down" else sess["held"].discard)(btn)
                    if t.startswith("rtc_") or t in ("point", "rel", "audio"):
                        reply = await self.handle_screen(sess, m)
                    elif t in SYSTEM_MSGS:
                        reply = await self.handle_system(m)
                    else:
                        reply = self.handle(m)
                except Exception as e:  # never let one bad message kill the session
                    log.warning("bad message %r: %s", msg.data[:200], e)
                    continue
                if reply is not None:
                    await ws.send_str(json.dumps(reply))
        finally:
            for btn in sess["held"]:   # phone vanished mid-drag: don't leave the button stuck down
                inp.button(btn, "up")
            await self._close_rtc(sess)
            self.clients.discard(ws)
            self.on_clients(len(self.clients))
            log.info("phone disconnected")
        return ws

    # ---------- screen sharing (WebRTC; the websocket carries the signaling) ----------
    async def handle_screen(self, sess: dict, m: dict):
        t = m["t"]
        if t == "rtc_offer":
            await self._close_rtc(sess)
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))  # LAN only: host candidates suffice
            track = ScreenTrack(self.grabber)
            track.configure(m.get("w"), m.get("fps"))
            sess.update(pc=pc, track=track)

            @pc.on("connectionstatechange")
            async def _state():
                log.info("screen stream: %s", pc.connectionState)
                if pc.connectionState == "failed":
                    await pc.close()

            pc.addTrack(track)
            if "m=audio" in m["sdp"]:   # laptop sound; silent until the phone turns it on
                sess["audio"] = audio.LoopbackAudioTrack()
                pc.addTrack(sess["audio"])
            sess["cur_task"] = asyncio.create_task(self._cursor_feed(sess, track))
            await pc.setRemoteDescription(RTCSessionDescription(sdp=m["sdp"], type=m["type"]))
            await pc.setLocalDescription(await pc.createAnswer())  # aiortc waits for ICE gathering
            reply = {"t": "rtc_answer", "sdp": pc.localDescription.sdp, "type": pc.localDescription.type,
                     "audio": audio.SUPPORTED}
            problem = screen_permission_problem()
            if problem:
                reply["warn"] = problem
            return reply
        if t == "rtc_cfg" and sess["track"]:
            sess["track"].configure(m.get("w"), m.get("fps"))
        elif t == "audio" and sess.get("audio"):
            sess["audio"].set_enabled(bool(m.get("on")))
        elif t == "rtc_stop":
            await self._close_rtc(sess)
        elif t == "point" and sess["track"] and sess["track"].mon:
            # touch on the screen preview: move there, then optionally click / press / release
            mon = sess["track"].mon
            fx, fy = min(max(float(m["x"]), 0.0), 1.0), min(max(float(m["y"]), 0.0), 1.0)
            inp.move_to(mon["left"] + fx * (mon["width"] - 1), mon["top"] + fy * (mon["height"] - 1))
            a = m.get("a")
            if a == "click":
                inp.button("left", "click")
            elif a == "rclick":
                inp.button("right", "click")
            elif a in ("down", "up"):
                inp.button("left", a)
        elif t == "rel" and sess["track"] and sess["track"].mon:
            # trackpad on the preview: move by a fraction of the screen, starting from where the cursor is
            mon = sess["track"].mon
            sess["rx"] += float(m["x"]) * mon["width"]
            sess["ry"] += float(m["y"]) * mon["height"]
            ix, iy = int(sess["rx"]), int(sess["ry"])
            sess["rx"] -= ix   # keep sub-pixel remainders so slow moves aren't lost
            sess["ry"] -= iy
            if ix or iy:
                cx, cy = inp.cursor_pos()
                inp.move_to(cx + ix, cy + iy)
        return None

    @staticmethod
    async def _cursor_feed(sess: dict, track):
        """Stream the cursor position (as a fraction of the shown monitor) so the phone can highlight it."""
        last = None
        while sess.get("track") is track:
            mon = track.mon
            if mon:
                cx, cy = inp.cursor_pos()
                cur = (round((cx - mon["left"]) / mon["width"], 4), round((cy - mon["top"]) / mon["height"], 4))
                if cur != last:
                    last = cur
                    try:
                        await sess["ws"].send_str(json.dumps({"t": "cur", "x": cur[0], "y": cur[1]}))
                    except Exception:
                        return
            await asyncio.sleep(0.03)

    # ---------- system: clipboard, media, volume, brightness, power ----------
    async def _sys(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self._sys_pool, fn, *args)

    async def _sys_state(self):
        vol, muted = await self._sys(sysctl.get_volume)
        bright = await self._sys(sysctl.get_brightness)
        st = await self._sys(status.get_status)
        return {"t": "sys", "vol": vol, "muted": muted, "bright": bright, "status": st}

    def _actions_msg(self):
        return {"t": "actions", "items": self.actions.items}

    async def _broadcast(self, msg: dict):
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:
                pass

    async def handle_system(self, m: dict):
        t = m["t"]
        if t == "media":
            await self._sys(sysctl.media, str(m.get("k", "")))
            return None
        if t == "vol":
            mute = m.get("mute")
            if mute == "toggle":
                mute = not (await self._sys(sysctl.get_volume))[1]
            await self._sys(sysctl.set_volume, m.get("v"), mute)
            return await self._sys_state()
        if t == "bright":
            if "v" in m:
                await self._sys(sysctl.set_brightness, int(m["v"]))
            else:
                await self._sys(sysctl.step_brightness, bool(m.get("up")))
            return await self._sys_state()
        if t == "sys_get":
            return await self._sys_state()
        # ---- app switcher ----
        if t == "wins":
            res = await self._sys(sysctl.list_windows, set(m.get("have") or []))
            return {"t": "wins", **res}
        if t == "win":
            ok = await self._sys(sysctl.window_action, int(m["id"]), str(m.get("a", "focus")))
            await asyncio.sleep(0.15)   # let the window settle, then send the fresh list
            res = await self._sys(sysctl.list_windows, set(m.get("have") or []))
            return {"t": "wins", "ok": ok, **res}
        # ---- open a link in the laptop's browser ----
        if t == "open_url":
            url = str(m.get("url", "")).strip()
            if url.lower().startswith("www."):
                url = "https://" + url
            if not url.lower().startswith(("http://", "https://")):
                return {"t": "toast", "msg": "Only http(s) links can be opened"}
            await self._sys(sysctl.open_target, url)
            return {"t": "toast", "msg": "Opened on laptop"}
        # ---- quick actions ----
        if t == "actions":
            return self._actions_msg()
        if t == "action_run":
            a = self.actions.get(str(m.get("id")))
            if a:
                log.info("quick action: %s", a["name"])
                try:
                    await run_action(a, inp, sysctl, self._sys)
                except Exception as e:
                    return {"t": "toast", "msg": f"“{a['name']}” failed: {e}"}
            return None
        if t in ("action_save", "action_del", "action_move"):
            if t == "action_save":
                self.actions.upsert(m.get("action") or {})
            elif t == "action_del":
                self.actions.delete(str(m.get("id")))
            else:
                self.actions.move(str(m.get("id")), int(m.get("d", 0)))
            await self._broadcast(self._actions_msg())   # every connected phone sees the change
            return None
        if t == "power" and m.get("a") in POWER_ACTIONS:
            log.info("power action from phone: %s", m["a"])
            await self._sys(sysctl.power, m["a"])
            return None
        if t == "clip_get":
            text = await self._sys(sysctl.get_clipboard)
            return {"t": "clip", "v": (text or "")[:CLIP_MAX], "manual": True}
        if t == "clip_set":
            text = str(m.get("v", ""))[:1_000_000]
            self._clip_from_phone = text
            ok = await self._sys(sysctl.set_clipboard, text)
            if ok and m.get("paste"):
                await asyncio.sleep(0.05)
                inp.hotkey("mod+v")   # Ctrl+V / Cmd+V into the focused app
            return {"t": "clip_ok", "ok": bool(ok), "paste": bool(m.get("paste"))}
        return None

    async def _watch_battery(self):
        """Every 20 s: low battery / charger / fully charged -> alert on the phone."""
        while True:
            try:
                st = await self._sys(status.get_status)
                for msg in self._alerts.check(st):
                    log.info("alert: %s", msg)
                    await self._broadcast({"t": "alert", "msg": msg})
            except Exception as e:
                log.debug("status check failed: %s", e)
            await asyncio.sleep(20)

    async def _watch_clipboard(self):
        """Push laptop clipboard text to connected phones whenever it changes."""
        seq = await self._sys(sysctl.clipboard_seq)
        while True:
            await asyncio.sleep(0.4)
            if not self.clients:
                continue
            try:
                new = await self._sys(sysctl.clipboard_seq)
                if new == seq:
                    continue
                seq = new
                text = await self._sys(sysctl.get_clipboard)
            except Exception as e:
                log.debug("clipboard read failed: %s", e)
                continue
            if not text or text == self._clip_from_phone:
                continue
            self._clip_from_phone = None
            msg = json.dumps({"t": "clip", "v": text[:CLIP_MAX], "truncated": len(text) > CLIP_MAX})
            for ws in list(self.clients):
                try:
                    await ws.send_str(msg)
                except Exception:
                    pass

    @staticmethod
    async def _close_rtc(sess: dict):
        pc = sess.get("pc")
        task = sess.get("cur_task")
        snd = sess.get("audio")
        sess.update(pc=None, track=None, cur_task=None, audio=None)
        if task:
            task.cancel()
        if snd:
            snd.set_enabled(False)   # stop the capture thread
        if pc:
            await pc.close()

    def handle(self, m: dict):
        t = m.get("t")
        if t == "m":
            inp.move(int(m["x"]), int(m["y"]))
        elif t == "s":
            inp.scroll(int(m.get("x", 0)), int(m.get("y", 0)))
        elif t == "b":
            inp.button(m.get("b", "left"), m.get("a", "click"))
        elif t == "txt":
            text = str(m.get("v", ""))[:10000]
            if text:
                inp.type_text(text)
        elif t == "edit":  # live keyboard: undo `del` characters, then type `ins`
            if m.get("del"):
                inp.delete_back(int(m["del"]))
            text = str(m.get("ins", ""))[:10000]
            if text:
                inp.type_text(text)
        elif t == "key":
            inp.hotkey(str(m.get("k", "")))
        elif t == "ping":
            return {"t": "pong", "id": m.get("id")}
        return None

    # ---------- lifecycle ----------
    async def start(self):
        self.loop = asyncio.get_running_loop()
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.ws)
        app.router.add_get("/{name}", self.static)

        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.cert, self.key)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", self.port, ssl_context=ctx).start()
        log.info("listening on https://0.0.0.0:%d", self.port)

    async def kick_all(self):
        for ws in list(self.clients):
            await ws.close(code=4001, message=b"token changed")
