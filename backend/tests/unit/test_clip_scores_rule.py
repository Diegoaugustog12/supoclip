"""Every clip carries a score: estimate it from relevance when the model left it out."""

from src.repositories.clip_repository import ensure_scores


def test_keeps_real_scores():
    assert ensure_scores(0.9, 88, 22, 22, 22, 22) == (88, 22, 22, 22, 22)


def test_sums_criteria_when_total_is_missing():
    assert ensure_scores(0.9, 0, 20, 18, 15, 10) == (63, 20, 18, 15, 10)


def test_estimates_from_relevance_when_everything_is_missing():
    total, hook, engagement, value, shareability = ensure_scores(0.95, 0, 0, 0, 0, 0)
    assert total == hook + engagement + value + shareability == 96
    assert 0 < hook <= 25


def test_no_relevance_stays_empty():
    assert ensure_scores(0, 0, 0, 0, 0, 0) == (0, 0, 0, 0, 0)
