"""Trusted phones. A phone proves who it is with its own random key; only a SHA-256 of that key is
stored (data/devices.json). The QR pairing link alone is not enough: a new phone must be approved
on the laptop first. A phone that hasn't connected for EXPIRE_DAYS is forgotten (a sold or lost phone
stops working by itself) and has to be approved again."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from pathlib import Path

EXPIRE_DAYS = 90


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class DeviceStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "devices.json"
        self._lock = threading.Lock()
        self.devices: dict[str, dict] = self._load()
        self.forgotten = self.forget_expired()   # names of phones dropped at start-up, for the log

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {d["id"]: d for d in data if isinstance(d, dict) and "id" in d and "key_hash" in d}
        except (OSError, ValueError, KeyError):
            return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(list(self.devices.values()), ensure_ascii=False, indent=2), encoding="utf-8")

    def expired(self, d: dict, now: float | None = None) -> bool:
        seen = d.get("last_seen") or d.get("added") or 0
        return (now or time.time()) - seen > EXPIRE_DAYS * 86400

    def forget_expired(self) -> list[str]:
        """Remove phones not seen for EXPIRE_DAYS; returns their names."""
        with self._lock:
            old = [i for i, d in self.devices.items() if self.expired(d)]
            names = [self.devices.pop(i).get("name", "Phone") for i in old]
            if old:
                self._save()
        return names

    def verify(self, dev_id: str, key: str) -> bool:
        d = self.devices.get(dev_id)
        if d and self.expired(d):
            self.forget_expired()
            return False
        return bool(d and key and hmac.compare_digest(d["key_hash"], _digest(key)))

    def add(self, dev_id: str, key: str, name: str):
        with self._lock:
            now = int(time.time())
            self.devices[dev_id] = {"id": dev_id, "name": name[:60] or "Phone", "key_hash": _digest(key),
                                    "added": now, "last_seen": now}
            self._save()

    def touch(self, dev_id: str, name: str | None = None):
        with self._lock:
            d = self.devices.get(dev_id)
            if d:
                d["last_seen"] = int(time.time())
                if name:
                    d["name"] = name[:60]
                self._save()

    def remove(self, dev_id: str):
        with self._lock:
            if self.devices.pop(dev_id, None) is not None:
                self._save()

    def listing(self) -> list[dict]:
        """Without key hashes, newest activity first (for the laptop window)."""
        return sorted(({k: v for k, v in d.items() if k != "key_hash"} for d in self.devices.values()),
                      key=lambda d: -d.get("last_seen", 0))
