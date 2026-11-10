import shutil
import subprocess

import pytest

from src.media.custom_layout import build_custom_layout, normalize_layout_spec, panel_heights
from src.media.layout_choice import bind_layout, current_layout, current_layout_spec

CAM = {"x": 0.7, "y": 0.55, "w": 0.28, "h": 0.4}
GAME = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}


def two(first=0.35, **extra):
    return {"panels": [{"crop": CAM, "height": first}, {"crop": GAME, "height": 1 - first}], **extra}


def test_two_panels_are_normalized_and_heights_sum_to_the_output():
    spec = normalize_layout_spec(two(0.35))
    assert spec["panels"][1]["height"] == pytest.approx(0.65)
    heights = panel_heights(spec)
    assert sum(heights) == 1920 and all(h % 2 == 0 for h in heights)


def test_one_panel_fills_the_frame():
    spec = normalize_layout_spec({"panels": [{"crop": GAME}]})
    assert panel_heights(spec) == [1920]


@pytest.mark.parametrize("bad", [
    None, [], {}, {"panels": []},
    {"panels": [{"crop": GAME}] * 3},
    {"panels": [{"crop": {"x": 0.9, "y": 0, "w": 0.5, "h": 1}}]},
    {"panels": [{"crop": {"x": 0, "y": 0, "w": 0.0, "h": 1}}]},
    {"panels": [{"crop": {"x": "a", "y": 0, "w": 1, "h": 1}}]},
    {"panels": [{"crop": {"x": True, "y": 0, "w": 1, "h": 1}}]},
    {"panels": [{"crop": CAM, "height": 0.05}, {"crop": GAME, "height": 0.95}]},
    {"panels": [{"crop": CAM, "height": 0.5}, {"crop": GAME}], "caption_y": 5},
])
def test_invalid_specs_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_layout_spec(bad)


def test_caption_defaults_to_the_panel_boundary_or_the_given_value():
    assert build_custom_layout(1920, 1080, normalize_layout_spec(two(0.4)))["caption_y"] == pytest.approx(0.4, abs=0.001)
    assert build_custom_layout(1920, 1080, normalize_layout_spec(two(0.4, caption_y=0.7)))["caption_y"] == 0.7


def test_bind_layout_custom_needs_a_valid_spec():
    assert bind_layout("custom", two()) == "custom"
    assert current_layout() == "custom" and current_layout_spec()
    assert bind_layout("custom", {"panels": []}) == "auto"
    assert current_layout_spec() is None
    assert bind_layout("reaction_top") == "reaction_top"
    assert current_layout_spec() is None


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
@pytest.mark.parametrize("spec", [
    two(0.35),
    {"panels": [{"crop": CAM}]},
    {"panels": [{"crop": GAME}]},
])
def test_filtergraph_renders_a_1080x1920_clip(tmp_path, spec):
    plan = build_custom_layout(1920, 1080, normalize_layout_spec(spec))
    out = tmp_path / "out.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=size=1920x1080:rate=10:duration=1",
        "-filter_complex", plan["video_filter"], "-map", "[vout]",
        "-pix_fmt", "yuv420p", str(out),
    ], check=True)
    size = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
        "stream=width,height", "-of", "csv=p=0", str(out),
    ], check=True, capture_output=True, text=True).stdout.strip()
    assert size == "1080,1920"


def test_second_panel_height_may_be_omitted():
    spec = normalize_layout_spec({"panels": [{"crop": CAM, "height": 0.4}, {"crop": GAME}]})
    assert spec["panels"][1]["height"] == pytest.approx(0.6)


def test_fit_defaults_to_cover_and_rejects_other_values():
    spec = normalize_layout_spec(two(0.35))
    assert [p["fit"] for p in spec["panels"]] == ["cover", "cover"]
    bad = two(0.35)
    bad["panels"][0]["fit"] = "stretch"
    with pytest.raises(ValueError):
        normalize_layout_spec(bad)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
def test_contain_panel_shows_the_whole_crop_over_a_blurred_background(tmp_path):
    # A wide full-frame crop in a tall panel: cover would cut the sides, contain keeps them.
    spec = two(0.35)
    spec["panels"][1]["crop"] = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    spec["panels"][1]["fit"] = "contain"
    plan = build_custom_layout(1920, 1080, normalize_layout_spec(spec))
    assert "gblur" in plan["video_filter"] and "decrease" in plan["video_filter"]
    out = tmp_path / "out.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=size=1920x1080:rate=10:duration=1",
        "-filter_complex", plan["video_filter"], "-map", "[vout]",
        "-pix_fmt", "yuv420p", str(out),
    ], check=True)
    size = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
        "stream=width,height", "-of", "csv=p=0", str(out),
    ], check=True, capture_output=True, text=True).stdout.strip()
    assert size == "1080,1920"
