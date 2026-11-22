"""Hashtags that are working right now in a clip's own subject.

Asks the YouTube Data API for the most-viewed recent videos about the clip's topic and counts the tags those
videos carry. A tag used by several of them is "in the air" for that context. Best effort: with no key, no
quota or no result the caller falls back to tags the model picks itself.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Sequence

import requests

from .config import get_config
from .utils.async_helpers import run_in_thread

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
WINDOW_DAYS = 30
VIDEOS_PER_QUERY = 25
MAX_QUERIES = 3
MIN_TAG_USES = 2
MAX_CANDIDATES = 40
REQUEST_TIMEOUT = (8, 20)


def _clean(tag: str) -> str:
    """A hashtag body: lowercase letters and digits only (accents kept, no spaces)."""
    return re.sub(r"[^\w]", "", tag.lower().lstrip("#"), flags=re.UNICODE)


def _search_ids(api_key: str, query: str, language: str | None) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "part": "id",
        "type": "video",
        "q": query,
        "order": "viewCount",
        "publishedAfter": since,
        "maxResults": VIDEOS_PER_QUERY,
        "key": api_key,
    }
    if language:
        params["relevanceLanguage"] = language
    response = requests.get(SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return [item["id"]["videoId"] for item in response.json().get("items", []) if item.get("id", {}).get("videoId")]


def _video_tags(api_key: str, video_ids: Sequence[str]) -> list[list[str]]:
    found: list[list[str]] = []
    for start in range(0, len(video_ids), 50):
        response = requests.get(
            VIDEOS_URL,
            params={
                "part": "snippet",
                "id": ",".join(video_ids[start:start + 50]),
                "fields": "items(snippet(title,tags))",
                "key": api_key,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        for item in response.json().get("items", []):
            snippet = item.get("snippet") or {}
            tags = [_clean(tag) for tag in snippet.get("tags") or []]
            tags += [_clean(tag) for tag in re.findall(r"#(\w+)", snippet.get("title") or "", flags=re.UNICODE)]
            found.append([tag for tag in tags if 2 <= len(tag) <= 30])
    return found


def _collect(queries: Sequence[str], language: str | None) -> list[tuple[str, int]]:
    api_key = get_config().resolve_youtube_data_api_key()
    if not api_key:
        return []
    try:
        return _gather(api_key, queries, language)
    except requests.RequestException as error:
        # The request URL carries the key: report the status only, never the exception text.
        status = getattr(getattr(error, "response", None), "status_code", None)
        raise RuntimeError(f"YouTube API request failed (HTTP {status})") from None


def _gather(api_key: str, queries: Sequence[str], language: str | None) -> list[tuple[str, int]]:
    ids: list[str] = []
    for query in list(queries)[:MAX_QUERIES]:
        for video_id in _search_ids(api_key, query, language):
            if video_id not in ids:
                ids.append(video_id)
    if not ids:
        return []
    counts: Counter[str] = Counter()
    for tags in _video_tags(api_key, ids):
        counts.update(set(tags))  # one vote per video
    ranked = sorted(((tag, uses) for tag, uses in counts.items() if uses >= MIN_TAG_USES), key=lambda item: (-item[1], item[0]))
    return ranked[:MAX_CANDIDATES]


async def trending_tags(queries: Sequence[str], language: str | None = None) -> list[tuple[str, int]]:
    """(tag, videos using it) for the subject's recent top videos, most used first; [] when unavailable."""
    queries = [query.strip() for query in queries if query and query.strip()]
    if not queries:
        return []
    try:
        return await run_in_thread(_collect, queries, language)
    except Exception as error:  # quota, key without the YouTube API, network: the model picks tags itself
        logger.warning("Trending tags unavailable (%s)", type(error).__name__)
        return []
