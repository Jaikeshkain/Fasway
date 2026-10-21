"""System-tray (Windows) / menu-bar (macOS) icon. Menu clicks are posted to the app's event queue,
because the Tk window may only be touched from the Tk thread."""
from __future__ import annotations

import logging
import threading

from PIL import Image, ImageDraw

log = logging.getLogger("fasway")


def _icon_image(connected: bool) -> Image.Image:
    s, k = 64, 1.0  # same design as web/icon.svg (64x64)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=14, fill="#4f8cff")
    pts = [(20, 16), (46, 16), (46, 24), (29, 24), (29, 30), (43, 30), (43, 38), (29, 38), (29, 50), (20, 50)]
    d.polygon([(x * k, y * k) for x, y in pts], fill="white")
    if connected:   # green dot = a phone is connected
        d.ellipse((40, 40, 63, 63), fill="#2ecc71", outline="white", width=3)
    return img


class Tray:
    def __init__(self, post, state):
        """post(event) sends an event to the app; state() returns a dict for menu checkmarks."""
        self.post = post
        self.state = state
        self.icon = None
        self._images = {c: _icon_image(c) for c in (False, True)}

    def start(self):
        try:
            import pystray
        except Exception as e:
            log.warning("tray icon unavailable: %s", e)
            return False
        item, menu = pystray.MenuItem, pystray.Menu
        st = lambda key: (lambda _item: bool(self.state().get(key)))  # noqa: E731
        self.icon = pystray.Icon("Fasway", self._images[False], "Fasway – waiting for phone", menu(
            item("Show pairing QR", lambda: self.post(("show", None)), default=True),
            item(lambda _i: self.state().get("phones_text", ""), None, enabled=False),
            menu.SEPARATOR,
            item("Start with Windows" if __import__("sys").platform == "win32" else "Start at login",
                 lambda: self.post(("toggle_autostart", None)), checked=st("autostart")),
            item("Run as administrator", lambda: self.post(("toggle_admin", None)), checked=st("admin"),
                 visible=st("is_windows")),
            menu.SEPARATOR,
            item("Quit Fasway", lambda: self.post(("quit", None))),
        ))
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
        return True

    def set_connected(self, n: int):
        if not self.icon:
            return
        self.icon.icon = self._images[n > 0]
        self.icon.title = f"Fasway – {n} phone{'s' if n != 1 else ''} connected" if n else "Fasway – waiting for phone"
        self.icon.update_menu()

    def notify(self, message: str, title: str = "Fasway"):
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def refresh(self):
        if self.icon:
            self.icon.update_menu()

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
