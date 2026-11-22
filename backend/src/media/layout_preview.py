"""One still frame of a source video, for the layout page.

Only YouTube links are accepted (the host is checked by ``get_youtube_video_id``,
so this cannot be pointed at arbitrary addresses). A video already in the
cache is read from disk; otherwise yt-dlp downloads only the few seconds the
preview needs into a temp file, and ffmpeg reads that file.

Reading the googlevideo stream URL straight from ffmpeg fails with 403, so the
bytes are fetched by yt-dlp itself, the same way the pipeline downloads media.
"""

import logging
import os
import shutil
import subprocess
import tempfile
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
DOWNLOAD_TIMEOUT = 120


class PreviewError(Exception):
    """The frame could not be produced; the message is safe to show."""


def _frame_from(source: str, seconds: float) -> bytes:
    command = [
        "ffmpeg", "-v", "error", "-y",
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


def _ydl_options(extra: dict) -> dict:
    from ..youtube_cookies import with_cookies
    from ..youtube_proxy import challenge_params

    options = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": "bv*[height<=720][ext=mp4]/bv*[height<=720]/b[height<=720]/b",
        "socket_timeout": 20,
        **challenge_params(),
        **extra,
    }
    return with_cookies(options)


def _lookup_error(exc: Exception) -> PreviewError:
    logger.warning("Preview lookup failed: %s", exc)
    text = str(exc).lower()
    if "sign in" in text or "age" in text and "confirm" in text:
        return PreviewError(
            "YouTube requires a login to open this video (age-restricted). "
            "Download it and use the File option instead."
        )
    if "private" in text or "unavailable" in text:
        return PreviewError("This video is private or unavailable")
    return PreviewError("Could not open this YouTube video")


def _video_duration(url: str) -> float:
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_ydl_options({"skip_download": True})) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise _lookup_error(exc) from None
    return float(info.get("duration") or 0)


def _download_section(url: str, start: float, length: float) -> Path:
    """Download ``length`` seconds from ``start`` into a temp dir; returns the file."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    folder = Path(tempfile.mkdtemp(prefix="layout-preview-"))
    options = _ydl_options({
        "outtmpl": str(folder / "section.%(ext)s"),
        "download_ranges": download_range_func(None, [(start, start + length)]),
        "force_keyframes_at_cuts": True,
        "overwrites": True,
        "socket_timeout": 30,
    })
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except Exception as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise _lookup_error(exc) from None
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.endswith(".part")]
    if not files:
        shutil.rmtree(folder, ignore_errors=True)
        raise PreviewError("Could not read a frame from this video")
    return files[0]


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def preview_frame(url: str, seconds: float) -> bytes:
    """JPEG bytes of the frame at ``seconds`` of a YouTube video."""
    video_id = get_youtube_video_id(url)
    if not video_id:
        raise PreviewError("Only YouTube links can be previewed for now")
    cached = _cached_file(video_id)
    if cached is not None:
        return _frame_from(str(cached), seconds)
    watch = _watch_url(video_id)
    duration = _video_duration(watch)
    if duration and seconds >= duration:
        seconds = max(0.0, duration - 1)
    start = max(0.0, seconds - 0.5)
    section = _download_section(watch, start, 2.0)
    try:
        return _frame_from(str(section), seconds - start)
    finally:
        shutil.rmtree(section.parent, ignore_errors=True)


def _clip_from(source: str, seconds: float) -> bytes:
    """Five seconds as a fragmented MP4 (streamable through a pipe)."""
    command = [
        "ffmpeg", "-v", "error", "-y",
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
    watch = _watch_url(video_id)
    duration = _video_duration(watch)
    if duration and seconds >= duration:
        seconds = max(0.0, duration - CLIP_SECONDS)
    section = _download_section(watch, max(0.0, seconds), CLIP_SECONDS)
    try:
        return _clip_from(str(section), 0.0)
    finally:
        shutil.rmtree(section.parent, ignore_errors=True)
