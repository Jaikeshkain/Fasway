"""Live desktop streaming over WebRTC.

ScreenTrack is an aiortc video track: each frame grabs the monitor under the
cursor (mss), draws the mouse pointer (screen capture doesn't include it) and
hands a scaled YUV frame to aiortc's VP8 encoder.
"""
from __future__ import annotations

import asyncio
import fractions
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import av
import mss
import numpy as np
from aiortc import MediaStreamTrack
from aiortc.codecs import vpx
from PIL import Image, ImageDraw

from .platform_input import inp

# aiortc defaults (0.5–1.5 Mbps) blur on-screen text; a LAN can easily carry more
vpx.DEFAULT_BITRATE = 3_000_000
vpx.MAX_BITRATE = 10_000_000

log = logging.getLogger("fasway")

VIDEO_CLOCK = 90000
TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK)

# Classic arrow pointer, 16 units tall, tip at (0, 0)
_ARROW = [(0, 0), (0, 16), (4, 12), (7, 19), (10, 18), (7, 11), (12, 11)]


def _cursor_sprite(scale: float) -> np.ndarray:
    """Pre-rendered pointer as BGRA, ready to alpha-blend onto captured frames."""
    pad = 2
    w, h = int(13 * scale) + pad * 2, int(20 * scale) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).polygon([(pad + x * scale, pad + y * scale) for x, y in _ARROW],
                                fill=(255, 255, 255, 255), outline=(0, 0, 0, 255),
                                width=max(1, round(scale)))
    rgba = np.asarray(img)
    return rgba[:, :, [2, 1, 0, 3]].copy()  # RGBA -> BGRA


def _contains(m, x, y):
    return m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]


class _DxgiCapture:
    """Windows Desktop Duplication (GPU) capture: ~1 ms per grab vs ~27 ms for GDI,
    and it only returns a frame when the screen actually changed."""

    def __init__(self):
        import dxcam
        self.outputs = []  # (monitor rect, camera)
        for i in range(8):
            try:
                cam = dxcam.create(output_idx=i, output_color="BGRA")
            except Exception:
                break
            if cam is None:
                break
            r = cam._output.desc.DesktopCoordinates
            self.outputs.append(({"left": r.left, "top": r.top, "width": r.right - r.left,
                                  "height": r.bottom - r.top}, cam))
        if not self.outputs:
            raise RuntimeError("no DXGI outputs")
        self.last: dict[int, np.ndarray] = {}

    def grab(self, cx, cy):
        """Returns (BGRA array, monitor rect, changed)."""
        idx = next((i for i, (m, _) in enumerate(self.outputs) if _contains(m, cx, cy)), 0)
        mon, cam = self.outputs[idx]
        arr = cam.grab()
        if arr is not None:
            self.last[idx] = arr
            return arr, mon, True
        if idx not in self.last:  # first grab after start: wait briefly for an initial frame
            for _ in range(50):
                time.sleep(0.01)
                arr = cam.grab()
                if arr is not None:
                    self.last[idx] = arr
                    return arr, mon, True
            raise RuntimeError("DXGI returned no frame")
        return self.last[idx], mon, False


