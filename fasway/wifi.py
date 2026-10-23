"""The laptop's own Wi-Fi signal, to warn when it is weak (Windows: netsh; elsewhere: unknown)."""
from __future__ import annotations

import re
import subprocess
import sys


def signal_percent() -> int | None:
    """Signal quality of the connected Wi-Fi in %, or None (not on Wi-Fi, cable, or unknown)."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=5,
                             creationflags=0x08000000).stdout.decode("utf-8", "replace")   # no console window
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^\s*Signal\s*:\s*(\d+)\s*%", out, re.M)
    return int(m.group(1)) if m else None
