"""File sharing between the phone and the laptop.

Phone -> laptop: the phone uploads over HTTPS (authenticated with its own key); files land in
Downloads/Fasway. Laptop -> phone: files dropped on the Fasway window are *offered* to the connected
phones, which download them by an unguessable id that stays valid for a while.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

OFFER_TTL = 3600  # seconds a phone can still download an offered file


def downloads_dir() -> Path:
    """The user's Downloads folder (also when it was moved to another drive)."""
    if sys.platform == "win32":
        try:
            import ctypes
            folder_id = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B")  # FOLDERID_Downloads
            guid = (ctypes.c_byte * 16).from_buffer_copy(folder_id.bytes_le)
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except Exception:
            pass
    return Path.home() / "Downloads"


def safe_name(name: str) -> str:
    """A file name from the phone, made safe for Windows and macOS (no folders, no reserved names)."""
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        name = "file"
    if Path(name).stem.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                   *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name[:180]


def unique_path(folder: Path, name: str) -> Path:
    """folder/name, or "name (2).ext", "name (3).ext"… if that already exists."""
    path = folder / name
    stem, ext = Path(name).stem, Path(name).suffix
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}){ext}"
        n += 1
    return path


def open_folder(path: Path, select: Path | None = None):
    """Show a folder (and highlight a file in it) in Explorer / Finder."""
    try:
        if sys.platform == "win32":
            if select is not None and select.exists():
                subprocess.Popen(["explorer", "/select,", str(select)])
            else:
                os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(select)] if select is not None else ["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass


class FileShare:
    def __init__(self, inbox: Path | None = None):
        self.inbox = inbox or downloads_dir() / "Fasway"
        self._offers: dict[str, dict] = {}

    def offer(self, paths: list[str | Path]) -> list[dict]:
        """Make files downloadable for the phones; returns what to announce to them."""
        now = time.time()
        self._offers = {k: o for k, o in self._offers.items() if now - o["at"] < OFFER_TTL}
        out = []
        for p in paths:
            p = Path(p)
            if not p.is_file():   # folders are skipped (send their files instead)
                continue
            fid = secrets.token_urlsafe(18)
            self._offers[fid] = {"path": p, "at": now}
            out.append({"id": fid, "name": p.name, "size": p.stat().st_size})
        return out

    def offered(self, fid: str) -> Path | None:
        o = self._offers.get(fid)
        if o is None or time.time() - o["at"] > OFFER_TTL or not o["path"].is_file():
            return None
        return o["path"]

    def new_upload(self) -> Path:
        """Temporary file for an upload in progress (renamed by finish_upload when complete)."""
        self.inbox.mkdir(parents=True, exist_ok=True)
        return self.inbox / f".fasway-{secrets.token_hex(6)}.part"

    def finish_upload(self, part: Path, name: str) -> Path:
        # the final name is picked only now: two phones sending "photo.jpg" at once get both files
        final = unique_path(self.inbox, safe_name(name))
        os.rename(part, final)
        return final
