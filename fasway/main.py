"""Fasway laptop service: runs in the tray, announces fasway-<id>.local and shows a pairing QR on demand."""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import queue
import secrets
import socket
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import qrcode
from PIL import ImageTk

from . import autostart
from .certs import cert_fingerprint, ensure_cert
from .discovery import Announcer, new_device_id
from .files import open_folder
from .platform_input import permission_problem
from .server import FaswayServer
from .tray import Tray


def _data_dir() -> Path:
    if not getattr(sys, "frozen", False):          # running from source: keep data next to the project
        return Path(__file__).resolve().parent.parent / "data"
    if sys.platform == "darwin":                   # packaged app: the bundle itself is read-only
        return Path.home() / "Library" / "Application Support" / "Fasway"
    return Path(os.environ.get("APPDATA", Path.home())) / "Fasway"


DATA = _data_dir()
CONFIG = DATA / "config.json"
DEFAULT_PORT = 8443
# localhost only: keeps Fasway single-instance and lets a 2nd launch open the window (env override for tests)
CONTROL_PORT = int(os.environ.get("FASWAY_CONTROL_PORT", "47391"))
FONT = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
FG, MUTED = "#111111", "#555555"  # explicit colours: macOS dark mode would otherwise draw white-on-white

log = logging.getLogger("fasway")


def setup_logging():
    """Log to data/fasway.log (Fasway usually runs without a console) and to the console when there is one."""
    DATA.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(DATA / "fasway.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr:   # pythonw / packaged app: no console
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        root.addHandler(sh)
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
    cfg.setdefault("device_id", new_device_id())   # -> fasway-<id>.local, fixed for this install
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


def is_admin() -> bool | None:
    """True/False on Windows; None elsewhere (macOS uses per-app permissions instead)."""
    if sys.platform != "win32":
        return None
    from .input_win import is_elevated
    return is_elevated()


def relaunch_as_admin(background: bool = False) -> bool:
    """Start an elevated copy of Fasway (Windows shows the UAC prompt). False if the user declined."""
    import ctypes
    prog, args, workdir = autostart.launch_command()   # pythonw / packaged exe: no console window
    args = [a for a in args if a != "--background"] + ["--no-elevate", "--takeover"]
    if background:
        args.append("--background")
    params = " ".join(f'"{a}"' if " " in a else a for a in args)
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", prog, params, workdir, 1) > 32


# ---------------- single instance ----------------

def acquire_instance(takeover: bool) -> socket.socket | None:
    """Hold a localhost port while running. `takeover`: we were started to replace the running copy
    (e.g. restart as administrator), so wait for it to exit."""
    deadline = time.monotonic() + (10 if takeover else 0)
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind(("127.0.0.1", CONTROL_PORT))
            s.listen(4)
            return s
        except OSError:
            s.close()
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.3)


def signal_running_instance():
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=2) as c:
            c.sendall(b"show\n")
    except OSError:
        pass


