"""Explorer's "Send to phone (Fasway)": hands the paths to the running Fasway straight away.

Loading the whole app (screen sharing, audio, the UI) took about 1.6 s on every right-click just to pass
a path along, so this module imports nothing from Fasway. Only when Fasway isn't running does the full
app start, to send the files once a phone connects.
"""
from __future__ import annotations

import os
import socket
import sys

# localhost only: keeps Fasway single-instance and lets a 2nd launch open the window (env override for tests)
CONTROL_PORT = int(os.environ.get("FASWAY_CONTROL_PORT", "47391"))


def signal_running_instance(msg: bytes = b"show\n") -> bool:
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=2) as c:
            c.sendall(msg)
        return True
    except OSError:
        return False


def send_args() -> list[str]:
    """Paths after --send."""
    if "--send" not in sys.argv:
        return []
    return [a for a in sys.argv[sys.argv.index("--send") + 1:] if not a.startswith("--")]


def main():
    paths = send_args()
    if paths and signal_running_instance(b"send\n" + "\n".join(paths).encode("utf-8")):
        return
    from .main import main as full   # not running: start Fasway, which sends them when a phone connects
    full()
