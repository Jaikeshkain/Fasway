"""Wake-on-LAN: the phone wakes a sleeping laptop with a "magic packet" (sent on the Wi-Fi to the laptop's
network card address). The laptop only has to tell the phone that address, and the network's broadcast
address, while it is awake (in the hello message)."""
from __future__ import annotations

import ipaddress
import socket


def adapter_for(local_ip: str) -> dict | None:
    """{"mac": "aa:bb:cc:dd:ee:ff", "bcast": "192.168.1.255"} for the network card that has `local_ip`."""
    try:
        import psutil
        cards = psutil.net_if_addrs()
        link = getattr(psutil, "AF_LINK", -1)
    except Exception:
        return None
    for addrs in cards.values():
        v4 = next((a for a in addrs if a.family == socket.AF_INET and a.address == local_ip), None)
        if not v4:
            continue
        mac = next((a.address for a in addrs if a.family == link), "")
        mac = mac.replace("-", ":").lower()
        if len(mac) != 17 or mac == "00:00:00:00:00:00":
            return None
        bcast = ""
        if v4.netmask:
            try:
                bcast = str(ipaddress.IPv4Network(f"{local_ip}/{v4.netmask}", strict=False).broadcast_address)
            except ValueError:
                pass
        return {"mac": mac, "bcast": bcast}
    return None
