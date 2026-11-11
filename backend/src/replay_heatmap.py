"""YouTube's "Most replayed" graph as a clipping signal.

yt-dlp exposes it as ``info["heatmap"]``: about a hundred bins of
``{"start_time", "end_time", "value"}`` with ``value`` scaled 0..1 per video.
Only videos with enough views have one; everything here is a no-op without it.
The peaks are hints for the ranking step, never clip boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence

# Bins at or above this value (relative to the video's own top) belong to a peak.
PEAK_MIN_VALUE = 0.6
MAX_PEAKS = 10
# Peaks closer than this are one moment.
PEAK_MERGE_GAP_SECONDS = 20.0
# Ranking bonus, in score points, for a clip sitting on the video's top peak.
MAX_RANK_BONUS = 6.0
MIN_BINS = 8


@dataclass(frozen=True)
class Bin:
    start: float
    end: float
    value: float


@dataclass(frozen=True)
class Peak:
    start: float
    end: float
    value: float


def normalize_heatmap(raw: Any) -> List[Bin]:
    """Valid, time-ordered bins from yt-dlp's heatmap; empty when unusable."""
    if not isinstance(raw, (list, tuple)):
        return []
    bins: List[Bin] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start_time"])
            end = float(item["end_time"])
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (start >= 0 and end > start and 0.0 <= value <= 1.0):
            continue
        bins.append(Bin(start, end, value))
    bins.sort(key=lambda b: b.start)
    return bins if len(bins) >= MIN_BINS else []


def find_peaks(
    bins: Sequence[Bin],
    *,
    min_value: float = PEAK_MIN_VALUE,
    max_peaks: int = MAX_PEAKS,
) -> List[Peak]:
    """Contiguous runs of hot bins, strongest first, nearby runs merged."""
    runs: List[Peak] = []
    current: Optional[Peak] = None
    for b in bins:
        if b.value >= min_value:
            if current is not None and b.start - current.end <= PEAK_MERGE_GAP_SECONDS:
                current = Peak(current.start, b.end, max(current.value, b.value))
            else:
                if current is not None:
                    runs.append(current)
                current = Peak(b.start, b.end, b.value)
        elif current is not None and b.start - current.end > PEAK_MERGE_GAP_SECONDS:
            runs.append(current)
            current = None
    if current is not None:
        runs.append(current)
    runs.sort(key=lambda p: p.value, reverse=True)
    return runs[:max_peaks]


def _label(seconds: float) -> str:
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{secs:02d}"


def signal_lines(peaks: Iterable[Peak]) -> List[str]:
    """Lines in the clip-signal format the analysis prompt already carries."""
    lines = []
    for peak in sorted(peaks, key=lambda p: p.start):
        lines.append(
            f"- [{_label(peak.start)} - {_label(peak.end)}] replay={peak.value:.2f}: "
            "viewers replayed this part most (YouTube 'Most replayed'); the payoff "
            "sits here, so start the clip a sentence or two earlier for the setup"
        )
    return lines


def merge_clip_signals(clip_signals: Optional[str], peaks: Sequence[Peak]) -> Optional[str]:
    """The transcript/audio hints plus the replay peaks, as one signal text."""
    lines = signal_lines(peaks)
    if not lines:
        return clip_signals
    header = "YouTube audience replay peaks (real viewer behaviour, strongest signal of interest):"
    extra = "\n".join([header, *lines])
    return f"{clip_signals}\n{extra}" if clip_signals else extra


def heat_between(bins: Sequence[Bin], start: float, end: float) -> float:
    """Highest replay value of any bin overlapping [start, end]; 0 when none."""
    best = 0.0
    for b in bins:
        if b.end > start and b.start < end:
            best = max(best, b.value)
    return best


def rank_bonus(heat: float) -> float:
    """Score points added when ordering clips: nothing below the peak threshold."""
    if heat < PEAK_MIN_VALUE:
        return 0.0
    return MAX_RANK_BONUS * (heat - PEAK_MIN_VALUE) / (1.0 - PEAK_MIN_VALUE)
