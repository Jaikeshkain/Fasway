"""Laptop sound -> phone, as a WebRTC audio track (Opus) next to the screen video.

Windows: WASAPI loopback of the default speakers (soundcard). macOS has no built-in way to capture
system audio (it needs a driver like BlackHole), so there the track just sends silence.
"""
from __future__ import annotations

import asyncio
import collections
import fractions
import logging
import sys
import threading
import time
import warnings

import av
import numpy as np
from aiortc import MediaStreamTrack

log = logging.getLogger("fasway")

RATE = 48000
FRAME = 960            # 20 ms per packet, what Opus expects
MAX_QUEUE = 3          # keep at most ~60 ms buffered: low latency beats perfect smoothness
TIME_BASE = fractions.Fraction(1, RATE)
SUPPORTED = sys.platform == "win32"


class LoopbackAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._q: collections.deque = collections.deque()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start: float | None = None
        self._pts = 0
        self._silence = np.zeros((1, FRAME * 2), np.int16)

    # ---- capture thread ----
    def set_enabled(self, on: bool):
        if on and SUPPORTED and not (self._thread and self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._capture, name="audio", daemon=True)
            self._thread.start()
        elif not on:
            self._stop.set()
            self._q.clear()

    def _capture(self):
        import soundcard as sc
        warnings.filterwarnings("ignore", module="soundcard")  # "data discontinuity" chatter
        while not self._stop.is_set():
            try:
                spk = sc.default_speaker()
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
                with mic.recorder(samplerate=RATE, channels=2, blocksize=FRAME) as rec:
                    log.info("laptop audio: streaming %s", spk.name)
                    while not self._stop.is_set():
                        data = rec.record(numframes=FRAME)
                        pcm = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16).reshape(1, -1)  # interleaved
                        self._q.append(pcm)
                        while len(self._q) > MAX_QUEUE:
                            self._q.popleft()
            except Exception as e:   # e.g. speakers unplugged / default device changed: retry
                log.info("laptop audio capture restarting: %s", e)
                self._stop.wait(1.0)

    def stop(self):
        self.set_enabled(False)
        super().stop()

    # ---- aiortc pulls a 20 ms frame at a time ----
    async def recv(self):
        if self._start is None:
            self._start = time.monotonic()
        self._pts += FRAME
        wait = self._start + self._pts / RATE - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        elif wait < -0.2:  # fell behind (e.g. laptop was busy): resync instead of bursting
            self._start = time.monotonic() - self._pts / RATE
        pcm = self._q.popleft() if self._q else self._silence
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="stereo")
        frame.sample_rate = RATE
        frame.pts = self._pts
        frame.time_base = TIME_BASE
        return frame
