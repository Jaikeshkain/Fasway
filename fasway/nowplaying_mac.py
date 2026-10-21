"""Now Playing on macOS for Spotify and Apple Music (via AppleScript; macOS has no public API for
other apps' media). Artwork comes as a URL for Spotify."""
from __future__ import annotations

import asyncio
import subprocess

_APPS = (("Spotify", "spotify"), ("Music", "music"))


def _osa(script: str) -> str:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=4).stdout.strip()


def _running(app: str) -> bool:
    return _osa(f'application "{app}" is running') == "true"


def _state_sync() -> dict:
    sessions = []
    for app, kind in _APPS:
        if not _running(app):
            continue
        dur = "(duration of current track) / 1000" if kind == "spotify" else "duration of current track"
        art = "artwork url of current track" if kind == "spotify" else '""'
        out = _osa(f'''tell application "{app}"
            if player state is stopped then return ""
            return (name of current track) & "\\n" & (artist of current track) & "\\n" & (album of current track) ¬
              & "\\n" & (player state as text) & "\\n" & (player position as text) & "\\n" & ({dur} as text) & "\\n" & {art}
        end tell''')
        parts = out.split("\n")
        if len(parts) < 7:
            continue
        num = lambda s: float(s.replace(",", ".") or 0)  # noqa: E731  (locale decimal comma)
        sessions.append({"id": app, "app": app, "title": parts[0], "artist": parts[1], "album": parts[2],
                         "status": "playing" if parts[3] == "playing" else "paused",
                         "pos": round(num(parts[4]), 1), "dur": round(num(parts[5]), 1),
                         "art": None, "art_url": parts[6] or None,
                         "can_seek": True, "can_next": True, "can_prev": True})
    current = next((s["id"] for s in sessions if s["status"] == "playing"), sessions[0]["id"] if sessions else None)
    return {"sessions": sessions, "current": current, "art": {}}


async def get_state(have_art: set[str]) -> dict:
    return await asyncio.to_thread(_state_sync)


async def command(session_id: str | None, action: str, pos: float | None = None) -> bool:
    app = session_id if session_id in ("Spotify", "Music") else None
    if app is None:
        return False
    verb = {"play_pause": "playpause", "next": "next track", "prev": "previous track"}.get(action)
    if action == "seek" and pos is not None:
        verb = f"set player position to {max(0.0, pos)}"
    if not verb:
        return False
    await asyncio.to_thread(_osa, f'tell application "{app}" to {verb}')
    return True
