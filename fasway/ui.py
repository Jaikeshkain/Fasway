"""Look of the laptop window: the phone app's dark colours, flat buttons, toggle switches and cards (Tk)."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

FONT = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
MONO = "Menlo" if sys.platform == "darwin" else "Consolas"

BG = "#111318"
PANEL = "#1b1e25"
PANEL2 = "#242833"
BORDER = "#2a2f3a"
TEXT = "#e8eaf0"
MUTED = "#8b90a0"
ACCENT = "#4f8cff"
OK = "#2ecc71"
WARN = "#f5b041"
BAD = "#ff5c5c"


def scale(widget) -> float:
    """Pixels per 96-dpi pixel (Fasway is DPI aware: on a 150 % screen this is 1.5)."""
    try:
        return max(1.0, widget.winfo_fpixels("1i") / 96)
    except tk.TclError:
        return 1.0


def _mix(a: str, b: str, t: float) -> str:
    a_, b_ = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a_, b_))


def dark_title_bar(win):
    """Windows 10/11: dark title bar to match the window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (20; 19 on older Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except Exception:
        pass


def style_ttk(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=TEXT, arrowcolor=TEXT,
                bordercolor=BORDER, lightcolor=PANEL2, darkcolor=PANEL2, selectbackground=PANEL2,
                selectforeground=TEXT, padding=5)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", TEXT)],
          background=[("active", BORDER)])
    root.option_add("*TCombobox*Listbox.background", PANEL2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))


class Button(tk.Label):
    """Flat button: hover lightens, press darkens, click fires on release (like a real button)."""
    KINDS = {   # bg, hover, press, fg
        "primary": (ACCENT, "#6a9dff", "#3f7aeb", "#ffffff"),
        "secondary": (PANEL2, "#2f3442", "#20242d", TEXT),
        "danger": (PANEL2, "#3a1f24", "#2c171b", BAD),
    }

    def __init__(self, parent, text: str, command, kind: str = "secondary", small: bool = False):
        self.colors = self.KINDS[kind]
        super().__init__(parent, text=text, bg=self.colors[0], fg=self.colors[3], cursor="hand2",
                         font=(FONT, 9 if small else 10, "bold"), padx=10 if small else 14, pady=3 if small else 7)
        self.command = command
        self._inside = False
        self.bind("<Enter>", lambda e: self._paint(1, inside=True))
        self.bind("<Leave>", lambda e: self._paint(0, inside=False))
        self.bind("<ButtonPress-1>", lambda e: self._paint(2))
        self.bind("<ButtonRelease-1>", self._release)

    def _paint(self, i: int, inside: bool | None = None):
        if inside is not None:
            self._inside = inside
        self.configure(bg=self.colors[i])

    def _release(self, _e):
        self._paint(1 if self._inside else 0)
        if self._inside and self.command:
            self.command()


class Toggle(tk.Canvas):
    """On/off switch that slides."""

    def __init__(self, parent, value: bool, command, bg: str = PANEL):
        self.k = scale(parent)
        w, h = int(40 * self.k), int(22 * self.k)
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, cursor="hand2")
        self.w, self.h = w, h
        self.value = bool(value)
        self._pos = 1.0 if self.value else 0.0
        self.command = command
        self.bind("<Button-1>", lambda e: self.command())
        self._draw()

    def set(self, value: bool):
        value = bool(value)
        if value != self.value:
            self.value = value
            self._animate()

    def _animate(self):
        target = 1.0 if self.value else 0.0
        self._pos += (target - self._pos) * 0.45
        if abs(target - self._pos) < 0.03:
            self._pos = target
        self._draw()
        if self._pos != target:
            self.after(12, self._animate)

    def _draw(self):
        self.delete("all")
        w, h, p = self.w, self.h, self._pos
        c = _mix("#3a3f4b", ACCENT, p)
        r = h / 2
        self.create_oval(0, 0, h, h, fill=c, outline=c)
        self.create_oval(w - h, 0, w, h, fill=c, outline=c)
        self.create_rectangle(r, 0, w - r, h, fill=c, outline=c)
        m = 3 * self.k
        x = m + (w - h) * p
        self.create_oval(x, m, x + h - 2 * m, h - m, fill="#ffffff", outline="")


class Card(tk.Frame):
    """Panel with an optional small caps title."""

    def __init__(self, parent, title: str | None = None, **kw):
        k = scale(parent)
        super().__init__(parent, bg=PANEL, padx=int(16 * k), pady=int(14 * k),
                         highlightbackground=BORDER, highlightthickness=1, **kw)
        if title:
            tk.Label(self, text=title.upper(), font=(FONT, 8, "bold"), fg=MUTED, bg=PANEL,
                     anchor="w").pack(fill="x", pady=(0, int(8 * k)))


def setting_row(parent, title: str, subtitle: str | None, value: bool, command) -> Toggle:
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=4)
    t = Toggle(row, value, command)
    t.pack(side="right", padx=(10, 0))
    text = tk.Frame(row, bg=PANEL)
    text.pack(side="left", fill="x", expand=True)
    tk.Label(text, text=title, font=(FONT, 10), fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
    if subtitle:
        tk.Label(text, text=subtitle, font=(FONT, 8), fg=MUTED, bg=PANEL, anchor="w", justify="left",
                 wraplength=int(250 * scale(parent))).pack(fill="x")
    return t


class Dot(tk.Canvas):
    """Status dot that can pulse."""

    def __init__(self, parent, bg: str):
        self.k = scale(parent)
        s = int(12 * self.k)
        super().__init__(parent, width=s, height=s, bg=bg, highlightthickness=0)
        self.s, self.color, self.pulsing, self._t = s, MUTED, False, 0.0
        self._tick()

    def set(self, color: str, pulsing: bool):
        self.color, self.pulsing = color, pulsing

    def _tick(self):
        import math
        self._t += 0.12
        a = (math.sin(self._t) + 1) / 2 if self.pulsing else 1.0
        bg = self.cget("bg")
        self.delete("all")
        s, m = self.s, 2 * self.k
        self.create_oval(m, m, s - m, s - m, fill=_mix(bg, self.color, 0.35 + 0.65 * a), outline="")
        self.after(60, self._tick)