class ScreenGrabber:
    def __init__(self):
        # capture objects are per-thread (GDI/DXGI), so all captures run on one dedicated thread
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screen")
        self._local = threading.local()
        self._sprites: dict[float, np.ndarray] = {}
        self._cache = None  # (key, VideoFrame, mon): reused while nothing on screen changes

    def _sct(self):
        if not hasattr(self._local, "sct"):
            self._local.sct = getattr(mss, "MSS", mss.mss)()
        return self._local.sct

    def _dxgi(self):
        if not hasattr(self._local, "dxgi"):
            self._local.dxgi = None
            if sys.platform == "win32":
                try:
                    self._local.dxgi = _DxgiCapture()
                except Exception as e:
                    log.info("fast DXGI capture unavailable (%s); using GDI", e)
        return self._local.dxgi

    async def grab(self, max_width: int):
        return await asyncio.get_running_loop().run_in_executor(self._pool, self._grab, max_width)

    def _capture(self, cx, cy):
        """Returns (BGRA array, monitor rect, changed)."""
        dx = self._dxgi()
        if dx:
            try:
                return dx.grab(cx, cy)
            except Exception as e:  # e.g. display mode change, secure desktop (UAC)
                log.info("DXGI capture failed (%s); using GDI", e)
                self._local.dxgi = None
        sct = self._sct()
        mons = sct.monitors[1:] or sct.monitors
        mon = next((m for m in mons if _contains(m, cx, cy)), mons[0])
        shot = sct.grab(mon)
        arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return arr, mon, True

    def _grab(self, max_width: int):
        """Returns (yuv420p VideoFrame, monitor rect)."""
        cx, cy = inp.cursor_pos()
        src, mon, changed = self._capture(cx, cy)
        key = (cx, cy, int(max_width), mon["left"], mon["top"])
        if not changed and self._cache and self._cache[0] == key:
            return self._cache[1], self._cache[2]   # nothing moved: skip scaling/converting

        sh, sw = src.shape[:2]
        frame = src.copy()  # keep the captured frame clean; the cursor is drawn on a copy

        # cursor position in captured pixels (mon is in points on macOS Retina, pixels on Windows)
        px_per_unit = sw / mon["width"]
        x = int((cx - mon["left"]) * px_per_unit)
        y = int((cy - mon["top"]) * px_per_unit)
        scale = round(max(1.0, sh / 1080) * px_per_unit, 1) * 1.3
        sprite = self._sprites.get(scale)
        if sprite is None:
            sprite = self._sprites[scale] = _cursor_sprite(scale)
        self._blend(frame, sprite, x - 2, y - 2)

        # scale + convert to YUV in one fast swscale pass; VP8 needs even dimensions
        w = min(int(max_width), sw)
        w -= w % 2
        h = round(sh * w / sw)
        h -= h % 2
        vf = av.VideoFrame.from_ndarray(frame, format="bgra")
        vf = vf.reformat(width=w, height=h, format="yuv420p", interpolation="AREA")  # AREA keeps text sharp
        mon = dict(mon)
        self._cache = (key, vf, mon)
        return vf, mon

    @staticmethod
    def _blend(frame: np.ndarray, sprite: np.ndarray, x: int, y: int):
        fh, fw = frame.shape[:2]
        sh, sw = sprite.shape[:2]
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + sw, fw), min(y + sh, fh)
        if x0 >= x1 or y0 >= y1:
            return
        s = sprite[y0 - y:y1 - y, x0 - x:x1 - x]
        a = s[:, :, 3:4].astype(np.float32) / 255.0
        region = frame[y0:y1, x0:x1, :3]
        region[:] = (region * (1 - a) + s[:, :, :3] * a).astype(np.uint8)


class ScreenTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, grabber: ScreenGrabber, max_width: int = 1280, fps: int = 30):
        super().__init__()
        self.grabber = grabber
        self.max_width = max_width
        self.fps = fps
        self.mon: dict | None = None
        self._start: float | None = None
        self._next: float | None = None

    def configure(self, max_width=None, fps=None):
        if max_width:
            self.max_width = max(320, min(int(max_width), 3840))
        if fps:
            self.fps = max(5, min(int(fps), 60))

    async def recv(self):
        now = time.monotonic()
        if self._next is None:
            self._start = self._next = now
        wait = self._next - now
        if wait > 0.001:
            await asyncio.sleep(wait)
        # fixed schedule so sleep rounding doesn't accumulate; never build a backlog when behind
        period = 1 / self.fps
        t = time.monotonic()
        self._next = max(self._next + period, t - period)

        frame, self.mon = await self.grabber.grab(self.max_width)
        # timestamps from the wall clock, so slow captures never build up latency on the phone
        frame.pts = int((t - self._start) * VIDEO_CLOCK)
        frame.time_base = TIME_BASE
        return frame
