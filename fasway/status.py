"""Laptop status (battery, CPU, RAM) and alerts for low battery / charging, via psutil (Windows + macOS)."""
from __future__ import annotations

import time

import psutil

psutil.cpu_percent(None)  # prime: the first reading is always 0

LOW_BATTERY = (20, 10)    # warn when crossing these levels while unplugged


def get_status() -> dict:
    vm = psutil.virtual_memory()
    st = {"cpu": round(psutil.cpu_percent(None)), "ram": round(vm.percent),
          "ram_used": round(vm.used / 2**30, 1), "ram_total": round(vm.total / 2**30, 1),
          "uptime": int(time.time() - psutil.boot_time()),
          "battery": None, "plugged": None, "secsleft": None}
    b = psutil.sensors_battery()
    if b is not None:   # desktops have no battery
        st.update(battery=round(b.percent), plugged=bool(b.power_plugged),
                  secsleft=int(b.secsleft) if isinstance(b.secsleft, (int, float)) and b.secsleft > 0 else None)
    return st


class BatteryAlerts:
    """Turns successive status readings into one-off alert messages."""

    def __init__(self):
        self.prev: dict | None = None
        self.warned: set[int] = set()

    def check(self, st: dict) -> list[str]:
        out = []
        prev, self.prev = self.prev, st
        if st["battery"] is None or prev is None or prev["battery"] is None:
            return out
        pct, plugged = st["battery"], st["plugged"]
        if plugged != prev["plugged"]:
            out.append(f"🔌 Charger connected ({pct}%)" if plugged else f"🔋 Charger unplugged ({pct}%)")
            self.warned.clear()
        if not plugged:
            for level in LOW_BATTERY:
                if pct <= level and level not in self.warned:
                    self.warned.add(level)
                    out.append(f"🪫 Laptop battery low: {pct}%")
                    break
        elif pct >= 100 and prev["battery"] < 100:
            out.append("✅ Laptop fully charged")
        return out
