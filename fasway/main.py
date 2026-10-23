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
from . import shellmenu, ui
from .version import __version__
from .discovery import Announcer, new_device_id
from .files import open_folder
from .platform_input import permission_problem
from .server import FaswayServer
from .tray import Tray, _icon_image


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


def relaunch_as_admin(background: bool = False, send: list[str] | None = None) -> bool:
    """Start an elevated copy of Fasway (Windows shows the UAC prompt). False if the user declined."""
    import ctypes
    prog, args, workdir = autostart.launch_command()   # pythonw / packaged exe: no console window
    args = [a for a in args if a != "--background"] + ["--no-elevate", "--takeover"]
    if background:
        args.append("--background")
    if send:   # files from Explorer's "Send to phone" that started us
        args += ["--send", *send]
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


def signal_running_instance(msg: bytes = b"show\n") -> bool:
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=2) as c:
            c.sendall(msg)
        return True
    except OSError:
        return False


def send_args() -> list[str]:
    """Paths after --send (Explorer's "Send to phone (Fasway)")."""
    if "--send" not in sys.argv:
        return []
    return [a for a in sys.argv[sys.argv.index("--send") + 1:] if not a.startswith("--")]


class App:
    def __init__(self, background: bool, lock: socket.socket, pending_send: list | None = None):
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
                                   on_file_received=lambda path, phone: self.events.put(("file_received", (path, phone))),
                                   on_link_quality=lambda *a: self.events.put(("link", a)))
        threading.Thread(target=self._run_server, name="server", daemon=True).start()
        threading.Thread(target=self._control_loop, args=(lock,), name="control", daemon=True).start()

        self._pending_send: list = []      # files to send once a phone connects
        self._menu_batch: list = []        # paths from Explorer's "Send to phone", gathered for 0.5 s
        self._menu_flush = None
        if pending_send:
            self.events.put(("send_menu", pending_send))
        if sys.platform == "win32" and self.cfg.get("send_menu", True):
            shellmenu.install(DATA)       # keeps the right-click entry pointing at this copy of Fasway

        self._weak_phones: dict[str, str] = {}   # phones reporting weak Wi-Fi: id -> name
        self._laptop_signal: int | None = None    # this laptop's Wi-Fi signal %
        self._laptop_weak = False
        self._weak_told: dict[str, float] = {}   # last notification time per subject (no spam)
        threading.Thread(target=self._watch_wifi, name="wifi", daemon=True).start()

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
        """A second launch of Fasway connects here: "show" (open the window) or "send" + paths (Explorer's
        "Send to phone" on files)."""
        while True:
            try:
                conn, _ = lock.accept()
            except OSError:
                return
            try:
                with conn:
                    conn.settimeout(2)
                    data = b""
                    while len(data) < 1 << 20:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        data += chunk
            except OSError:
                continue
            if data.startswith(b"show"):
                self.events.put(("show", None))
            elif data.startswith(b"send\n"):
                paths = [p for p in data[5:].decode("utf-8", "replace").split("\n") if p.strip()]
                self.events.put(("send_menu", paths))

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
        root.configure(bg=ui.BG)
        ui.style_ttk(root)
        ui.dark_title_bar(root)
        k = self.k = ui.scale(root)
        px = lambda v: int(v * k)  # noqa: E731
        try:
            self._logo = ImageTk.PhotoImage(_icon_image(False).resize((px(40), px(40))))
            root.iconphoto(True, ImageTk.PhotoImage(_icon_image(False)))
        except Exception:
            self._logo = None

        # ---- header: logo, name, live status ----
        head = tk.Frame(root, bg=ui.BG)
        head.pack(fill="x", padx=px(22), pady=(px(18), px(12)))
        if self._logo:
            tk.Label(head, image=self._logo, bg=ui.BG).pack(side="left")
        titles = tk.Frame(head, bg=ui.BG)
        titles.pack(side="left", padx=px(12))
        tk.Label(titles, text="Fasway", font=(ui.FONT, 18, "bold"), fg=ui.TEXT, bg=ui.BG, anchor="w").pack(fill="x")
        tk.Label(titles, text="Control this laptop from your phone", font=(ui.FONT, 9), fg=ui.MUTED, bg=ui.BG,
                 anchor="w").pack(fill="x")
        pill = tk.Frame(head, bg=ui.PANEL2, padx=px(12), pady=px(6))
        pill.pack(side="right")
        self.status_dot = ui.Dot(pill, ui.PANEL2)
        self.status_dot.pack(side="left")
        self.status_var = tk.StringVar(value="Starting…")
        tk.Label(pill, textvariable=self.status_var, font=(ui.FONT, 10, "bold"), fg=ui.TEXT,
                 bg=ui.PANEL2).pack(side="left", padx=(px(6), 0))
        self.status_dot.set(ui.WARN, True)

        problem = permission_problem()
        if problem:
            tk.Label(root, text="⚠  " + problem, font=(ui.FONT, 9, "bold"), fg="#1a1300", bg=ui.WARN,
                     wraplength=px(700), justify="left", anchor="w", padx=px(12), pady=px(8)).pack(
                fill="x", padx=px(22), pady=(0, px(12)))

        # weak Wi-Fi warning (shown by _update_status)
        self.wifi_warn = tk.Label(root, font=(ui.FONT, 9, "bold"), fg="#1a1300", bg=ui.WARN, anchor="w",
                                  justify="left", wraplength=px(700), padx=px(12), pady=px(8))
        body = self._body = tk.Frame(root, bg=ui.BG)
        body.pack(fill="both", padx=px(22), pady=(0, px(10)))
        left = tk.Frame(body, bg=ui.BG)
        left.pack(side="left", fill="y", anchor="n")
        right = tk.Frame(body, bg=ui.BG)
        right.pack(side="left", fill="both", expand=True, padx=(px(14), 0), anchor="n")

        # ---- left: pairing ----
        pair = ui.Card(left, "Pair a phone")
        pair.pack(fill="x")
        qr_tile = tk.Frame(pair, bg="white", padx=px(8), pady=px(8))
        qr_tile.pack()
        self.qr_label = tk.Label(qr_tile, bg="white")
        self.qr_label.pack()
        tk.Label(pair, text="Scan with the Fasway app or the phone camera", font=(ui.FONT, 9), fg=ui.MUTED,
                 bg=ui.PANEL).pack(pady=(px(10), px(8)))
        self.addr_var = tk.StringVar(value=self._address_choices()[0])
        self.addr_combo = ttk.Combobox(pair, textvariable=self.addr_var, values=self._address_choices(),
                                       state="readonly", width=34, font=(ui.FONT, 10))
        self.addr_combo.pack(fill="x")
        self.addr_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_qr())
        self.url_var = tk.StringVar()
        tk.Entry(pair, textvariable=self.url_var, state="readonly", font=(ui.MONO, 8), relief="flat",
                 readonlybackground=ui.PANEL2, fg=ui.MUTED, bd=px(6)).pack(fill="x", pady=(px(6), 0))
        self.hint_var = tk.StringVar()
        tk.Label(pair, textvariable=self.hint_var, font=(ui.FONT, 8), fg=ui.MUTED, bg=ui.PANEL,
                 wraplength=px(300), justify="center").pack(pady=(px(6), px(8)))
        btns = tk.Frame(pair, bg=ui.PANEL)
        btns.pack()
        self._copy_btn = ui.Button(btns, "Copy link", self.copy_link)
        self._copy_btn.pack(side="left", padx=px(4))
        ui.Button(btns, "New pairing code", self.new_token).pack(side="left", padx=px(4))

        # ---- right: files ----
        files = ui.Card(right, "Send files to your phone")
        files.pack(fill="x")
        self.drop_canvas = tk.Canvas(files, height=px(96), bg=ui.PANEL, highlightthickness=0)
        self.drop_canvas.pack(fill="x")
        self.drop_canvas.bind("<Configure>", lambda e: self._draw_drop())
        self._drop_flash = 0.0
        fb = tk.Frame(files, bg=ui.PANEL)
        fb.pack(fill="x", pady=(px(10), 0))
        ui.Button(fb, "Choose files…", self.pick_files, kind="primary").pack(side="left")
        ui.Button(fb, "Received files", lambda: open_folder(self.server.files.inbox)).pack(side="left", padx=px(8))
        self.files_var = tk.StringVar(value=f"Files from the phone are saved in {self.server.files.inbox}")
        tk.Label(files, textvariable=self.files_var, font=(ui.FONT, 8), fg=ui.MUTED, bg=ui.PANEL, anchor="w",
                 justify="left", wraplength=px(330)).pack(fill="x", pady=(px(8), 0))
        self._drop_ready = False
        root.after(300, self._enable_drop)

        # ---- right: phones ----
        phones = ui.Card(right, "Phones")
        phones.pack(fill="x", pady=(px(12), 0))
        self.phones_frame = tk.Frame(phones, bg=ui.PANEL)
        self.phones_frame.pack(fill="x")
        self._render_phones()

        # ---- right: settings ----
        sets = ui.Card(right, "Settings")
        sets.pack(fill="x", pady=(px(12), 0))
        self.autostart_toggle = ui.setting_row(
            sets, "Start with Windows" if sys.platform == "win32" else "Start at login",
            "Runs quietly in the tray" if sys.platform == "win32" else "Runs in the menu bar",
            self.autostart_on, lambda: self.events.put(("toggle_autostart", None)))
        if sys.platform == "win32":
            self.menu_toggle = ui.setting_row(
                sets, "“Send to phone” in Explorer", "Right-click any file (Windows 11: Show more options)",
                shellmenu.is_installed(), self._toggle_send_menu)
        # Windows blocks input to apps running as Administrator (Task Manager...) unless we are admin too
        if self.admin is not None:
            self.admin_toggle = ui.setting_row(
                sets, "Always run as administrator", "Needed to control apps like Task Manager",
                bool(self.cfg.get("always_admin")), lambda: self.events.put(("toggle_admin", None)))
            if self.admin:
                tk.Label(sets, text="🛡  Running as administrator", font=(ui.FONT, 9), fg=ui.OK, bg=ui.PANEL,
                         anchor="w").pack(fill="x", pady=(px(6), 0))
            else:
                row = tk.Frame(sets, bg=ui.PANEL)
                row.pack(fill="x", pady=(px(6), 0))
                tk.Label(row, text="Not running as administrator", font=(ui.FONT, 9), fg=ui.WARN,
                         bg=ui.PANEL).pack(side="left")
                ui.Button(row, "Restart as admin", self.restart_as_admin, small=True).pack(side="right")

        tk.Label(root, text=f"Fasway v{__version__}  ·  Closing this window keeps Fasway running in the tray.", font=(ui.FONT, 8),
                 fg=ui.MUTED, bg=ui.BG).pack(pady=(0, px(14)))

        self.refresh_qr()
        root.after(100, self._poll)
        root.after(10_000, self._watch_network)
        root.protocol("WM_DELETE_WINDOW", self.hide)

    # ---------- weak Wi-Fi ----------
    def _watch_wifi(self):
        from . import wifi
        while True:
            self.events.put(("wifi", wifi.signal_percent()))
            time.sleep(15)

    def _tell(self, key: str, msg: str, every: float = 300):
        """Tray notification at most every `every` seconds per subject."""
        now = time.monotonic()
        if now - self._weak_told.get(key, -1e9) >= every:
            self._weak_told[key] = now
            self.tray.notify(msg)

    def _phone_link(self, dev: str, name: str, weak: bool, rtt):
        if weak:
            self._weak_phones[dev] = name
            slow = f" ({rtt} ms)" if rtt and rtt < 3000 else ""
            self._tell(dev, f"📶 Weak Wi-Fi to {name}{slow}. Move the phone closer to the Wi-Fi router.")
        else:
            self._weak_phones.pop(dev, None)
        self._update_status()

    def _laptop_wifi(self, signal: int | None):
        self._laptop_signal = signal
        # weak below 40 %, good again from 55 % (no flapping around one value)
        weak = signal is not None and (signal < 55 if self._laptop_weak else signal < 40)
        if weak and not self._laptop_weak:
            msg = f"Laptop Wi-Fi signal is weak ({signal}%). Move the laptop closer to the router (or use a cable)."
            self._tell("laptop", "📶 " + msg)
            if self.phones:
                self.server.alert_phones("📶 " + msg)
        self._laptop_weak = weak
        self._update_status()

    def _update_status(self):
        if self._laptop_weak:
            self._set_status("Weak Wi-Fi", ui.WARN)
            self._set_wifi_warning(f"Weak Wi-Fi on this laptop ({self._laptop_signal}%): move it closer to the router "
                                   "or use a cable. The phone's controls may lag.")
        elif self._weak_phones and self.phones:
            names = ", ".join(self._weak_phones.values())
            self._set_status("Weak Wi-Fi", ui.WARN)
            self._set_wifi_warning(f"Weak Wi-Fi to {names}: move the phone closer to the Wi-Fi router.")
        else:
            n = self.phones
            self._set_status(f"{n} phone{'s' if n != 1 else ''} connected" if n else "Waiting for phone",
                             ui.OK if n else ui.WARN, pulsing=not n)
            self._set_wifi_warning(None)

    def _set_wifi_warning(self, text: str | None):
        if text:
            self.wifi_warn.configure(text="📶  " + text)
            if not self.wifi_warn.winfo_ismapped():
                self.wifi_warn.pack(fill="x", padx=int(22 * self.k), pady=(0, int(12 * self.k)), before=self._body)
        elif self.wifi_warn.winfo_ismapped():
            self.wifi_warn.pack_forget()

    def _set_status(self, text: str, color: str, pulsing: bool = False):
        self.status_var.set(text)
        self.status_dot.set(color, pulsing)

    def _draw_drop(self):
        """Dashed drop zone; flashes blue when files are dropped."""
        c, k = self.drop_canvas, self.k
        w, h = c.winfo_width(), c.winfo_height()
        f = self._drop_flash
        c.delete("all")
        m = int(2 * k)
        fill = ui._mix(ui.PANEL, ui.ACCENT, 0.06 + 0.25 * f)
        c.create_rectangle(m, m, w - m - 1, h - m - 1, outline=ui._mix(ui.BORDER, ui.ACCENT, 0.5 + 0.5 * f),
                           dash=(6, 4), width=max(1, int(1.5 * k)), fill=fill)
        drop = sys.platform == "win32"
        c.create_text(w / 2, h / 2 - 10 * k, text="⇩  Drop files or folders here" if drop else "Send files",
                      fill=ui.TEXT, font=(ui.FONT, 11, "bold"))
        c.create_text(w / 2, h / 2 + 13 * k, text="anywhere on this window · they land in the phone's Downloads/Fasway",
                      fill=ui.MUTED, font=(ui.FONT, 8))

    def _flash_drop(self, v: float = 1.0):
        self._drop_flash = v
        self._draw_drop()
        if v > 0:
            self.root.after(30, lambda: self._flash_drop(max(0.0, v - 0.08)))

    def _toggle_send_menu(self):
        on = not shellmenu.is_installed()
        ok = shellmenu.install(DATA) if on else shellmenu.uninstall()
        self.cfg["send_menu"] = on
        save_config(self.cfg)
        self.menu_toggle.set(shellmenu.is_installed())
        if on and ok:
            self.files_var.set("Right-click a file in Explorer → “Send to phone (Fasway)”.")

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
        if not self.phones:   # sent as soon as a phone connects (within a few minutes)
            self._pending_send = files
            self.root.after(180_000, lambda f=files: self._pending_send is f and self._drop_pending())
            what = files[0].name if len(files) == 1 else f"{len(files)} files"
            self.files_var.set(f"Waiting for your phone: {what} will be sent when Fasway opens on it.")
            self.tray.notify(f"Open Fasway on your phone to receive {what}.")
            return
        n = self.server.offer_files(files)
        what = files[0].name if n == 1 else f"{n} files"
        self.files_var.set(f"📤 Sending {what} to your phone (saved in its Downloads/Fasway)")

    def _drop_pending(self):
        self._pending_send = []
        self.files_var.set("No phone connected: the files were not sent.")

    def _send_menu_batch(self):
        self._menu_flush = None
        batch, self._menu_batch = self._menu_batch, []
        self.send_files(batch)
        if self.phones:
            what = Path(batch[0]).name if len(batch) == 1 else f"{len(batch)} items"
            self.tray.notify(f"📤 Sending {what} to your phone")

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
        if not devices:
            tk.Label(f, text="No phones yet. Scan the QR code with your phone; you approve it here once.",
                     font=(ui.FONT, 9), fg=ui.MUTED, bg=ui.PANEL, anchor="w", justify="left",
                     wraplength=int(330 * self.k)).pack(fill="x")
        for d in devices:
            on = d["id"] in online
            row = tk.Frame(f, bg=ui.PANEL2, padx=int(10 * self.k), pady=int(7 * self.k))
            row.pack(fill="x", pady=int(3 * self.k))
            tk.Label(row, text="📱", font=(ui.FONT, 14), fg=ui.TEXT, bg=ui.PANEL2).pack(side="left")
            text = tk.Frame(row, bg=ui.PANEL2)
            text.pack(side="left", padx=int(8 * self.k), fill="x", expand=True)
            tk.Label(text, text=d["name"], font=(ui.FONT, 10, "bold"), fg=ui.TEXT, bg=ui.PANEL2,
                     anchor="w").pack(fill="x")
            tk.Label(text, text="● Connected" if on else f"Last seen {self._ago(d.get('last_seen', 0))}",
                     font=(ui.FONT, 8), fg=ui.OK if on else ui.MUTED, bg=ui.PANEL2, anchor="w").pack(fill="x")
            ui.Button(row, "Remove", lambda d=d: self._remove_phone(d), kind="danger", small=True).pack(side="right")

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
        win.configure(bg=ui.PANEL, padx=int(8 * self.k))
        win.resizable(False, False)
        ui.dark_title_bar(win)
        win.attributes("-topmost", True)
        done = {"v": False}

        def reply(ok: bool):
            if not done["v"]:
                done["v"] = True
                answer(ok)
                win.destroy()

        k = self.k
        tk.Label(win, text="📱", font=(ui.FONT, 30), fg=ui.TEXT, bg=ui.PANEL).pack(pady=(int(18 * k), 0))
        tk.Label(win, text="A phone wants to connect", font=(ui.FONT, 14, "bold"), fg=ui.TEXT,
                 bg=ui.PANEL).pack(padx=int(24 * k), pady=(int(4 * k), int(6 * k)))
        tk.Label(win, text=name, font=(ui.FONT, 11, "bold"), fg=ui.ACCENT, bg=ui.PANEL).pack()
        tk.Label(win, text=f"from {ip}", font=(ui.FONT, 9), fg=ui.MUTED, bg=ui.PANEL).pack()
        tk.Label(win, text="Only allow phones you own: it will be able to control this laptop.",
                 font=(ui.FONT, 9), fg=ui.WARN, bg=ui.PANEL, wraplength=int(300 * k),
                 justify="center").pack(padx=int(24 * k), pady=(int(12 * k), int(8 * k)))
        b = tk.Frame(win, bg=ui.PANEL)
        b.pack(pady=(int(4 * k), int(20 * k)))
        ui.Button(b, "Deny", lambda: reply(False)).pack(side="left", padx=int(6 * k))
        allow = ui.Button(b, "Allow", lambda: reply(True), kind="primary")
        allow.pack(side="left", padx=int(6 * k))
        win.bind("<Return>", lambda e: reply(True))
        win.bind("<Escape>", lambda e: reply(False))
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
                    self._update_status()
                    if val and self._pending_send:   # files picked in Explorer before a phone was connected
                        files, self._pending_send = self._pending_send, []
                        self.send_files(files)
                    self.tray.set_connected(val)
                    self._render_phones()
                elif kind == "devices":
                    self._render_phones()
                elif kind == "pair":
                    self._ask_pair(*val)
                elif kind == "status":
                    if val == "running":
                        self._update_status()
                    else:
                        self._set_status(val, ui.BAD)
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
                    self.autostart_toggle.set(val)
                    self.tray.refresh()
                elif kind == "toggle_admin":
                    self._toggle_admin()
                elif kind == "send_files":
                    self._flash_drop()
                    self.send_files(val)
                elif kind == "send_menu":   # Explorer: one event per selected item; send them as one batch
                    self._menu_batch += val
                    if not self._menu_flush:
                        self._menu_flush = self.root.after(500, self._send_menu_batch)
                elif kind == "file_received":
                    self._file_received(*val)
                elif kind == "link":
                    self._phone_link(*val)
                elif kind == "wifi":
                    self._laptop_wifi(val)
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
        if hasattr(self, "admin_toggle"):
            self.admin_toggle.set(on)
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
            self._set_status("Admin restart cancelled", ui.WARN)

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
    send = send_args()
    background = "--background" in sys.argv or bool(send)
    setup_logging()
    lock = acquire_instance(takeover="--takeover" in sys.argv)
    if lock is None:                       # Fasway is already running
        if send:
            signal_running_instance(b"send\n" + "\n".join(send).encode("utf-8"))   # it sends them
        elif not background:
            signal_running_instance()      # ... so just bring up its window
        return
    cfg = load_config()
    if is_admin() is False and "--no-elevate" not in sys.argv and cfg.get("always_admin"):
        lock.close()
        if relaunch_as_admin(background, send):
            return   # the elevated copy runs Fasway; if the UAC prompt is declined we carry on normally
        lock = acquire_instance(takeover=True)
        if lock is None:
            return
    log.info("Fasway %s starting (%s%s)", __version__, "background" if background else "window",
             ", administrator" if is_admin() else "")
    App(background, lock, pending_send=send).run()


if __name__ == "__main__":
    main()
