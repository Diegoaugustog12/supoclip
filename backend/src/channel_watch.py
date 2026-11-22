"""Automations: follow YouTube, Twitch and Kick channels and queue their new videos for the user's approval.

A worker cron (``check_channel_watches``) asks every due channel for its newest uploads, streams
and past broadcasts. Videos that were already there when the channel was added are stored as ``baseline`` so
they are never offered. Every later video becomes a ``pending`` discovery. Nothing is clipped,
queued or posted until the user approves a discovery, which creates a normal task.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .utils.async_helpers import run_in_thread

logger = logging.getLogger(__name__)

MAX_WATCHES_PER_USER = 30
MAX_STREAMERS_PER_USER = 20
MAX_PENDING_PER_WATCH = 30
CHECK_INTERVAL_MINUTES = 10
DUE_BATCH = 25
LATEST_PER_TAB = 6
CHANNEL_TABS = ("videos", "streams")

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}
_KICK_HOSTS = {"kick.com", "www.kick.com"}
_CHANNEL_PATH = re.compile(r"^/(@[\w.\-]{1,100}|channel/UC[\w\-]{20,24}|c/[\w.\-%]{1,100}|user/[\w.\-%]{1,100})/?$")
_TAB_SUFFIX = re.compile(r"/(videos|streams|shorts|featured|live|playlists|about)/?$")
_LIVE_TAB_SUFFIX = re.compile(r"/(videos|clips|schedule|about|chat)/?$", re.IGNORECASE)
_TWITCH_NAME = re.compile(r"^[A-Za-z0-9_]{3,25}$")
_KICK_NAME = re.compile(r"^[A-Za-z0-9_\-]{3,40}$")
_RESERVED = {"videos", "directory", "search", "settings", "downloads", "turbo", "following", "categories", "browse", "clips"}
_BAD_LINK = "Paste a YouTube, Twitch or Kick channel link, like youtube.com/@name, twitch.tv/name or kick.com/name"


class WatchError(Exception):
    """A request the user can fix (bad link, too many channels)."""


def platform_of(channel_url: str) -> str:
    host = (urlparse(channel_url).hostname or "").lower()
    if host in _TWITCH_HOSTS:
        return "twitch"
    if host in _KICK_HOSTS:
        return "kick"
    return "youtube"


def normalize_channel_url(raw: str) -> str:
    """The canonical address of a YouTube, Twitch or Kick channel, or a WatchError for anything else."""
    parsed = urlparse((raw or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        raise WatchError(_BAD_LINK)
    if host in _YOUTUBE_HOSTS:
        path = _TAB_SUFFIX.sub("", parsed.path.rstrip("/") or "/")
        if not _CHANNEL_PATH.match(path):
            raise WatchError(_BAD_LINK)
        return f"https://www.youtube.com{path.rstrip('/')}"
    if host in _TWITCH_HOSTS or host in _KICK_HOSTS:
        twitch = host in _TWITCH_HOSTS
        path = _LIVE_TAB_SUFFIX.sub("", parsed.path.rstrip("/") or "/")
        name = path.strip("/")
        valid = _TWITCH_NAME if twitch else _KICK_NAME
        if "/" in name or not valid.match(name) or name.lower() in _RESERVED:
            raise WatchError(_BAD_LINK)
        return f"https://www.twitch.tv/{name.lower()}" if twitch else f"https://kick.com/{name.lower()}"
    raise WatchError(_BAD_LINK)


def _ydl_options(extra: Dict[str, Any]) -> Dict[str, Any]:
    from .youtube_cookies import with_cookies
    from .youtube_proxy import challenge_params

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 20,
        **challenge_params(),
        **extra,
    }
    return with_cookies(options)


def _live_options() -> Dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 20,
        "playlistend": LATEST_PER_TAB,
    }


def _fetch_past_broadcasts(channel_url: str, platform: str) -> Dict[str, Any]:
    """Twitch and Kick: the channel's newest past broadcasts (VODs), newest first."""
    import yt_dlp

    name = urlparse(channel_url).path.strip("/")
    if platform == "twitch":
        listing = f"https://www.twitch.tv/{name}/videos?filter=archives&sort=time"
        id_ok = re.compile(r"v\d{4,}")
    else:
        listing = f"https://kick.com/{name}/videos"
        id_ok = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    try:
        with yt_dlp.YoutubeDL(_live_options()) as ydl:
            info = ydl.extract_info(listing, download=False) or {}
    except Exception as exc:
        logger.warning("%s channel lookup failed: %s", platform, str(exc)[:200])
        raise WatchError("Could not read this channel. Check the link and try again.") from exc
    title = str(info.get("title") or "").rsplit(" - ", 1)[0].strip() or name
    videos: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in info.get("entries") or []:
        video_id = str((entry or {}).get("id") or "")
        if not id_ok.fullmatch(video_id) or video_id in seen:
            continue
        if (entry.get("live_status") or "") in {"is_live", "is_upcoming"}:
            continue
        seen.add(video_id)
        duration = entry.get("duration")
        url = f"https://www.twitch.tv/videos/{video_id[1:]}" if platform == "twitch" else f"https://kick.com/{name}/videos/{video_id}"
        videos.append(
            {
                "id": video_id,
                "title": str(entry.get("title") or "")[:500],
                "duration": int(duration) if isinstance(duration, (int, float)) else None,
                "url": url,
            }
        )
    return {"title": title[:200], "videos": videos}


