"""Now Playing on Windows via System Media Transport Controls (the media panel in the volume flyout).
Works with Spotify, YouTube/Netflix in Chrome & Edge, VLC, the Media Player app, etc."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import logging

from PIL import Image

log = logging.getLogger("fasway")
_mgr = None
_art_cache: dict[str, str] = {}   # art key -> base64 JPEG

_PRETTY = {"spotify": "Spotify", "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "vlc": "VLC",
           "zunemusic": "Media Player", "microsoft.zunemusic": "Media Player", "brave": "Brave",
           "opera": "Opera", "applemusic": "Apple Music", "itunes": "iTunes", "wmplayer": "Media Player"}
_STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}


def _app_name(aumid: str) -> str:
    """'Spotify.exe' / 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' / 'MSEdge' -> 'Spotify' / 'Edge'."""
    s = aumid.split("!")[-1] if "!" in aumid else aumid
    s = s.rsplit("\\", 1)[-1].removesuffix(".exe").removesuffix(".EXE")
    key = s.lower().split("_")[0]
    for k, v in _PRETTY.items():
        if k in key:
            return v
    return s[:24] or "App"


async def _manager():
    global _mgr
    if _mgr is None:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
        _mgr = await M.request_async()
    return _mgr


async def _art(props, key: str) -> str | None:
    if key in _art_cache:
        return _art_cache[key]
    _art_cache[key] = ""
    try:
        if props.thumbnail:
            from winrt.windows.storage.streams import Buffer, InputStreamOptions
            stream = await props.thumbnail.open_read_async()
            buf = Buffer(stream.size)
            await stream.read_async(buf, stream.size, InputStreamOptions.READ_AHEAD)
            im = Image.open(io.BytesIO(bytes(buf))).convert("RGB")
            im.thumbnail((320, 320))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=82)
            _art_cache[key] = base64.b64encode(out.getvalue()).decode()
    except Exception as e:
        log.debug("artwork failed: %s", e)
    if len(_art_cache) > 40:
        _art_cache.pop(next(iter(_art_cache)))
    return _art_cache[key] or None


def _secs(td) -> float:
    return td.total_seconds() if isinstance(td, dt.timedelta) else 0.0


async def get_state(have_art: set[str]) -> dict:
    mgr = await _manager()
    cur = mgr.get_current_session()
    cur_id = cur.source_app_user_model_id if cur else None
    sessions, art = [], {}
    for s in mgr.get_sessions():
        try:
            props = await s.try_get_media_properties_async()
            info = s.get_playback_info()
            tl = s.get_timeline_properties()
        except Exception:
            continue
        status = _STATUS.get(int(info.playback_status), "stopped")
        pos, end = _secs(tl.position), _secs(tl.end_time)
        if status == "playing" and end > 0:
            # apps only report the position now and then: add the time since that report
            try:
                pos += (dt.datetime.now(dt.timezone.utc) - tl.last_updated_time).total_seconds()
            except Exception:
                pass
        pos = max(0.0, min(pos, end)) if end > 0 else 0.0
        key = hashlib.sha1(f"{s.source_app_user_model_id}|{props.title}|{props.artist}".encode()).hexdigest()[:12]
        b64 = await _art(props, key)
        if b64 and key not in have_art:
            art[key] = b64
        c = info.controls
        sessions.append({
            "id": s.source_app_user_model_id, "app": _app_name(s.source_app_user_model_id),
            "title": props.title or "", "artist": props.artist or props.album_artist or "",
            "album": props.album_title or "", "status": status, "pos": round(pos, 1), "dur": round(end, 1),
            "art": key if b64 else None, "can_seek": bool(c.is_playback_position_enabled) and end > 0,
            "can_next": bool(c.is_next_enabled), "can_prev": bool(c.is_previous_enabled),
        })
    return {"sessions": sessions, "current": cur_id, "art": art}


async def command(session_id: str | None, action: str, pos: float | None = None) -> bool:
    mgr = await _manager()
    target = next((s for s in mgr.get_sessions() if s.source_app_user_model_id == session_id), None) \
        or mgr.get_current_session()
    if target is None:
        return False
    if action == "play_pause":
        return bool(await target.try_toggle_play_pause_async())
    if action == "next":
        return bool(await target.try_skip_next_async())
    if action == "prev":
        return bool(await target.try_skip_previous_async())
    if action == "seek" and pos is not None:
        return bool(await target.try_change_playback_position_async(int(max(0.0, pos) * 10_000_000)))  # 100 ns ticks
    return False
