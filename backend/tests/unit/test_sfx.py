import shutil
import subprocess

import pytest

from src.media import sfx

KEEP = [(100.0, 110.0), (200.0, 210.0)]
OFFSETS = [0.0, 10.0]
MOMENTS = [{"range": [100.0, 110.0]}, {"range": [200.0, 210.0]}]


def test_humor_whooshes_at_the_handover_and_dings_where_the_last_beat_lands():
    cues = sfx.sfx_cues({"style": "humor", "moments": MOMENTS}, KEEP, OFFSETS)

    # The first beat's ding would sit on top of the handover whoosh, so the whoosh wins.
    assert [(cue["kind"], cue["time"]) for cue in cues] == [("whoosh", 9.85), ("ding", 19.9)]


def test_no_style_or_an_unsounded_style_adds_nothing():
    assert sfx.sfx_cues({"moments": MOMENTS}, KEEP, OFFSETS) == []
    assert sfx.sfx_cues({"style": "drama", "moments": MOMENTS}, KEEP, OFFSETS) == []
    assert sfx.sfx_cues(None, KEEP, OFFSETS) == []
    assert sfx.sfx_cues({"style": "humor", "moments": MOMENTS}, KEEP, [0.0]) == []


def test_a_beat_cut_out_of_the_render_gets_no_sound():
    cues = sfx.sfx_cues({"style": "hype", "moments": [{"range": [100.0, 110.0]}, {"range": [500.0, 510.0]}]}, KEEP, OFFSETS)

    assert cues == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_mix_keeps_the_picture_and_the_length(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=4", "-f", "lavfi", "-i", "sine=f=220:d=4",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)],
        check=True, capture_output=True,
    )

    assert sfx.apply_sfx(clip, [{"kind": "whoosh", "time": 1.0}, {"kind": "ding", "time": 2.5}]) is True

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(clip)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert sorted(probe) == ["audio", "video"]


def test_a_missing_clip_is_left_alone(tmp_path):
    assert sfx.apply_sfx(tmp_path / "nope.mp4", [{"kind": "ding", "time": 1.0}]) is False
    assert sfx.apply_sfx(tmp_path / "nope.mp4", []) is False