def fetch_latest(channel_url: str) -> Dict[str, Any]:
    """Blocking: the channel's title and newest finished videos, newest first."""
    platform = platform_of(channel_url)
    if platform != "youtube":
        return _fetch_past_broadcasts(channel_url, platform)

    import yt_dlp

    title = ""
    videos: List[Dict[str, Any]] = []
    seen: set[str] = set()
    errors: List[str] = []
    for tab in CHANNEL_TABS:
        try:
            with yt_dlp.YoutubeDL(_ydl_options({"playlistend": LATEST_PER_TAB})) as ydl:
                info = ydl.extract_info(f"{channel_url}/{tab}", download=False) or {}
        except Exception as exc:  # a channel without a streams tab is normal
            errors.append(str(exc))
            continue
        title = title or str(info.get("channel") or info.get("uploader") or info.get("title") or "")
        for entry in info.get("entries") or []:
            video_id = str((entry or {}).get("id") or "")
            if not re.fullmatch(r"[\w\-]{11}", video_id) or video_id in seen:
                continue
            if (entry.get("live_status") or "") in {"is_live", "is_upcoming"}:
                continue  # wait until the stream ends and becomes a video
            seen.add(video_id)
            duration = entry.get("duration")
            videos.append(
                {
                    "id": video_id,
                    "title": str(entry.get("title") or "")[:500],
                    "duration": int(duration) if isinstance(duration, (int, float)) else None,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
    if not videos and not title:
        logger.warning("Channel lookup failed: %s", errors[:1])
        raise WatchError("Could not read this channel. Check the link and try again.")
    return {"title": title[:200], "videos": videos}


def _watch_row(row: Any) -> Dict[str, Any]:
    return {
        "id": row.id,
        "channel_url": row.channel_url,
        "platform": platform_of(row.channel_url),
        "streamer_id": row.streamer_id,
        "title": row.title,
        "allows_clips": bool(row.allows_clips),
        "active": bool(row.active),
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
        "last_error": row.last_error,
        "pending_count": int(getattr(row, "pending_count", 0) or 0),
    }


def _discovery_row(row: Any) -> Dict[str, Any]:
    return {
        "id": row.id,
        "watch_id": row.watch_id,
        "streamer_name": row.streamer_name,
        "channel_platform": platform_of(row.channel_url),
        "channel_title": row.channel_title,
        "allows_clips": bool(row.allows_clips),
        "video_id": row.video_id,
        "url": row.url,
        "title": row.title,
        "duration_seconds": row.duration_seconds,
        "status": row.status,
        "task_id": row.task_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


_WATCH_COLUMNS = (
    "w.id, w.streamer_id, w.channel_url, w.title, w.allows_clips, w.active, w.last_checked_at, w.last_error, "
    "(SELECT COUNT(*) FROM channel_discoveries d WHERE d.watch_id = w.id AND d.status = 'pending') AS pending_count"
)


class ChannelWatchService:
    @staticmethod
    async def list_streamers(db: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
        result = await db.execute(
            text("SELECT id, name FROM streamers WHERE user_id = :u ORDER BY lower(name)"), {"u": user_id}
        )
        return [{"id": row.id, "name": row.name} for row in result.fetchall()]

    @staticmethod
    async def add_streamer(db: AsyncSession, user_id: str, raw_name: str) -> Dict[str, Any]:
        name = " ".join((raw_name or "").split())[:80]
        if not name:
            raise WatchError("Type the streamer's name")
        count = (await db.execute(text("SELECT COUNT(*) FROM streamers WHERE user_id = :u"), {"u": user_id})).scalar()
        if int(count or 0) >= MAX_STREAMERS_PER_USER:
            raise WatchError(f"You can follow up to {MAX_STREAMERS_PER_USER} streamers")
        exists = (
            await db.execute(
                text("SELECT 1 FROM streamers WHERE user_id = :u AND lower(name) = lower(:n)"), {"u": user_id, "n": name}
            )
        ).fetchone()
        if exists:
            raise WatchError("You already added this streamer")
        streamer_id = str(uuid4())
        await db.execute(
            text("INSERT INTO streamers (id, user_id, name) VALUES (:id, :u, :n)"),
            {"id": streamer_id, "u": user_id, "n": name},
        )
        await db.commit()
        return {"id": streamer_id, "name": name}

    @staticmethod
    async def delete_streamer(db: AsyncSession, user_id: str, streamer_id: str) -> bool:
        """Removes the streamer together with its channels and their waiting videos."""
        result = await db.execute(
            text("DELETE FROM streamers WHERE id = :id AND user_id = :u"), {"id": streamer_id, "u": user_id}
        )
        await db.commit()
        return bool(result.rowcount)

    @staticmethod
    async def list_watches(db: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
        result = await db.execute(
            text(f"SELECT {_WATCH_COLUMNS} FROM channel_watches w WHERE w.user_id = :u ORDER BY w.created_at DESC"),
            {"u": user_id},
        )
        return [_watch_row(row) for row in result.fetchall()]

    @staticmethod
    async def _get_watch(db: AsyncSession, user_id: str, watch_id: str) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            text(f"SELECT {_WATCH_COLUMNS} FROM channel_watches w WHERE w.id = :id AND w.user_id = :u"),
            {"id": watch_id, "u": user_id},
        )
        row = result.fetchone()
        return _watch_row(row) if row else None

    @staticmethod
    async def add_watch(
        db: AsyncSession, user_id: str, raw_url: str, allows_clips: bool, streamer_id: str
    ) -> Dict[str, Any]:
        url = normalize_channel_url(raw_url)
        owned = (
            await db.execute(
                text("SELECT 1 FROM streamers WHERE id = :s AND user_id = :u"), {"s": streamer_id, "u": user_id}
            )
        ).fetchone()
        if not owned:
            raise WatchError("Streamer not found")
        count = (await db.execute(text("SELECT COUNT(*) FROM channel_watches WHERE user_id = :u"), {"u": user_id})).scalar()
        if int(count or 0) >= MAX_WATCHES_PER_USER:
            raise WatchError(f"You can follow up to {MAX_WATCHES_PER_USER} channels")
        exists = (
            await db.execute(
                text("SELECT 1 FROM channel_watches WHERE user_id = :u AND channel_url = :url"),
                {"u": user_id, "url": url},
            )
        ).fetchone()
        if exists:
            raise WatchError("You already follow this channel")
        latest = await run_in_thread(fetch_latest, url)
        watch_id = str(uuid4())
        await db.execute(
            text(
                "INSERT INTO channel_watches (id, user_id, streamer_id, channel_url, title, allows_clips, last_checked_at) "
                "VALUES (:id, :u, :sid, :url, :title, :allows, CURRENT_TIMESTAMP)"
            ),
            {"id": watch_id, "u": user_id, "sid": streamer_id, "url": url, "title": latest["title"], "allows": allows_clips},
        )
        await ChannelWatchService._store(db, watch_id, user_id, latest["videos"], status="baseline")
        await db.commit()
        return await ChannelWatchService._get_watch(db, user_id, watch_id) or {}

    @staticmethod
    async def update_watch(db: AsyncSession, user_id: str, watch_id: str, changes: Dict[str, bool]) -> Optional[Dict[str, Any]]:
        fields = {key: value for key, value in changes.items() if key in {"allows_clips", "active"}}
        if fields:
            assignments = ", ".join(f"{key} = :{key}" for key in fields)
            await db.execute(
                text(f"UPDATE channel_watches SET {assignments} WHERE id = :id AND user_id = :u"),
                {**fields, "id": watch_id, "u": user_id},
            )
            await db.commit()
        return await ChannelWatchService._get_watch(db, user_id, watch_id)

    @staticmethod
    async def delete_watch(db: AsyncSession, user_id: str, watch_id: str) -> bool:
        result = await db.execute(
            text("DELETE FROM channel_watches WHERE id = :id AND user_id = :u"), {"id": watch_id, "u": user_id}
        )
        await db.commit()
        return bool(result.rowcount)

    @staticmethod
    async def _store(db: AsyncSession, watch_id: str, user_id: str, videos: List[Dict[str, Any]], status: str) -> int:
        stored = 0
        for video in videos:
            result = await db.execute(
                text(
                    "INSERT INTO channel_discoveries (id, watch_id, user_id, video_id, url, title, duration_seconds, status) "
                    "VALUES (:id, :w, :u, :vid, :url, :title, :dur, :status) ON CONFLICT (watch_id, video_id) DO NOTHING"
                ),
                {
                    "id": str(uuid4()),
                    "w": watch_id,
                    "u": user_id,
                    "vid": video["id"],
                    "url": video.get("url") or f"https://www.youtube.com/watch?v={video['id']}",
                    "title": video["title"],
                    "dur": video["duration"],
                    "status": status,
                },
            )
            stored += int(result.rowcount or 0)
        return stored

    @staticmethod
    async def check_watch(db: AsyncSession, user_id: str, watch_id: str) -> Dict[str, Any]:
        """Look for new videos now; returns how many were found."""
        watch = await ChannelWatchService._get_watch(db, user_id, watch_id)
        if watch is None:
            raise WatchError("Channel not found")
        found = await ChannelWatchService._check(db, watch["id"], user_id, watch["channel_url"], watch["pending_count"])
        return {"found": found, "watch": await ChannelWatchService._get_watch(db, user_id, watch_id)}

    @staticmethod
    async def _check(db: AsyncSession, watch_id: str, user_id: str, channel_url: str, pending: int) -> int:
        try:
            latest = await run_in_thread(fetch_latest, channel_url)
        except Exception as exc:
            await db.execute(
                text("UPDATE channel_watches SET last_checked_at = CURRENT_TIMESTAMP, last_error = :e WHERE id = :id"),
                {"e": str(exc)[:300], "id": watch_id},
            )
            await db.commit()
            return 0
        room = max(0, MAX_PENDING_PER_WATCH - pending)
        found = await ChannelWatchService._store(db, watch_id, user_id, latest["videos"][:room], status="pending") if room else 0
        await db.execute(
            text(
                "UPDATE channel_watches SET last_checked_at = CURRENT_TIMESTAMP, last_error = NULL, "
                "title = CASE WHEN :title <> '' THEN :title ELSE title END WHERE id = :id"
            ),
            {"title": latest["title"], "id": watch_id},
        )
        await db.commit()
        return found

    @staticmethod
    async def check_due(db: AsyncSession) -> Dict[str, int]:
        """Cron: check the channels that have waited longest."""
        result = await db.execute(
            text(
                "SELECT w.id, w.user_id, w.channel_url, "
                "(SELECT COUNT(*) FROM channel_discoveries d WHERE d.watch_id = w.id AND d.status = 'pending') AS pending "
                "FROM channel_watches w WHERE w.active AND "
                "(w.last_checked_at IS NULL OR w.last_checked_at < CURRENT_TIMESTAMP - make_interval(mins => :mins)) "
                "ORDER BY w.last_checked_at NULLS FIRST LIMIT :limit"
            ),
            {"mins": CHECK_INTERVAL_MINUTES, "limit": DUE_BATCH},
        )
        due = result.fetchall()
        found = 0
        for row in due:
            found += await ChannelWatchService._check(db, row.id, row.user_id, row.channel_url, int(row.pending or 0))
        return {"checked": len(due), "found": found}

    @staticmethod
    async def list_discoveries(db: AsyncSession, user_id: str, status: str = "pending") -> List[Dict[str, Any]]:
        result = await db.execute(
            text(
                "SELECT d.id, d.watch_id, w.channel_url, COALESCE(s.name, w.title) AS streamer_name, w.title AS channel_title, "
                "w.allows_clips, d.video_id, d.url, d.title, d.duration_seconds, d.status, d.task_id, d.created_at "
                "FROM channel_discoveries d JOIN channel_watches w ON w.id = d.watch_id "
                "LEFT JOIN streamers s ON s.id = w.streamer_id "
                "WHERE d.user_id = :u AND d.status = :s ORDER BY d.created_at DESC LIMIT 100"
            ),
            {"u": user_id, "s": status},
        )
        return [_discovery_row(row) for row in result.fetchall()]

    @staticmethod
    async def resolve_discovery(db: AsyncSession, user_id: str, discovery_id: str, status: str, task_id: Optional[str] = None) -> bool:
        """Mark a pending discovery approved (with the task it became) or dismissed."""
        result = await db.execute(
            text(
                "UPDATE channel_discoveries SET status = :s, task_id = :t "
                "WHERE id = :id AND user_id = :u AND status = 'pending'"
            ),
            {"s": status, "t": task_id, "id": discovery_id, "u": user_id},
        )
        await db.commit()
        return bool(result.rowcount)
