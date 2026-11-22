"""A custom layout also carries caption and title styling."""
import pytest

from src.media import captions
from src.media.custom_layout import normalize_layout_spec
from src.media.layout_choice import bind_layout

CAM = {"x": 0.7, "y": 0.55, "w": 0.28, "h": 0.4}
GAME = {"x": 0.0, "y": 0.0, "w": 0.47, "h": 1.0}
WORDS = [{"text": f"w{i}", "start": i * 0.4, "end": i * 0.4 + 0.35} for i in range(8)]


def spec(**extra):
    return {"panels": [{"crop": CAM, "height": 0.35}, {"crop": GAME}], **extra}


@pytest.fixture(autouse=True)
def _reset():
    yield
    bind_layout("auto")


def render(tmp_path, monkeypatch, *, layout=None, title="Big news today"):
    monkeypatch.setattr(captions, "emoji_rendering_supported", lambda: False)
    bind_layout("custom" if layout is not None else "auto", layout)
    out = tmp_path / "c.ass"
    assert captions.build_assemblyai_ass_subtitles(
        tmp_path / "missing.mp4", 0.0, 4.0, 1080, 1920, out,
        caption_template="default", caption_words=WORDS, include_captions=True, hook_title=title,
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    return [l for l in lines if l.startswith("Dialogue:")], [l for l in lines if l.startswith("Style:")]


def split(events):
    return [e for e in events if ",Hook," in e], [e for e in events if ",Default," in e]


def test_styles_are_validated_and_unknown_keys_dropped():
    out = normalize_layout_spec(spec(caption={"size": 30, "bogus": 1}, title={"y": 0.2}))
    assert out["caption"] == {"size": 30} and out["title"] == {"y": 0.2}
    assert normalize_layout_spec(spec())["caption"] == {}


@pytest.mark.parametrize("caption", [
    {"template": "nope"}, {"size": 500}, {"max_words": 0}, {"margin": 0.9},
    {"animation": "spin"}, {"font": "../etc/passwd"}, {"uppercase": "yes"}, "x",
])
def test_bad_caption_styles_are_rejected(caption):
    with pytest.raises(ValueError):
        normalize_layout_spec(spec(caption=caption))


@pytest.mark.parametrize("title", [{"y": 2}, {"size": 3}, {"animation": "spin"}, {"enabled": "no"}, "x"])
def test_bad_title_styles_are_rejected(title):
    with pytest.raises(ValueError):
        normalize_layout_spec(spec(title=title))


def test_without_a_layout_nothing_changes(tmp_path, monkeypatch):
    plain, _ = render(tmp_path, monkeypatch)
    same, _ = render(tmp_path, monkeypatch, layout=normalize_layout_spec(spec()))
    assert plain == same


def test_max_words_sets_how_many_words_each_caption_shows(tmp_path, monkeypatch):
    _, wide = split(render(tmp_path, monkeypatch, layout=normalize_layout_spec(spec(caption={"max_words": 8, "animation": "fade"})))[0])
    _, narrow = split(render(tmp_path, monkeypatch, layout=normalize_layout_spec(spec(caption={"max_words": 2, "animation": "fade"})))[0])
    assert len(narrow) > len(wide)


def test_caption_animation_and_template_come_from_the_layout(tmp_path, monkeypatch):
    _, events = split(render(tmp_path, monkeypatch, layout=normalize_layout_spec(
        spec(caption={"animation": "typewriter", "max_words": 4})))[0])
    assert any("\\alpha&HFF&" in e for e in events)


def test_title_position_size_and_off_switch(tmp_path, monkeypatch):
    hook, _ = split(render(tmp_path, monkeypatch, layout=normalize_layout_spec(spec(title={"y": 0.25, "size": 70})))[0])
    assert len(hook) == 1 and "\\an5\\pos(540,480)" in hook[0]
    off, _ = split(render(tmp_path, monkeypatch, layout=normalize_layout_spec(spec(title={"enabled": False})))[0])
    assert off == []


def test_title_animation_none_drops_the_fade_and_pop(tmp_path, monkeypatch):
    hook, _ = split(render(tmp_path, monkeypatch, layout=normalize_layout_spec(spec(title={"animation": "none"})))[0])
    assert "\\fad(" not in hook[0] and "\\fscx90" not in hook[0]
    pop, _ = split(render(tmp_path, monkeypatch, layout=normalize_layout_spec(spec(title={"animation": "pop"})))[0])
    assert "\\fscx90" in pop[0]
