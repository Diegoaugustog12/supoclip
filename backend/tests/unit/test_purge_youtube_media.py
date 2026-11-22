from types import SimpleNamespace

from src import youtube_source as ys
from src import youtube_utils as yu


def test_purge_removes_only_that_video(monkeypatch, tmp_path):
    config = SimpleNamespace(temp_dir=str(tmp_path))
    monkeypatch.setattr(yu, "get_config", lambda: config)
    monkeypatch.setattr(ys, "get_config", lambda: config)
    cache = tmp_path / "youtube-cache"
    (cache / "AAAAAAAAAAA").mkdir(parents=True)
    (cache / "AAAAAAAAAAA" / "full.mp4").write_text("x")
    (cache / "BBBBBBBBBBB").mkdir()
    (tmp_path / "AAAAAAAAAAA.mp4").write_text("x")
    (tmp_path / "AAAAAAAAAAA.f399.mp4.part").write_text("x")
    (tmp_path / "BBBBBBBBBBB.mp4").write_text("x")

    assert yu.purge_youtube_media("AAAAAAAAAAA") == 3
    assert not (cache / "AAAAAAAAAAA").exists()
    assert (cache / "BBBBBBBBBBB").exists()
    assert (tmp_path / "BBBBBBBBBBB.mp4").exists()


def test_purge_rejects_bad_ids(tmp_path):
    assert yu.purge_youtube_media("../..") == 0
    assert yu.purge_youtube_media("") == 0
