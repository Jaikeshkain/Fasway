"""HTTPS + WebSocket server: serves the phone web app and executes its input commands."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import ssl
import sys
from pathlib import Path

from aiohttp import web, WSMsgType
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from .platform_input import inp, screen_permission_problem
from .screen import ScreenGrabber, ScreenTrack

log = logging.getLogger("fasway")
# Packaged apps (PyInstaller) unpack bundled files under sys._MEIPASS
WEB_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "web"


class FaswayServer:
    def __init__(self, token: str, port: int, cert: Path, key: Path, on_clients=None):
        self.token = token
        self.port = port
        self.cert, self.key = cert, key
        self.on_clients = on_clients or (lambda n: None)
        self.clients: set[web.WebSocketResponse] = set()
        self.grabber = ScreenGrabber()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None

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
        sess = {"pc": None, "track": None}
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                    if str(m.get("t", "")).startswith("rtc_") or m.get("t") == "point":
                        reply = await self.handle_screen(sess, m)
                    else:
                        reply = self.handle(m)
                except Exception as e:  # never let one bad message kill the session
                    log.warning("bad message %r: %s", msg.data[:200], e)
                    continue
                if reply is not None:
                    await ws.send_str(json.dumps(reply))
        finally:
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
            await pc.setRemoteDescription(RTCSessionDescription(sdp=m["sdp"], type=m["type"]))
            await pc.setLocalDescription(await pc.createAnswer())  # aiortc waits for ICE gathering
            reply = {"t": "rtc_answer", "sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
            problem = screen_permission_problem()
            if problem:
                reply["warn"] = problem
            return reply
        if t == "rtc_cfg" and sess["track"]:
            sess["track"].configure(m.get("w"), m.get("fps"))
        elif t == "rtc_stop":
            await self._close_rtc(sess)
        elif t == "point" and sess["track"] and sess["track"].mon:
            mon = sess["track"].mon
            fx, fy = min(max(float(m["x"]), 0.0), 1.0), min(max(float(m["y"]), 0.0), 1.0)
            inp.move_to(mon["left"] + fx * (mon["width"] - 1), mon["top"] + fy * (mon["height"] - 1))
        return None

    @staticmethod
    async def _close_rtc(sess: dict):
        pc = sess.get("pc")
        sess.update(pc=None, track=None)
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
