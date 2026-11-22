from src.media import duo_layout as dl


def test_two_people_intervals_hold_and_smooth():
    times = [i * 0.3 for i in range(40)]  # 12 seconds
    flags = [False] * 10 + [True] * 20 + [False] * 10
    flags[15] = False  # one missed detection must not break the split
    spans = dl.two_people_intervals(times, flags, 12.0)
    assert len(spans) == 1
    assert 2.5 < spans[0][0] < 3.6 and 8.5 < spans[0][1] < 9.6


def test_short_blip_is_ignored():
    times = [i * 0.3 for i in range(40)]
    flags = [False] * 40
    flags[20] = flags[21] = flags[22] = True  # under the minimum hold
    assert dl.two_people_intervals(times, flags, 12.0) == []


def test_pair_needs_two_separate_main_faces():
    wide = [(100.0, 200.0, 120.0, 150.0), (1400.0, 220.0, 110.0, 140.0)]
    assert dl._pair(wide, 1920) is not None
    assert dl._pair(wide[:1], 1920) is None
    background = [(100.0, 200.0, 120.0, 150.0), (1400.0, 220.0, 30.0, 40.0)]
    assert dl._pair(background, 1920) is None


def _analysis(samples):
    import numpy as np
    return {"face_samples": samples, "motion": np.zeros((130, 34, 60), dtype="float32"),
            "motion_fps": 10.0, "motion_cell": 8, "scene_cuts": []}


def test_graph_switches_between_split_and_single(monkeypatch):
    left, right = (300.0, 300.0, 160.0, 200.0), (1400.0, 320.0, 150.0, 190.0)
    samples = [(i * 0.3, [left, right] if 10 <= i < 30 else [left]) for i in range(40)]
    monkeypatch.setattr(dl, "analyze_speaker_clip", lambda *a, **k: _analysis(samples))
    plan = dl.build_duo_layout("clip.mp4", 1920, 1080, 12.0)
    graph = plan["video_filter"]
    assert "vstack=inputs=2[dtwo]" in graph and "overlay=0:0:enable='between(t" in graph
    assert graph.endswith("[vout]") and 5.0 < plan["split_seconds"] < 7.0


def test_single_person_clip_has_no_split(monkeypatch):
    samples = [(i * 0.3, [(900.0, 300.0, 160.0, 200.0)]) for i in range(40)]
    monkeypatch.setattr(dl, "analyze_speaker_clip", lambda *a, **k: _analysis(samples))
    plan = dl.build_duo_layout("clip.mp4", 1920, 1080, 12.0)
    assert "vstack" not in plan["video_filter"] and plan["caption_y"] is None


def test_no_faces_returns_none(monkeypatch):
    monkeypatch.setattr(dl, "analyze_speaker_clip", lambda *a, **k: _analysis([(0.0, []), (0.3, [])]))
    assert dl.build_duo_layout("clip.mp4", 1920, 1080, 12.0) is None
