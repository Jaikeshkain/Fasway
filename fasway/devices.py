"""Trusted phones. A phone proves who it is with its own random key; only a SHA-256 of that key is
stored (data/devices.json). The QR pairing link alone is not enough: a new phone must be approved
on the laptop first."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from pathlib import Path


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class DeviceStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "devices.json"
        self._lock = threading.Lock()
        self.devices: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {d["id"]: d for d in data if isinstance(d, dict) and "id" in d and "key_hash" in d}
        except (OSError, ValueError, KeyError):
            return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(list(self.devices.values()), ensure_ascii=False, indent=2), encoding="utf-8")

    def verify(self, dev_id: str, key: str) -> bool:
        d = self.devices.get(dev_id)
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
