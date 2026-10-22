"""Explorer right-click menu: "Send to phone (Fasway)" on files and folders (Windows, per user, no admin).

Each selected item starts `Fasway --send <path>`; that copy hands the path to the running Fasway over
its local control port and exits at once, and the running Fasway sends the batch to the phone.
On Windows 11 the entry is under "Show more options" (Shift+F10), like other classic menu entries.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import autostart

LABEL = "Send to phone (Fasway)"
_KEYS = (r"Software\Classes\*\shell\FaswaySendToPhone", r"Software\Classes\Directory\shell\FaswaySendToPhone")


def _quote(a: str) -> str:
    return f'"{a}"' if (" " in a or not a) else a


def command() -> str:
    prog, _args, _cwd = autostart.launch_command()
    if getattr(sys, "frozen", False):
        return f'{_quote(prog)} --send "%1"'
    # running from source: Explorer starts us in the file's folder, so put the project on the path
    root = str(autostart.ROOT).replace("'", "\\'")
    code = f"import sys;sys.path.insert(0,r'{root}');from fasway.main import main;main()"
    return f'{_quote(prog)} -c "{code}" --send "%1"'


def _icon(data_dir: Path) -> str:
    if getattr(sys, "frozen", False):
        return f"{sys.executable},0"
    from .tray import _icon_image   # same icon as the tray
    ico = data_dir / "fasway.ico"
    if not ico.exists():
        _icon_image(False).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
    return str(ico)


def install(data_dir: Path) -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        cmd, icon = command(), _icon(data_dir)
        for key in _KEYS:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
                winreg.SetValueEx(k, None, 0, winreg.REG_SZ, LABEL)
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
                winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")  # also for many files
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
                winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)
        return True
    except OSError:
        return False


def uninstall() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    for key in _KEYS:
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
    return not is_installed()


def is_installed() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEYS[0] + r"\command"):
            return True
    except OSError:
        return False
