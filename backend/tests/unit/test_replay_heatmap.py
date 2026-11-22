import pytest

from src.ai import TranscriptSegment, apply_replay_ranking
from src.replay_heatmap import (
    find_peaks,
    heat_between,
    merge_clip_signals,
    normalize_heatmap,
    rank_bonus,
)


def raw(values, size=10.0):
    return [
        {"start_time": i * size, "end_time": (i + 1) * size, "value": v}
        for i, v in enumerate(values)
    ]


def test_unusable_heatmaps_are_ignored():
    assert normalize_heatmap(None) == []
    assert normalize_heatmap("x") == []
    assert normalize_heatmap(raw([0.5] * 3)) == []
    assert len(normalize_heatmap(raw([0.5] * 10) + [{"start_time": "a"}, 3])) == 10


def test_peaks_merge_nearby_hot_bins_and_rank_by_value():
    bins = normalize_heatmap(raw([0.1, 0.7, 0.9, 0.2, 0.1, 0.1, 0.1, 0.1, 0.65, 0.1]))
    peaks = find_peaks(bins)
    assert [(p.start, p.end, p.value) for p in peaks] == [(10.0, 30.0, 0.9), (80.0, 90.0, 0.65)]


def test_signal_text_keeps_the_prompt_line_format():
    bins = normalize_heatmap(raw([0.1, 1.0] + [0.1] * 8))
    text = merge_clip_signals("Deterministic hints:\n- [00:05 - 00:09] score=1.0: x", find_peaks(bins))
    assert "- [00:10 - 00:20] replay=1.00:" in text
    assert merge_clip_signals("a", []) == "a"


def test_bonus_only_on_peaks_and_bounded():
    bins = normalize_heatmap(raw([0.1, 1.0] + [0.1] * 8))
    assert heat_between(bins, 12, 18) == 1.0
    assert heat_between(bins, 50, 60) == 0.1
    assert rank_bonus(0.3) == 0.0
    assert rank_bonus(1.0) == pytest.approx(6.0)


def segment(start, end, score):
    return TranscriptSegment(
        start_time=start, end_time=end, text="uma frase de teste aqui",
        relevance_score=score / 100, reasoning="r",
        virality={"hook_score": score // 4, "engagement_score": score // 4,
                  "value_score": score // 4, "shareability_score": score - 3 * (score // 4),
                  "total_score": score, "virality_reasoning": "r"},
    )


def test_replay_reorders_close_calls_but_not_big_gaps():
    bins = normalize_heatmap(raw([0.1, 1.0] + [0.1] * 8))
    close = [segment("00:50", "01:10", 72), segment("00:10", "00:30", 70)]
    assert apply_replay_ranking(close, bins)[0].start_time == "00:10"
    far = [segment("00:50", "01:10", 85), segment("00:10", "00:30", 70)]
    assert apply_replay_ranking(far, bins)[0].start_time == "00:50"
