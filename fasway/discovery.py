"""Stable phone link: announce this laptop on the local network as fasway-<id>.local (mDNS / Bonjour).

The name comes from a random id created once per install, so it never depends on the computer's name
(two laptops can share one) or its IP address (changes between networks). Phones open
https://fasway-<id>.local:<port>/ and the same bookmark keeps working on any Wi-Fi.
"""
from __future__ import annotations

import logging
import secrets
import socket
import string
import threading

from zeroconf import IPVersion, ServiceInfo, Zeroconf

log = logging.getLogger("fasway")
SERVICE = "_fasway._tcp.local."   # also lets a future native app find laptops by browsing this service


def new_device_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(5))


class Announcer:
    def __init__(self, device_id: str, port: int, label: str):
        self.device_id = device_id
        self.hostname = f"fasway-{device_id}.local"
        self.port = port
        self.label = label
        self._zc: Zeroconf | None = None
        self._info: ServiceInfo | None = None
        self._ips: list[str] = []
        self._lock = threading.Lock()   # updates run on background threads

    def _make_info(self, ips: list[str]) -> ServiceInfo:
        return ServiceInfo(SERVICE, f"{self.label}.{SERVICE}",
                           addresses=[socket.inet_aton(ip) for ip in ips], port=self.port,
                           server=self.hostname + ".",
                           properties={"host": self.hostname, "id": self.device_id, "v": "1"})

    def update(self, ips: list[str]):
        """(Re)announce with these addresses. Only reachable ones should be passed: phones try them in order."""
        with self._lock:
            self._update(ips)

    def _update(self, ips: list[str]):
        ips = [ip for ip in dict.fromkeys(ips) if ip and not ip.startswith("127.")]
        if not ips or ips == self._ips:
            return
        try:
            if self._zc is None:
                self._zc = Zeroconf(ip_version=IPVersion.V4Only)
                self._info = self._make_info(ips)
                self._zc.register_service(self._info, allow_name_change=True)
            else:
                self._info = self._make_info(ips)
                self._zc.update_service(self._info)
            self._ips = ips
            log.info("announcing %s -> %s", self.hostname, ", ".join(ips))
        except Exception as e:   # mDNS port blocked etc.: the IP links still work
            log.warning("could not announce %s: %s", self.hostname, e)

    def close(self):
        with self._lock:
            self._close()

    def _close(self):
        if self._zc:
            try:
                if self._info:
                    self._zc.unregister_service(self._info)
                self._zc.close()
            except Exception:
                pass
            self._zc = None
