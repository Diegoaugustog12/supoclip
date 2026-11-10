"""The studio can re-render a clip's source with a chosen layout."""
import json
import shutil
import subprocess

import pytest

from src.media.layout_choice import bind_layout
from src.services.editor_service import (
    PRESERVED_LAYOUT_KINDS,
    apply_editor_layout,
    editor_preserved_layout,
    read_editor_layout,
)

SPEC = {
    "panels": [
        {"crop": {"x": 0.7, "y": 0.55, "w": 0.28, "h": 0.4}, "height": 0.35},
        {"crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "fit": "contain"},
    ],
}


@pytest.fixture(autouse=True)
def _reset():
    yield
    bind_layout("auto")


def test_custom_is_a_layout_the_editor_keeps_whole():
    assert "custom" in PRESERVED_LAYOUT_KINDS


def test_read_editor_layout_handles_missing_and_broken_files(tmp_path):
    assert read_editor_layout(tmp_path) is None
    (tmp_path / "editor_layout.json").write_text("not json")
    assert read_editor_layout(tmp_path) is None
    (tmp_path / "editor_layout.json").write_text(json.dumps(["x"]))
    assert read_editor_layout(tmp_path) is None
    (tmp_path / "editor_layout.json").write_text(json.dumps({"layout": "reaction_top"}))
    assert read_editor_layout(tmp_path) == {"layout": "reaction_top"}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
def test_a_custom_layout_is_baked_into_the_editor_source(tmp_path):
    clip = tmp_path / "clean.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=10:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip),
    ], check=True)
    bind_layout("custom", SPEC)
    layout = editor_preserved_layout(clip, "vertical", include_content=True)
    assert layout and layout["kind"] == "custom"
    assert apply_editor_layout(clip, layout)
    size = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
        "stream=width,height", "-of", "csv=p=0", str(clip),
    ], check=True, capture_output=True, text=True).stdout.strip()
    assert size == "1080,1920"
