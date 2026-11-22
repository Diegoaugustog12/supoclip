from src import youtube_cookies as yc


def test_without_file_options_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(tmp_path / "missing.txt"))
    assert yc.with_cookies({"a": 1}) == {"a": 1}


def test_with_file_uses_private_copy(monkeypatch, tmp_path):
    src = tmp_path / "youtube.txt"
    src.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(src))
    opts = yc.with_cookies({})
    assert opts["cookiefile"] != str(src)
    with open(opts["cookiefile"]) as handle:
        assert handle.read() == src.read_text()
