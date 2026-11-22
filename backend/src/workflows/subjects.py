"""Subjects planner: one compilation per recurring subject of a long video.

Discover the subjects (what keeps coming back) → extract every beat of each
subject window by window → deterministic gate (sentence edges, length, no
line plays twice) → one compilation per subject, its beats in source order
at their natural length. Nothing here trims to a short-form length: the
creator shortens a compilation afterwards (``shorten_ranges``), which reads
the beat scores this planner stores in ``workflow_meta.moments``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .boundaries import STRONG_BOUNDARY
from .durations import SHORTEN_CHOICES, subject_budget
from .errors import WorkflowError
from .llm import build_agent, is_cancellation, run, run_retrying
from .planning import PlanInput, base_plan, planned_segment
from .prompts import (
    outline_block,
    subjects_block,
    subjects_discover_system,
    subjects_extract_system,
    transcript_block,
    with_instructions,
)
from .schemas import SubjectDiscovery, SubjectExtraction, SubjectMoment
from .series import PART_JUNCTION_FADE
from .titles import compose_title
from .topic import pack_windows
from .units import UnitIndex

logger = logging.getLogger(__name__)

# Shorter windows than a topic run: each call finishes sooner and a slow one costs less, and more
# of them run at once (a 2 h video took 25 minutes with 12-minute windows, 3 at a time).
WINDOW_SECONDS = 8 * 60
EXTRACT_CONCURRENCY = 6
EXTRACT_ATTEMPTS = 3
DISCOVER_ATTEMPTS = 3
DISCOVER_BACKOFF_SECONDS = 30.0
MIN_STRENGTH = 45
MIN_MOMENT_SECONDS = 4.0
MAX_MOMENT_SECONDS = 300.0
# A moment that starts or ends mid-sentence may move this many units to reach an edge.
EDGE_SEARCH_UNITS = 3
# Under this a subject is not worth a video of its own.
MIN_SUBJECT_SECONDS = 15.0
MAX_SUBJECT_SECONDS = 1200.0
MAX_SUBJECTS = 10
# The model's own bar: a subject it rates under this is not worth a cut.
MIN_SUBJECT_VIRALITY = 40
# The whole listing goes to the discovery call under this size; above it the outline stands in.
FULL_LISTING_MAX_CHARS = 220_000
# Beats this close in the source are one continuous scene.
JOIN_GAP_UNITS = 0
RENDER_PADDING_SECONDS = 20.0

_PLAN_FAILED = "The AI editor couldn't finish this plan. Please try again."


@dataclass
class Beat:
    subject: int
    first: int
    last: int
    strength: int
    title: str
    why: str
    seconds: float = 0.0


def subjects_not_found() -> WorkflowError:
    return WorkflowError(
        "subjects_not_found",
        "We couldn't find a subject that comes back often enough in this video to make its own cut.",
    )


# -- gate ----------------------------------------------------------------------------------


def _clamp(value: int, low: int, high: int) -> int:
    return min(max(int(value), low), high)


def _snap_edges(index: UnitIndex, first: int, last: int, shown: set[int]) -> Optional[tuple[int, int]]:
    """Whole sentences only: move an edge a few units, or give the beat up."""
    start = first
    steps = 0
    while not index.unit(start).starts_sentence and steps < EDGE_SEARCH_UNITS and start - 1 in shown:
        start -= 1
        steps += 1
    if not index.unit(start).starts_sentence:
        return None
    end = last
    steps = 0
    while index.boundary_strength(end) < STRONG_BOUNDARY and steps < EDGE_SEARCH_UNITS and end + 1 in shown:
        end += 1
        steps += 1
    if index.boundary_strength(end) < STRONG_BOUNDARY and end < len(index):
        return None
    return start, end


def gate_beats(
    index: UnitIndex,
    moments: Sequence[SubjectMoment],
    window: Sequence[int],
    subject_count: int,
    cleanup: Optional[dict],
) -> list[Beat]:
    shown = set(window)
    beats: list[Beat] = []
    for moment in moments:
        if not 1 <= moment.subject <= subject_count:
            continue
        strength = _clamp(moment.strength, 0, 100)
        if strength < MIN_STRENGTH:
            continue
        first, last = sorted((_clamp(moment.first_unit, 1, len(index)), _clamp(moment.last_unit, 1, len(index))))
        if first not in shown or last not in shown:
            continue  # the model may only use lines this window showed
        if any(uid not in shown for uid in range(first, last + 1)):
            continue
        edges = _snap_edges(index, first, last, shown)
        if edges is None:
            continue
        first, last = edges
        seconds = index.speech_seconds(first, last, (), cleanup)
        if not MIN_MOMENT_SECONDS <= seconds <= MAX_MOMENT_SECONDS:
            continue
        beats.append(
            Beat(
                subject=moment.subject,
                first=first,
                last=last,
                strength=strength,
                title=" ".join(moment.title.split()),
                why=" ".join(moment.why.split()),
                seconds=seconds,
            )
        )
    return beats


def resolve_beats(beats: Sequence[Beat]) -> list[Beat]:
    """No line plays twice, in any subject: the stronger beat keeps an overlap, a tie goes to the earlier."""
    kept: list[Beat] = []
    for beat in sorted(beats, key=lambda item: (-item.strength, item.first)):
        if any(beat.first <= other.last and other.first <= beat.last for other in kept):
            continue
        kept.append(beat)
    return sorted(kept, key=lambda item: item.first)


def join_scenes(beats: Sequence[Beat], index: UnitIndex, cleanup: Optional[dict]) -> list[Beat]:
    """Neighbouring beats of one subject (no unit between them) are one scene."""
    joined: list[Beat] = []
    for beat in sorted(beats, key=lambda item: item.first):
        previous = joined[-1] if joined else None
        if previous is not None and beat.first - previous.last - 1 <= JOIN_GAP_UNITS:
            first, last = previous.first, beat.last
            joined[-1] = Beat(
                subject=previous.subject,
                first=first,
                last=last,
                strength=max(previous.strength, beat.strength),
                title=previous.title if previous.strength >= beat.strength else beat.title,
                why=previous.why if previous.strength >= beat.strength else beat.why,
                seconds=index.speech_seconds(first, last, (), cleanup),
            )
        else:
            joined.append(beat)
    return joined


def cap_subject(beats: list[Beat]) -> list[Beat]:
    """Over the ceiling the weakest beats go first; what is left stays in source order."""
    total = sum(beat.seconds for beat in beats)
    if total <= MAX_SUBJECT_SECONDS:
        return beats
    keep = sorted(beats, key=lambda item: (-item.strength, item.first))
    chosen: list[Beat] = []
    used = 0.0
    for beat in keep:
        if used + beat.seconds <= MAX_SUBJECT_SECONDS:
            chosen.append(beat)
            used += beat.seconds
    return sorted(chosen, key=lambda item: item.first)


# -- shortening ------------------------------------------------------------------------------


def shorten_ranges(moments: Sequence[dict[str, Any]], max_seconds: float) -> list[list[float]]:
    """The strongest beats of a compilation that fit ``max_seconds``, in source order.

    ``moments`` are the ``workflow_meta.moments`` entries: ``range`` ([start, end] in
    source seconds), ``strength`` and ``seconds`` (played length). Greedy by strength per
    beat; a beat longer than the budget is cut to its opening, which holds its setup.
    Returns source ranges, or [] when there is nothing to choose from.
    """
    entries = [
        (float(m["range"][0]), float(m["range"][1]), int(m.get("strength") or 0), float(m.get("seconds") or 0.0))
        for m in moments
        if isinstance(m.get("range"), (list, tuple)) and len(m["range"]) == 2
    ]
    entries = [entry for entry in entries if entry[3] > 0]
    if not entries:
        return []
    chosen: list[tuple[float, float, float]] = []
    used = 0.0
    for start, end, _strength, seconds in sorted(entries, key=lambda item: (-item[2], item[0])):
        room = max_seconds - used
        if seconds <= room + 0.05:
            chosen.append((start, end, seconds))
            used += seconds
        elif not chosen and room >= MIN_MOMENT_SECONDS:
            # Nothing else fits and this beat is longer than the whole budget: its opening.
            ratio = room / seconds
            chosen.append((start, start + (end - start) * ratio, room))
            used += room
    chosen.sort()
    return [[round(start, 3), round(end, 3)] for start, end, _ in chosen]


# Share of a compilation's strength a shorter copy must keep to be worth recommending.
# Comedy and hype survive on the peaks; drama and teaching need their build-up.
KEEP_SHARE_BY_STYLE: dict[str, float] = {"humor": 0.5, "hype": 0.5, "drama": 0.75, "educational": 0.8}
DEFAULT_KEEP_SHARE = 0.65


def recommend_shorten(
    moments: Sequence[dict[str, Any]], style: str, choices: Sequence[int] = SHORTEN_CHOICES
) -> Optional[int]:
    """The shortest length that still keeps most of what makes the compilation work.

    Each length is simulated with ``shorten_ranges``; what counts is the share of the beats'
    strength-weighted airtime that survives. When no length keeps enough (long compilations
    whose beats are all strong) the longest choice is the best available. None only when the
    compilation is shorter than every choice.
    """
    weights: list[tuple[float, float, float]] = []
    for moment in moments:
        try:
            start, end = float(moment["range"][0]), float(moment["range"][1])
            weight = float(moment.get("seconds") or 0.0) * max(int(moment.get("strength") or 0), 1)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if end > start and weight > 0:
            weights.append((start, end, weight))
    total_weight = sum(weight for _, _, weight in weights)
    total_seconds = sum(float(m.get("seconds") or 0.0) for m in moments)
    if not weights or total_weight <= 0:
        return None
    need = KEEP_SHARE_BY_STYLE.get(style, DEFAULT_KEEP_SHARE)
    fitting = [seconds for seconds in sorted(choices) if seconds < total_seconds - 0.5]
    for seconds in fitting:
        kept = 0.0
        for a, b in shorten_ranges(moments, seconds):
            for start, end, weight in weights:
                overlap = min(b, end) - max(a, start)
                if overlap > 0:
                    kept += weight * overlap / (end - start)
        if kept / total_weight >= need:
            return seconds
    return fitting[-1] if fitting else None


def output_windows(
    source_ranges: Sequence[tuple[float, float]], offsets: Sequence[float], chosen: Sequence[Sequence[float]]
) -> list[tuple[float, float]]:
    """Where each chosen source range plays on the rendered clip's own timeline.

    ``source_ranges`` and ``offsets`` are the clip's source map. A beat that spans several
    source ranges (dead air was cut inside it) yields one window per range; touching
    windows are joined. Windows come back in playing order.
    """
    windows: list[tuple[float, float]] = []
    for start, end in chosen:
        for (a, b), offset in zip(source_ranges, offsets):
            low, high = max(a, start), min(b, end)
            if high - low > 0.05:
                windows.append((offset + low - a, offset + high - a))
    windows.sort()
    joined: list[tuple[float, float]] = []
    for low, high in windows:
        if joined and low - joined[-1][1] <= 0.05:
            joined[-1] = (joined[-1][0], max(joined[-1][1], high))
        else:
            joined.append((low, high))
    return joined


# -- model passes ----------------------------------------------------------------------------


def _listing_chars(index: UnitIndex) -> int:
    return sum(len(unit.text) + 12 for unit in index.units)


async def _discover(pi: PlanInput) -> SubjectDiscovery:
    """Find the subjects. The first try reads the whole transcript; when the provider keeps failing
    (overloaded models answer 503 to big requests) it waits and asks again with the outline alone."""
    index = pi.index
    outline = outline_block(pi.outline.outline, index, include=("chapters", "points", "topics"))
    materials = []
    if _listing_chars(index) <= FULL_LISTING_MAX_CHARS:
        materials.append(outline + "\n\n" + transcript_block(index.listing(with_durations=False)))
    materials.append(outline)
    agent = build_agent(SubjectDiscovery, subjects_discover_system(pi.language_name), structural=True)
    last_error: Optional[BaseException] = None
    for position, material in enumerate(materials):
        prompt = with_instructions(material, pi.instructions)
        try:
            result = await run_retrying(
                lambda: run(agent, prompt, stats=pi.stats, stage="subjects_discover"),
                attempts=DISCOVER_ATTEMPTS,
                label="subjects discover",
            )
            if position:
                pi.stats.fallbacks.append("SUBJECTS_DISCOVERED_FROM_OUTLINE")
            return result.output
        except Exception as error:
            if is_cancellation(error):
                raise
            last_error = error
            logger.error("Subjects discovery failed (%s); %s", type(error).__name__,
                         "trying the outline alone" if position + 1 < len(materials) else "giving up")
            if position + 1 < len(materials):
                await asyncio.sleep(DISCOVER_BACKOFF_SECONDS)
    raise WorkflowError("plan_failed", _PLAN_FAILED) from last_error


async def _extract(
    pi: PlanInput, subjects: Sequence[Any], windows: list[list[int]]
) -> list[tuple[list[int], SubjectExtraction]]:
    """Every window read with the subject list. A window that still fails after its retries is left
    out (a compilation just has one stretch fewer); too many failing means the video wasn't read."""
    agent = build_agent(SubjectExtraction, subjects_extract_system(pi.language_name), structural=False)
    semaphore = asyncio.Semaphore(EXTRACT_CONCURRENCY)
    listing = subjects_block(subjects)

    async def extract(window: list[int]) -> Optional[tuple[list[int], SubjectExtraction]]:
        prompt = with_instructions(listing + "\n\n" + transcript_block(pi.index.listing(window)), pi.instructions)
        try:
            async with semaphore:
                result = await run_retrying(
                    lambda: run(agent, prompt, stats=pi.stats, stage="subjects_extract"),
                    attempts=EXTRACT_ATTEMPTS,
                    label="subjects window",
                )
        except Exception as error:
            if is_cancellation(error):
                raise
            logger.error("Subjects window #%d-#%d failed (%s)", window[0], window[-1], type(error).__name__)
            return None
        return window, result.output

    try:
        results = await asyncio.gather(*[extract(window) for window in windows])
    except Exception as error:
        if is_cancellation(error):
            raise
        logger.error("Subjects extraction failed (%s)", type(error).__name__)
        raise WorkflowError("analysis_incomplete", "We couldn't read the whole video. Please try again.") from error
    read = [item for item in results if item is not None]
    failed = len(results) - len(read)
    if failed and (not read or failed > max(1, len(results) // 4)):
        raise WorkflowError("analysis_incomplete", "We couldn't read the whole video. Please try again.")
    if failed:
        pi.note("SUBJECTS_WINDOWS_SKIPPED", {"skipped": failed, "total": len(results)})
    return read


# -- entry point ---------------------------------------------------------------------------------


async def plan_subjects(pi: PlanInput) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    index = pi.index
    await pi.ctx.progress(54, "Finding the subjects that keep coming back...")
    discovery = await _discover(pi)
    subjects = [
        subject for subject in discovery.subjects if subject.label.strip() and subject.virality >= MIN_SUBJECT_VIRALITY
    ][:MAX_SUBJECTS]
    if not subjects:
        raise subjects_not_found()

    windows = pack_windows(index, [(1, len(index))], WINDOW_SECONDS)
    await pi.ctx.progress(58, "Gathering every moment of each subject...")
    extractions = await _extract(pi, subjects, windows)
    beats = [
        beat
        for window, extraction in extractions
        for beat in gate_beats(index, extraction.moments, window, len(subjects), pi.cleanup)
    ]
    beats = resolve_beats(beats)

    compilations: list[tuple[int, list[Beat]]] = []
    for number in range(1, len(subjects) + 1):
        own = cap_subject(join_scenes([beat for beat in beats if beat.subject == number], index, pi.cleanup))
        if sum(beat.seconds for beat in own) >= MIN_SUBJECT_SECONDS:
            compilations.append((number, own))
    if not compilations:
        raise subjects_not_found()

    # Most viral first: the model's rating of the subject, blended with how strong its beats really are.
    def rank(item: tuple[int, list[Beat]]) -> tuple[float, int]:
        number, own = item
        strength = sum(beat.strength * beat.seconds for beat in own) / sum(beat.seconds for beat in own)
        return (-(0.5 * _clamp(subjects[number - 1].virality, 0, 100) + 0.5 * strength), number)

    compilations.sort(key=rank)
    limit = pi.setting("max_clips")
    if limit is not None:
        compilations = compilations[: int(limit)]
    if index.coarse:
        pi.note("COARSE_TRANSCRIPT")

    segments = [_segment(pi, subjects[number - 1], own) for number, own in compilations]
    plan = base_plan(pi, title="By subject")
    plan["subjects"] = [
        {
            "label": " ".join(subjects[number - 1].label.split()),
            "description": " ".join(subjects[number - 1].description.split()),
            "moments": len(own),
            "seconds": round(sum(beat.seconds for beat in own), 1),
            "virality": _clamp(subjects[number - 1].virality, 0, 100),
        }
        for number, own in compilations
    ]
    plan["shorten_choices"] = list(SHORTEN_CHOICES)
    return segments, plan


def _segment(pi: PlanInput, subject: Any, beats: Sequence[Beat]) -> dict[str, Any]:
    index = pi.index
    style = str(pi.setting("style") or "auto")
    ranges: list[tuple[float, float]] = []
    fades: list[float] = []
    moments: list[dict[str, Any]] = []
    played_total = 0.0
    for beat in beats:
        beat_ranges = index.ranges_for(beat.first, beat.last)
        if ranges:
            fades.append(PART_JUNCTION_FADE)
        fades.extend([PART_JUNCTION_FADE] * (len(beat_ranges) - 1))
        ranges.extend(beat_ranges)
        start, end = index.range_seconds(beat.first, beat.last)
        played = sum(b - a for a, b in beat_ranges)
        played_total += played
        moments.append(
            {
                "range": [round(start, 3), round(end, 3)],
                "first_unit": beat.first,
                "last_unit": beat.last,
                "strength": beat.strength,
                "seconds": round(played, 1),
                "title": beat.title,
            }
        )
    # What actually plays: the ranges keep the pauses inside a beat, so it runs longer than its speech.
    total = played_total
    label = " ".join(subject.label.split())
    recommended = recommend_shorten(moments, style)
    return planned_segment(
        ranges=ranges,
        junction_fades=fades,
        max_seconds=total + RENDER_PADDING_SECONDS,
        required=False,
        text=" ".join(index.text(beat.first, beat.last) for beat in beats),
        hook_title=compose_title(label),
        reasoning=" ".join(subject.description.split()),
        workflow_role="subject",
        meta={
            "subject": label,
            "moments": moments,
            "moment_count": len(beats),
            **({"style": style} if style != "auto" else {}),
            **({"recommended_shorten": recommended} if recommended else {}),
        },
        relevance_score=sum(beat.strength for beat in beats) / (100 * len(beats)),
    )
