"""One still frame of a source video, for the layout page.

Only YouTube links are accepted (the host is checked by ``get_youtube_video_id``,
so this cannot be pointed at arbitrary addresses). A video already in the
cache is read from disk; otherwise yt-dlp resolves a low-resolution stream URL
and ffmpeg reads a single frame from it, so nothing is downloaded in full.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from ..youtube_source import cache_dir_for
from ..youtube_utils import get_youtube_video_id

logger = logging.getLogger(__name__)

PREVIEW_WIDTH = 1280
FFMPEG_TIMEOUT = 45
CLIP_SECONDS = 5
CLIP_WIDTH = 854
CLIP_TIMEOUT = 90


class PreviewError(Exception):
    """The frame could not be produced; the message is safe to show."""


def _frame_from(source: str, seconds: float, headers: Optional[dict] = None) -> bytes:
    command = ["ffmpeg", "-v", "error", "-y"]
    if headers:
        command += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    command += [
        "-ss", f"{max(0.0, seconds):.2f}", "-i", source, "-frames:v", "1",
        "-vf", f"scale='min({PREVIEW_WIDTH},iw)':-2", "-f", "image2pipe",
        "-vcodec", "mjpeg", "-q:v", "3", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise PreviewError("Timed out loading the preview") from None
    if result.returncode != 0 or not result.stdout:
        logger.warning("Preview frame failed: %s", result.stderr[-300:].decode(errors="replace"))
        raise PreviewError("Could not read a frame from this video")
    return result.stdout


def _cached_file(video_id: str) -> Optional[Path]:
    directory = cache_dir_for(video_id)
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("full-*.mp4"), reverse=True)
    return files[0] if files else None


def _stream_url(url: str) -> tuple:
    import yt_dlp

    options = {
        "quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
        "format": "bv*[height<=720][ext=mp4]/bv*[height<=720]/b[height<=720]/b",
        "socket_timeout": 20,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        logger.warning("Preview stream lookup failed: %s", exc)
        text = str(exc).lower()
        if "sign in" in text or "age" in text and "confirm" in text:
            raise PreviewError(
                "YouTube requires a login to open this video (age-restricted). "
                "Download it and use the File option instead."
            ) from None
        if "private" in text or "unavailable" in text:
            raise PreviewError("This video is private or unavailable") from None
        raise PreviewError("Could not open this YouTube video") from None
    stream = info.get("url") or next(
        (f.get("url") for f in reversed(info.get("requested_formats") or []) if f.get("url")), None
    )
    if not stream:
        raise PreviewError("Could not open this YouTube video")
    return stream, info.get("http_headers") or {}, float(info.get("duration") or 0)


def preview_frame(url: str, seconds: float) -> bytes:
    """JPEG bytes of the frame at ``seconds`` of a YouTube video."""
    video_id = get_youtube_video_id(url)
    if not video_id:
        raise PreviewError("Only YouTube links can be previewed for now")
    cached = _cached_file(video_id)
    if cached is not None:
        return _frame_from(str(cached), seconds)
    stream, headers, duration = _stream_url(f"https://www.youtube.com/watch?v={video_id}")
    if duration and seconds >= duration:
        seconds = max(0.0, duration - 1)
    return _frame_from(stream, seconds, headers)


def _clip_from(source: str, seconds: float, headers: Optional[dict] = None) -> bytes:
    """Five seconds as a fragmented MP4 (streamable through a pipe)."""
    command = ["ffmpeg", "-v", "error", "-y"]
    if headers:
        command += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    command += [
        "-ss", f"{max(0.0, seconds):.2f}", "-i", source, "-t", str(CLIP_SECONDS), "-c:a", "aac", "-b:a", "96k",
        "-vf", f"scale='min({CLIP_WIDTH},iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=CLIP_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise PreviewError("Timed out loading the video clip") from None
    if result.returncode != 0 or not result.stdout:
        logger.warning("Preview clip failed: %s", result.stderr[-300:].decode(errors="replace"))
        raise PreviewError("Could not read a clip from this video")
    return result.stdout


def preview_clip(url: str, seconds: float) -> bytes:
    """MP4 bytes of 5 seconds of a YouTube video starting at ``seconds``."""
    video_id = get_youtube_video_id(url)
    if not video_id:
        raise PreviewError("Only YouTube links can be previewed for now")
    cached = _cached_file(video_id)
    if cached is not None:
        return _clip_from(str(cached), seconds)
    stream, headers, duration = _stream_url(f"https://www.youtube.com/watch?v={video_id}")
    if duration and seconds >= duration:
        seconds = max(0.0, duration - CLIP_SECONDS)
    return _clip_from(stream, seconds, headers)
