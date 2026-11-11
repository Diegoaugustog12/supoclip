"""Optional YouTube login for yt-dlp (age-restricted videos).

Export your browser's youtube.com cookies in Netscape format to
``cookies/youtube.txt`` (or point ``YOUTUBE_COOKIES_FILE`` at another file).
Without that file nothing changes.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_COOKIES_FILE = "/app/cookies/youtube.txt"


def cookies_path() -> Optional[Path]:
    raw = (os.getenv("YOUTUBE_COOKIES_FILE") or DEFAULT_COOKIES_FILE).strip()
    path = Path(raw)
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


def with_cookies(opts: Dict[str, Any]) -> Dict[str, Any]:
    """Add the cookie file to yt-dlp options when one is configured.

    yt-dlp rewrites its cookie file on exit, so each call gets a private copy
    (the mounted file stays read-only and parallel jobs never collide).
    """
    source = cookies_path()
    if source is None or opts.get("cookiefile"):
        return opts
    try:
        handle, copy = tempfile.mkstemp(prefix="yt-cookies-", suffix=".txt")
        os.close(handle)
        shutil.copyfile(source, copy)
    except OSError:
        return opts
    opts["cookiefile"] = copy
    return opts
