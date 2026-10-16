"""Fasway laptop service: starts the server and shows a pairing window with a QR code."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import secrets
import socket
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import qrcode
from PIL import ImageTk

from .certs import ensure_cert
from .platform_input import permission_problem
from .server import FaswayServer

def _data_dir() -> Path:
    if not getattr(sys, "frozen", False):          # running from source: keep data next to the project
        return Path(__file__).resolve().parent.parent / "data"
    if sys.platform == "darwin":                   # packaged app: the bundle itself is read-only
        return Path.home() / "Library" / "Application Support" / "Fasway"
    return Path(os.environ.get("APPDATA", Path.home())) / "Fasway"


DATA = _data_dir()
CONFIG = DATA / "config.json"
DEFAULT_PORT = 8443
FONT = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
FG, MUTED = "#111111", "#555555"  # explicit colours: macOS dark mode would otherwise draw white-on-white

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fasway")
for noisy in ("aioice", "aiortc"):  # per-candidate ICE chatter; keep warnings only
    logging.getLogger(noisy).setLevel(logging.WARNING)
# warns about unparsable monitor EDID on every brightness read, although brightness works fine
logging.getLogger("screen_brightness_control").setLevel(logging.ERROR)


def load_config() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text())
        except ValueError:
            pass
    cfg.setdefault("token", secrets.token_urlsafe(16))
    cfg.setdefault("port", DEFAULT_PORT)
    save_config(cfg)
    return cfg


def save_config(cfg: dict):
    CONFIG.write_text(json.dumps(cfg, indent=2))


def lan_ips() -> list[str]:
    """Best guess first (the interface used for the default route), then all others."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith(("127.", "169.254.")):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


class App:
    def __init__(self):
        self.cfg = load_config()
        self.ips = lan_ips()
        cert, key = ensure_cert(DATA, self.ips)
        self.events: queue.Queue = queue.Queue()
        self.server = FaswayServer(self.cfg["token"], self.cfg["port"], cert, key,
                                   on_clients=lambda n: self.events.put(("clients", n)), data_dir=DATA)
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        self._build_ui()

    # ---------- server thread ----------
    def _run_server(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.server.start())
            self.events.put(("status", "running"))
            loop.run_forever()
        except OSError as e:
            self.events.put(("status", f"error: {e}"))

    # ---------- ui ----------
    def url(self) -> str:
        return f"https://{self.ip_var.get()}:{self.cfg['port']}/#t={self.cfg['token']}"

    def _build_ui(self):
        self.root = root = tk.Tk()
        root.title("Fasway")
        root.resizable(False, False)
        root.configure(bg="white")
        pad = {"padx": 16, "pady": 6}

        tk.Label(root, text="Fasway", font=(FONT, 18, "bold"), fg=FG, bg="white").pack(pady=(14, 0))
        tk.Label(root, text="Scan with your phone camera (same Wi-Fi)",
                 font=(FONT, 10), fg=MUTED, bg="white").pack()

        problem = permission_problem()
        if problem:
            tk.Label(root, text=problem, font=(FONT, 10, "bold"), fg="#c0392b", bg="white",
                     wraplength=340, justify="center").pack(padx=16, pady=(8, 0))

        self.qr_label = tk.Label(root, bg="white")
        self.qr_label.pack(**pad)

        row = tk.Frame(root, bg="white")
        row.pack(**pad)
        tk.Label(row, text="Laptop IP:", bg="white", fg=FG, font=(FONT, 10)).pack(side="left")
        self.ip_var = tk.StringVar(value=self.ips[0])
        combo = ttk.Combobox(row, textvariable=self.ip_var, values=self.ips, state="readonly", width=16)
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_qr())

        self.url_var = tk.StringVar()
        tk.Entry(root, textvariable=self.url_var, state="readonly", width=52, fg=FG,
                 font=("Menlo" if sys.platform == "darwin" else "Consolas", 9), relief="flat",
                 readonlybackground="#f3f3f3").pack(**pad)

        btns = tk.Frame(root, bg="white")
        btns.pack(**pad)
        ttk.Button(btns, text="Copy link", command=self.copy_link).pack(side="left", padx=4)
        ttk.Button(btns, text="New pairing code", command=self.new_token).pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="Starting…")
        tk.Label(root, textvariable=self.status_var, bg="white", font=(FONT, 10, "bold"),
                 fg="#0a7").pack(pady=(4, 14))

        self.refresh_qr()
        root.after(100, self._poll)
        root.protocol("WM_DELETE_WINDOW", self.quit)

    def refresh_qr(self):
        url = self.url()
        self.url_var.set(url)
        img = qrcode.make(url, box_size=7, border=2).get_image()
        self._qr_img = ImageTk.PhotoImage(img)
        self.qr_label.configure(image=self._qr_img)
        print(f"\nOpen on your phone: {url}\n", flush=True)

    def copy_link(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url())

    def new_token(self):
        self.cfg["token"] = secrets.token_urlsafe(16)
        save_config(self.cfg)
        self.server.token = self.cfg["token"]
        if self.server.loop:
            asyncio.run_coroutine_threadsafe(self.server.kick_all(), self.server.loop)
        self.refresh_qr()

    def _poll(self):
        try:
            while True:
                kind, val = self.events.get_nowait()
                if kind == "clients":
                    self.status_var.set(f"● {val} phone connected" if val else "Waiting for phone…")
                elif kind == "status":
                    self.status_var.set("Waiting for phone…" if val == "running" else val)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def quit(self):
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


def main():
    App().run()


if __name__ == "__main__":
    main()
