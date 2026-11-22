"""Layout ``duo``: split screen while two people are on screen, else follow the speaker.

- Two people in the shot: the frame is split top and bottom, the person on the
  left above, the person on the right below, each panel staying on its face.
- One person (or nobody found): a single 9:16 crop that follows who is talking.

Both pictures are built for the whole clip and an overlay switches between
them, so each keeps a steady camera of its own. Switches are held for a
minimum time so a face missed for a moment does not flicker the layout.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .common import UPSCALE_SHARPEN_FILTER, logger
from .custom_follow import MAIN_FACE_RATIO, follow_expressions
from .custom_layout import OUT_H, OUT_W
from .ffmpeg import clamp_even, round_to_even
from .speaker_framing import analyze_speaker_clip

MIN_HOLD_SECONDS = 1.5
SMOOTH_SAMPLES = 5
PANEL_FACE_HEIGHTS = 3.5  # a split panel shows about this many face heights
MIN_PANEL_CROP = 0.5  # of the source height
MIN_SEPARATION = 0.12  # of the source width, between the two faces

Face = Tuple[float, float, float, float]


def _main_faces(faces: Sequence[Face]) -> List[Face]:
    if not faces:
        return []
    biggest = max(f[3] for f in faces)
    return sorted((f for f in faces if f[3] >= MAIN_FACE_RATIO * biggest), key=lambda f: f[0])


def _pair(faces: Sequence[Face], width: int) -> Optional[Tuple[Face, Face]]:
    """The left-most and right-most main faces when they are two different people."""
    main = _main_faces(faces)
    if len(main) < 2:
        return None
    left, right = main[0], main[-1]
    gap = (right[0] + right[2] / 2) - (left[0] + left[2] / 2)
    return (left, right) if gap >= MIN_SEPARATION * width else None


def two_people_intervals(
    times: Sequence[float], flags: Sequence[bool], end: float
) -> List[Tuple[float, float]]:
    """(start, end) spans with two people, smoothed and held for a minimum time."""
    if not times:
        return []
    half = SMOOTH_SAMPLES // 2
    smooth = [
        sum(flags[max(0, i - half): i + half + 1]) * 2 > len(flags[max(0, i - half): i + half + 1])
        for i in range(len(flags))
    ]
    # Runs of equal state as [state, start, end].
    runs: List[List[Any]] = []
    for i, state in enumerate(smooth):
        stop = times[i + 1] if i + 1 < len(times) else max(end, times[i])
        if runs and runs[-1][0] == state:
            runs[-1][2] = stop
        else:
            runs.append([state, times[i], stop])
    runs[0][1] = 0.0
    # A run too short to read joins the one before it (the first joins the next).
    merged: List[List[Any]] = []
    for run in runs:
        if merged and (run[2] - run[1] < MIN_HOLD_SECONDS or merged[-1][0] == run[0]):
            merged[-1][2] = run[2]
        else:
            merged.append(run)
    if len(merged) > 1 and merged[0][2] - merged[0][1] < MIN_HOLD_SECONDS:
        merged[1][1] = merged[0][1]
        merged.pop(0)
    return [(float(a), float(b)) for state, a, b in merged if state]


def _panel(label: str, cw: int, ch: int, plan: Optional[Dict[str, str]], x: int, y: int, out_h: int, out: str) -> str:
    position = f"x='{plan['x']}':y='{plan['y']}'" if plan else f"{x}:{y}"
    return (
        f"[{label}]crop={cw}:{ch}:{position},"
        f"scale={OUT_W}:{out_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={OUT_W}:{out_h},{UPSCALE_SHARPEN_FILTER},setsar=1[{out}]"
    )


def build_duo_layout(input_path: Path, width: int, height: int, duration: float) -> Optional[Dict[str, Any]]:
    """Filter graph (``[vout]``) and caption position, or None when no face is found."""
    if width <= 0 or height <= 0:
        return None
    try:
        analysis = analyze_speaker_clip(input_path, width, height)
    except Exception as exc:
        logger.warning("Duo layout analysis failed: %s", exc)
        return None
    if not analysis or not analysis["face_samples"]:
        return None
    samples = analysis["face_samples"]
    times = [t for t, _ in samples]
    pairs = [_pair(faces, width) for _, faces in samples]
    if not any(faces for _, faces in samples):
        return None
    split = two_people_intervals(times, [p is not None for p in pairs], duration)
    split_seconds = sum(b - a for a, b in split)

    # One person: a full-height 9:16 crop on whoever is talking.
    one_w = clamp_even(int(round(height * OUT_W / OUT_H)), 2, round_to_even(width))
    one_h = round_to_even(height) if height % 2 == 0 else height - 1
    one_plan = follow_expressions(
        analysis, "speaker", (width / 2, height / 2), one_w, one_h, width, height
    ) if one_w < width else None
    one_x = clamp_even((width - one_w) // 2, 0, max(0, width - one_w))

    if not split:
        graph = [_panel("0:v", one_w, one_h, one_plan, one_x, 0, OUT_H, "vout")]
        logger.info("Duo layout: one person throughout, following the speaker")
        return {"video_filter": ";".join(graph), "caption_y": None, "split_seconds": 0.0}

    # Two people: each panel stays on its own face (left above, right below).
    found = [p for p in pairs if p is not None]
    panel_h_out = OUT_H // 2
    aspect = OUT_W / panel_h_out
    face_h = float(np.median([f[3] for pair in found for f in pair]))
    crop_h = min(max(face_h * PANEL_FACE_HEIGHTS, MIN_PANEL_CROP * height), height, (width / 2) / aspect)
    ch = clamp_even(int(round(crop_h)), 2, round_to_even(height))
    cw = clamp_even(int(round(ch * aspect)), 2, round_to_even(width))
    panels: List[Tuple[Optional[Dict[str, str]], int, int]] = []
    for side in (0, 1):
        own = dict(analysis)
        own["face_samples"] = [(t, [pair[side]] if pair else []) for (t, _), pair in zip(samples, pairs)]
        cx = float(np.median([pair[side][0] + pair[side][2] / 2 for pair in found]))
        cy = float(np.median([pair[side][1] + pair[side][3] / 2 for pair in found]))
        plan = follow_expressions(own, "face", (cx, cy), cw, ch, width, height)
        x = clamp_even(int(round(cx - cw / 2)), 0, max(0, width - cw))
        y = clamp_even(int(round(cy - ch / 2)), 0, max(0, height - ch))
        panels.append((plan, x, y))

    always_split = split_seconds >= duration - 0.5 and len(split) == 1
    graph = [f"[0:v]split={2 if always_split else 3}[d0][d1]" + ("" if always_split else "[d2]")]
    graph.append(_panel("d0", cw, ch, panels[0][0], panels[0][1], panels[0][2], panel_h_out, "dt"))
    graph.append(_panel("d1", cw, ch, panels[1][0], panels[1][1], panels[1][2], panel_h_out, "db"))
    if always_split:
        graph.append("[dt][db]vstack=inputs=2[vout]")
    else:
        graph.append("[dt][db]vstack=inputs=2[dtwo]")
        graph.append(_panel("d2", one_w, one_h, one_plan, one_x, 0, OUT_H, "done"))
        enable = "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in split)
        graph.append(f"[done][dtwo]overlay=0:0:enable='{enable}'[vout]")
    logger.info("Duo layout: split screen for %.1fs of %.1fs (%d spans)", split_seconds, duration, len(split))
    return {
        "video_filter": ";".join(graph),
        # Between the panels when the split leads, the template default otherwise.
        "caption_y": 0.5 if split_seconds >= duration / 2 else None,
        "split_seconds": split_seconds,
    }
