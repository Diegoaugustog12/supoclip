import sys
import types

import pytest

from src import channel_watch
from src.channel_watch import WatchError, normalize_channel_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://www.youtube.com/@GameJu", "https://www.youtube.com/@GameJu"),
        ("youtube.com/@GameJu", None),  # no scheme: refused
        ("https://m.youtube.com/@GameJu/videos", "https://www.youtube.com/@GameJu"),
        ("https://youtube.com/@GameJu/streams/", "https://www.youtube.com/@GameJu"),
        ("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv", "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"),
        ("https://www.youtube.com/watch?v=abcdefghijk", None),
        ("https://evil.example.com/@GameJu", None),
        ("", None),
        ("https://www.twitch.tv/Gaules", "https://www.twitch.tv/gaules"),
        ("https://twitch.tv/gaules/videos?filter=all", "https://www.twitch.tv/gaules"),
        ("https://www.twitch.tv/videos/123456789", None),
        ("https://www.twitch.tv/directory", None),
        ("https://kick.com/XQC", "https://kick.com/xqc"),
        ("https://kick.com/xqc/videos", "https://kick.com/xqc"),
        ("https://kick.com/xqc/videos/01a200d7-e698-7c70-b0da-44f46b0c8fec", None),
        ("https://kick.com.evil.example/xqc", None),
    ],
)
def test_channel_links_are_normalized_or_refused(raw, expected):
    if expected is None:
        with pytest.raises(WatchError):
            normalize_channel_url(raw)
    else:
        assert normalize_channel_url(raw) == expected


def _fake_yt_dlp(monkeypatch, tabs):
    class FakeYDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            tab = url.rsplit("/", 1)[-1]
            if tab not in tabs:
                raise RuntimeError("no such tab")
            return tabs[tab]

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    monkeypatch.setattr(channel_watch, "_ydl_options", lambda extra: extra)


def test_latest_skips_live_and_upcoming_and_repeats(monkeypatch):
    _fake_yt_dlp(
        monkeypatch,
        {
            "videos": {
                "channel": "GameJu",
                "entries": [
                    {"id": "aaaaaaaaaaa", "title": "Corte um", "duration": 600},
                    {"id": "bbbbbbbbbbb", "title": "Ao vivo agora", "live_status": "is_live"},
                    {"id": "not-an-id", "title": "bad"},
                ],
            },
            "streams": {
                "entries": [
                    {"id": "aaaaaaaaaaa", "title": "Corte um", "duration": 600},
                    {"id": "ccccccccccc", "title": "Live acabou", "duration": 7200.0},
                    {"id": "ddddddddddd", "title": "Em breve", "live_status": "is_upcoming"},
                ]
            },
        },
    )

    latest = channel_watch.fetch_latest("https://www.youtube.com/@GameJu")

    assert latest["title"] == "GameJu"
    assert [v["id"] for v in latest["videos"]] == ["aaaaaaaaaaa", "ccccccccccc"]
    assert latest["videos"][1]["duration"] == 7200


def test_a_channel_that_cannot_be_read_is_an_error(monkeypatch):
    _fake_yt_dlp(monkeypatch, {})

    with pytest.raises(WatchError):
        channel_watch.fetch_latest("https://www.youtube.com/@Nobody")


def test_a_channel_without_a_streams_tab_still_works(monkeypatch):
    _fake_yt_dlp(monkeypatch, {"videos": {"channel": "Small", "entries": [{"id": "eeeeeeeeeee", "title": "x"}]}})

    latest = channel_watch.fetch_latest("https://www.youtube.com/@Small")

    assert [v["id"] for v in latest["videos"]] == ["eeeeeeeeeee"]


def test_twitch_past_broadcasts_become_video_urls(monkeypatch):
    seen = {}

    class FakeYDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            seen["url"] = url
            return {
                "title": "gaules - Past Broadcasts sorted by Date",
                "entries": [
                    {"id": "v2936298211", "title": "Rerun", "duration": 93724.0},
                    {"id": "v2936298211", "title": "Repeat"},
                    {"id": "clip-nope", "title": "bad"},
                ],
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))

    latest = channel_watch.fetch_latest("https://www.twitch.tv/gaules")

    assert "filter=archives" in seen["url"]
    assert latest["title"] == "gaules"
    assert latest["videos"] == [
        {"id": "v2936298211", "title": "Rerun", "duration": 93724, "url": "https://www.twitch.tv/videos/2936298211"}
    ]


def test_kick_past_broadcasts_become_video_urls(monkeypatch):
    vod = "01a200d7-e698-7c70-b0da-44f46b0c8fec"

    class FakeYDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"title": "xQc - Videos sorted by Date", "entries": [{"id": vod, "title": "Stream", "duration": 31009}]}

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))

    latest = channel_watch.fetch_latest("https://kick.com/xqc")

    assert latest["title"] == "xQc"
    assert latest["videos"][0]["url"] == f"https://kick.com/xqc/videos/{vod}"


def test_unreadable_live_channel_is_an_error(monkeypatch):
    class FakeYDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError("blocked")

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))

    with pytest.raises(WatchError):
        channel_watch.fetch_latest("https://kick.com/nobody")
