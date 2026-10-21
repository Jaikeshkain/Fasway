"""Picks the input backend for the current OS."""
import sys

if sys.platform == "darwin":
    from . import input_mac as inp
    from . import system_mac as sysctl
    from . import nowplaying_mac as nowplaying
elif sys.platform == "win32":
    from . import input_win as inp
    from . import system_win as sysctl
    from . import nowplaying_win as nowplaying
    inp.enable_dpi_awareness()  # before any window or capture, so coordinates are real pixels
    inp.enable_precise_timers()
else:
    raise SystemExit("Fasway currently supports Windows and macOS only.")


def permission_problem():
    check = getattr(inp, "permission_problem", None)
    return check() if check else None


def screen_permission_problem():
    check = getattr(inp, "screen_permission_problem", None)
    return check() if check else None