class App:
    def __init__(self, background: bool, lock: socket.socket):
        self.cfg = load_config()
        self.ips = lan_ips()
        self.events: queue.Queue = queue.Queue()
        self.phones = 0
        self.reached_ips: set[str] = set()   # laptop addresses phones actually connected through
        self.admin = is_admin()
        self.autostart_on = autostart.is_enabled()

        self.announcer = Announcer(self.cfg["device_id"], self.cfg["port"], label=f"Fasway on {socket.gethostname()}")
        self.hostname = self.announcer.hostname
        self._announce()

        cert, key = ensure_cert(DATA, self.ips, self.hostname)
        self.cert_fp = cert_fingerprint(cert)   # the native app pins this (in the QR) instead of a CA
        self.server = FaswayServer(self.cfg["token"], self.cfg["port"], cert, key, data_dir=DATA,
                                   on_clients=lambda n: self.events.put(("clients", n)),
                                   on_local_ip=lambda ip: self.events.put(("local_ip", ip)),
                                   on_pair_request=lambda name, ip, answer: self.events.put(("pair", (name, ip, answer))),
                                   on_devices=lambda: self.events.put(("devices", None)),
                                   on_file_received=lambda path, phone: self.events.put(("file_received", (path, phone))))
        threading.Thread(target=self._run_server, name="server", daemon=True).start()
        threading.Thread(target=self._control_loop, args=(lock,), name="control", daemon=True).start()

        self.tray = Tray(self.events.put, self._tray_state)
        has_tray = self.tray.start()
        self._build_ui()
        if background and has_tray:
            self.root.withdraw()   # started at sign-in: live quietly in the tray
        self._hid_hint_shown = False

    # ---------- background threads ----------
    def _run_server(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.server.start())
            self.events.put(("status", "running"))
            loop.run_forever()
        except OSError as e:
            log.error("server failed to start: %s", e)
            self.events.put(("status", f"error: {e}"))

    def _control_loop(self, lock: socket.socket):
        """A second launch of Fasway connects here and asks us to show the window."""
        while True:
            try:
                conn, _ = lock.accept()
                with conn:
                    conn.settimeout(2)
                    if conn.recv(16).startswith(b"show"):
                        self.events.put(("show", None))
            except OSError:
                return

    def _announce(self):
        """Announce the main address plus any address a phone has reached us on (unreachable ones would
        make the phone wait for a timeout before trying the next)."""
        ips = [self.ips[0]] + [ip for ip in self.ips[1:] if ip in self.reached_ips]
        threading.Thread(target=self.announcer.update, args=(ips,), daemon=True).start()

    def _tray_state(self) -> dict:
        return {"autostart": self.autostart_on, "admin": bool(self.cfg.get("always_admin")),
                "is_windows": sys.platform == "win32",
                "phones_text": f"{self.phones} phone{'s' if self.phones != 1 else ''} connected" if self.phones
                else "No phone connected"}

    # ---------- ui ----------
    def url(self) -> str:
        # t = pairing code · id = this laptop (matches the mDNS announcement) · fp = certificate fingerprint.
        # The web app only reads t; the Android app uses id to find the laptop and fp to pin its certificate.
        return (f"https://{self.addr_var.get().split(' ')[0]}:{self.cfg['port']}/"
                f"#t={self.cfg['token']}&id={self.cfg['device_id']}&fp={self.cert_fp}")

    def _address_choices(self) -> list[str]:
        return [f"{self.hostname}  (any Wi-Fi)"] + self.ips

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
                     wraplength=360, justify="center").pack(padx=16, pady=(8, 0))

        self.qr_label = tk.Label(root, bg="white")
        self.qr_label.pack(**pad)

        row = tk.Frame(root, bg="white")
        row.pack(**pad)
        tk.Label(row, text="Address:", bg="white", fg=FG, font=(FONT, 10)).pack(side="left")
        self.addr_var = tk.StringVar(value=self._address_choices()[0])
        self.addr_combo = ttk.Combobox(row, textvariable=self.addr_var, values=self._address_choices(),
                                       state="readonly", width=30)
        self.addr_combo.pack(side="left", padx=6)
        self.addr_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_qr())

        self.url_var = tk.StringVar()
        tk.Entry(root, textvariable=self.url_var, state="readonly", width=56, fg=FG,
                 font=("Menlo" if sys.platform == "darwin" else "Consolas", 9), relief="flat",
                 readonlybackground="#f3f3f3").pack(**pad)
        self.hint_var = tk.StringVar()
        tk.Label(root, textvariable=self.hint_var, font=(FONT, 9), fg=MUTED, bg="white",
                 wraplength=380, justify="center").pack(padx=16)

        btns = tk.Frame(root, bg="white")
        btns.pack(**pad)
        ttk.Button(btns, text="Copy link", command=self.copy_link).pack(side="left", padx=4)
        ttk.Button(btns, text="New pairing code", command=self.new_token).pack(side="left", padx=4)

        opts = tk.Frame(root, bg="white")
        opts.pack(padx=16, pady=(4, 0))
        cb = dict(bg="white", fg=FG, activebackground="white", font=(FONT, 9), anchor="w")
        self.autostart_var = tk.BooleanVar(value=self.autostart_on)
        tk.Checkbutton(opts, text="Start with Windows (runs in the tray)" if sys.platform == "win32"
                       else "Start at login (menu bar)", variable=self.autostart_var,
                       command=lambda: self.events.put(("toggle_autostart", None)), **cb).pack(fill="x")

        # Windows blocks input to apps running as Administrator (Task Manager...) unless we are admin too
        if self.admin is not None:
            self.always_admin = tk.BooleanVar(value=bool(self.cfg.get("always_admin")))
            tk.Checkbutton(opts, text="Always run as administrator", variable=self.always_admin,
                           command=lambda: self.events.put(("toggle_admin", None)), **cb).pack(fill="x")
            if self.admin:
                tk.Label(opts, text="🛡 Running as administrator – admin apps can be controlled too",
                         font=(FONT, 9), fg="#0a7", bg="white").pack(pady=(2, 0))
            else:
                tk.Label(opts, text="Not running as administrator: apps like Task Manager can't be "
                                    "controlled from the phone.", font=(FONT, 9), fg="#a65e00", bg="white",
                         wraplength=360, justify="center").pack(pady=(2, 0))
                ttk.Button(opts, text="Restart as administrator", command=self.restart_as_admin).pack(pady=(4, 0))

        self.status_var = tk.StringVar(value="Starting…")
        tk.Label(root, textvariable=self.status_var, bg="white", font=(FONT, 10, "bold"),
                 fg="#0a7").pack(pady=(6, 4))

        # file sharing: drop files anywhere on this window (Windows) or pick them
        drop = tk.Frame(root, bg="#f3f6ff", highlightbackground="#9db8ff", highlightthickness=1)
        drop.pack(fill="x", padx=20, pady=(4, 2))
        tk.Label(drop, text="📁 Drop files on this window to send them to your phone" if sys.platform == "win32"
                 else "📁 Send files to your phone", font=(FONT, 9, "bold"), fg=FG, bg="#f3f6ff").pack(pady=(6, 2))
        fb = tk.Frame(drop, bg="#f3f6ff")
        fb.pack(pady=(0, 4))
        ttk.Button(fb, text="Send files to phone…", command=self.pick_files).pack(side="left", padx=4)
        ttk.Button(fb, text="Open received files", command=lambda: open_folder(self.server.files.inbox)).pack(side="left", padx=4)
        self.files_var = tk.StringVar(value=f"Files from the phone are saved in {self.server.files.inbox}")
        tk.Label(drop, textvariable=self.files_var, font=(FONT, 8), fg=MUTED, bg="#f3f6ff",
                 wraplength=360, justify="center").pack(padx=8, pady=(0, 6))
        self._drop_ready = False
        root.after(300, self._enable_drop)

        # trusted phones: only these can connect without asking; Remove disconnects one immediately
        self.phones_frame = tk.Frame(root, bg="white")
        self.phones_frame.pack(fill="x", padx=20, pady=(2, 14))
        self._render_phones()

        self.refresh_qr()
        root.after(100, self._poll)
        root.after(10_000, self._watch_network)
        root.protocol("WM_DELETE_WINDOW", self.hide)

    # ---------- files ----------
    def _enable_drop(self):
        if self._drop_ready or sys.platform != "win32":
            return
        from . import filedrop_win
        # the window may still be hidden (started in the tray): then this runs again from show()
        self._drop_ready = filedrop_win.enable(self.root, lambda paths: self.events.put(("send_files", paths)))

    def pick_files(self):
        paths = filedialog.askopenfilenames(parent=self.root, title="Send files to your phone")
        if paths:
            self.send_files(list(paths))

    def send_files(self, paths: list[str]):
        files = []
        for p in map(Path, paths):   # a dropped folder sends the files inside it
            if p.is_dir():
                files += [f for f in sorted(p.rglob("*")) if f.is_file()][:500]
            elif p.is_file():
                files.append(p)
        if not files:
            return
        if not self.phones:
            self.files_var.set("No phone connected: open Fasway on the phone, then send the files again.")
            return
        n = self.server.offer_files(files)
        what = files[0].name if n == 1 else f"{n} files"
        self.files_var.set(f"📤 Sending {what} to your phone (saved in its Downloads/Fasway)")

    def _file_received(self, path: Path, phone: str):
        self.files_var.set(f"📥 Received {path.name} from {phone}")
        self.tray.notify(f"📥 {path.name} received from {phone} (Downloads\\Fasway)")

    def refresh_qr(self):
        url = self.url()
        self.url_var.set(url)
        img = qrcode.make(url, box_size=7, border=2).get_image()
        self._qr_img = ImageTk.PhotoImage(img)
        self.qr_label.configure(image=self._qr_img)
        self.hint_var.set("This link keeps working when the laptop changes Wi-Fi or IP address."
                          if self.addr_var.get().startswith(self.hostname)
                          else "IP links stop working if the laptop's address changes.")
        log.info("phone link: %s", url.split("#")[0])

    def copy_link(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url())

    def new_token(self):
        """Old QR codes/links can no longer be used to ask for pairing. Trusted phones stay trusted."""
        self.cfg["token"] = secrets.token_urlsafe(16)
        save_config(self.cfg)
        self.server.token = self.cfg["token"]
        self.refresh_qr()

    # ---------- trusted phones ----------
    @staticmethod
    def _ago(ts: int) -> str:
        s = max(0, int(time.time()) - int(ts))
        if s < 90:
            return "just now"
        for unit, n in (("day", 86400), ("hour", 3600), ("min", 60)):
            if s >= n:
                v = s // n
                return f"{v} {unit}{'s' if v > 1 and unit != 'min' else ''} ago"
        return "just now"

    def _render_phones(self):
        f = self.phones_frame
        for w in f.winfo_children():
            w.destroy()
        devices = self.server.devices.listing()
        online = {d for d, socks in self.server._dev_sockets.items() if socks}
        tk.Label(f, text=f"Trusted phones ({len(devices)})" if devices else
                 "No trusted phones yet – a new phone must be approved here",
                 font=(FONT, 9, "bold"), fg=MUTED, bg="white", anchor="w").pack(fill="x")
        for d in devices:
            row = tk.Frame(f, bg="#f5f6f8")
            row.pack(fill="x", pady=2)
            state = "● connected" if d["id"] in online else f"last seen {self._ago(d.get('last_seen', 0))}"
            tk.Label(row, text=f"📱 {d['name']}", font=(FONT, 9), fg=FG, bg="#f5f6f8", anchor="w").pack(side="left", padx=6, pady=3)
            tk.Label(row, text=state, font=(FONT, 8), fg="#0a7" if d["id"] in online else MUTED,
                     bg="#f5f6f8").pack(side="left")
            ttk.Button(row, text="Remove", width=8, command=lambda d=d: self._remove_phone(d)).pack(side="right", padx=4, pady=2)

    def _remove_phone(self, d: dict):
        from tkinter import messagebox
        if not messagebox.askyesno("Remove phone", f"Remove “{d['name']}”?\n\nIt is disconnected now and has to "
                                                   "be approved again to reconnect.", parent=self.root):
            return
        if self.server.loop:
            asyncio.run_coroutine_threadsafe(self.server.remove_device(d["id"]), self.server.loop)

    def _ask_pair(self, name: str, ip: str, answer):
        """'Allow this phone?' - shown even when the main window is hidden in the tray."""
        win = tk.Toplevel(self.root)
        win.title("Fasway – new phone")
        win.configure(bg="white")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        done = {"v": False}

        def reply(ok: bool):
            if not done["v"]:
                done["v"] = True
                answer(ok)
                win.destroy()

        tk.Label(win, text="📱 A phone wants to connect", font=(FONT, 13, "bold"), fg=FG, bg="white").pack(padx=24, pady=(18, 6))
        tk.Label(win, text=name, font=(FONT, 11), fg=FG, bg="white").pack()
        tk.Label(win, text=f"from {ip}", font=(FONT, 9), fg=MUTED, bg="white").pack()
        tk.Label(win, text="Only allow phones you own: it will be able to control this laptop.",
                 font=(FONT, 9), fg="#a65e00", bg="white", wraplength=300, justify="center").pack(padx=24, pady=(10, 6))
        b = tk.Frame(win, bg="white")
        b.pack(pady=(4, 18))
        ttk.Button(b, text="Deny", command=lambda: reply(False)).pack(side="left", padx=6)
        allow = ttk.Button(b, text="Allow", command=lambda: reply(True))
        allow.pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", lambda: reply(False))
        win.after(115_000, lambda: reply(False))   # phone gives up after 2 minutes anyway
        win.update_idletasks()
        x = win.winfo_screenwidth() // 2 - win.winfo_width() // 2
        y = win.winfo_screenheight() // 3 - win.winfo_height() // 2
        win.geometry(f"+{x}+{y}")
        win.lift()
        win.focus_force()
        allow.focus_set()
        self.tray.notify(f"{name} wants to connect. Allow or deny it on the laptop.")

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.root.after(300, self._enable_drop)

    def hide(self):
        if not self.tray.icon:   # no tray available: closing the window quits
            self.quit()
            return
        self.root.withdraw()
        if not self._hid_hint_shown:
            self._hid_hint_shown = True
            self.tray.notify("Fasway keeps running in the tray. Right-click the icon to quit.")

    # ---------- events (all UI work happens here, on the Tk thread) ----------
    def _poll(self):
        try:
            while True:
                kind, val = self.events.get_nowait()
                if kind == "clients":
                    self.phones = val
                    self.status_var.set(f"● {val} phone connected" if val else "Waiting for phone…")
                    self.tray.set_connected(val)
                    self._render_phones()
                elif kind == "devices":
                    self._render_phones()
                elif kind == "pair":
                    self._ask_pair(*val)
                elif kind == "status":
                    self.status_var.set("Waiting for phone…" if val == "running" else val)
                elif kind == "local_ip":
                    if val not in self.reached_ips:
                        self.reached_ips.add(val)
                        self._announce()
                elif kind == "show":
                    self.show()
                elif kind == "quit":
                    self.quit()
                elif kind == "toggle_autostart":
                    self._set_autostart(not self.autostart_on)
                elif kind == "autostart_done":
                    self.autostart_on = val
                    self.autostart_var.set(val)
                    self.tray.refresh()
                elif kind == "toggle_admin":
                    self._toggle_admin()
                elif kind == "send_files":
                    self.send_files(val)
                elif kind == "file_received":
                    self._file_received(*val)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _watch_network(self):
        """Every 10 s: if the laptop moved to another network, re-announce and update the QR."""
        ips = lan_ips()
        if ips != self.ips:
            moved = ips[0] != self.ips[0]
            self.ips = ips
            self.reached_ips &= set(ips)
            self._announce()
            current = self.addr_var.get()
            self.addr_combo.configure(values=self._address_choices())
            if current not in self._address_choices():
                self.addr_var.set(self._address_choices()[0])
            self.refresh_qr()
            if moved:
                log.info("network changed: now %s", ips[0])
                self.tray.notify(f"New network ({ips[0]}). Your phone link {self.hostname} still works.")
        self.root.after(10_000, self._watch_network)

    def _set_autostart(self, on: bool):
        admin = bool(self.cfg.get("always_admin"))
        # may show a UAC prompt and wait for it: keep the UI responsive
        threading.Thread(target=lambda: self.events.put(("autostart_done", autostart.set_enabled(on, admin))),
                         daemon=True).start()

    def _toggle_admin(self):
        on = not self.cfg.get("always_admin")
        self.cfg["always_admin"] = on
        save_config(self.cfg)
        if hasattr(self, "always_admin"):
            self.always_admin.set(on)
        self.tray.refresh()
        if self.autostart_on:          # the sign-in task must start Fasway with the same rights
            self._set_autostart(True)
        if on and not self.admin:
            self.restart_as_admin()

    def restart_as_admin(self):
        if relaunch_as_admin(background=self.root.state() == "withdrawn"):
            # the elevated copy takes over (same port, same link); the phone reconnects by itself
            self._shutdown()
        else:
            self.status_var.set("Administrator restart was cancelled")

    def _shutdown(self):
        self.tray.stop()
        self.announcer.close()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        os._exit(0)

    def quit(self):
        log.info("quit")
        self._shutdown()

    def run(self):
        self.root.mainloop()


def main():
    background = "--background" in sys.argv
    setup_logging()
    lock = acquire_instance(takeover="--takeover" in sys.argv)
    if lock is None:                       # Fasway is already running
        if not background:
            signal_running_instance()      # ... so just bring up its window
        return
    cfg = load_config()
    if is_admin() is False and "--no-elevate" not in sys.argv and cfg.get("always_admin"):
        lock.close()
        if relaunch_as_admin(background):
            return   # the elevated copy runs Fasway; if the UAC prompt is declined we carry on normally
        lock = acquire_instance(takeover=True)
        if lock is None:
            return
    log.info("Fasway starting (%s%s)", "background" if background else "window",
             ", administrator" if is_admin() else "")
    App(background, lock).run()


if __name__ == "__main__":
    main()
