"""Panels of a custom layout that follow a face or the person speaking.

A panel with ``follow`` set keeps its crop size but its position moves:

- ``face``: the crop stays centred on the face that starts closest to where the
  user placed it, however the person moves.
- ``speaker``: the crop jumps to whichever visible face moves its mouth the
  most (the person talking), holding each choice for a minimum time so it does
  not flicker.

Both reuse the low-resolution face and motion analysis of ``speaker_framing``.
The result is a pair of ffmpeg expressions (x and y of the crop) per panel.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .common import logger
from .ffmpeg import clamp_even, round_to_even
from .speaker_framing import analyze_speaker_clip, build_crop_x_expression

FOLLOW_MODES = ("none", "face", "speaker")
KEY_EVERY_SECONDS = 0.6
SWITCH_MIN_HOLD_SECONDS = 1.2
SWITCH_ADVANTAGE = 1.4
SWITCH_RAMP_SECONDS = 0.25
MAX_JUMP_FRACTION = 0.45

Face = Tuple[float, float, float, float]


def _centre(face: Face) -> Tuple[float, float]:
    return face[0] + face[2] / 2, face[1] + face[3] / 2


def _activity(analysis: Dict[str, Any], face: Face, t: float) -> float:
    """Mean frame-to-frame change around the lower part of a face (mouth area)."""
    motion = analysis["motion"]
    fps = analysis["motion_fps"]
    cell = analysis["motion_cell"]
    a, b = max(0, int((t - 0.5) * fps)), min(len(motion), int((t + 0.5) * fps) + 1)
    if b <= a:
        return 0.0
    x0, x1 = int(face[0] / cell), max(int(face[0] / cell) + 1, int((face[0] + face[2]) / cell))
    y0 = int((face[1] + face[3] * 0.45) / cell)
    y1 = max(y0 + 1, int((face[1] + face[3] * 1.1) / cell))
    region = motion[a:b, y0:y1, x0:x1]
    return float(region.mean()) if region.size else 0.0


BODY_DROP_FACES = 1.4


def track_centres(
    analysis: Dict[str, Any], mode: str, start: Tuple[float, float], max_jump: float, max_drop: float
) -> List[Tuple[float, float, float]]:
    """(time, centre x, centre y) keyframes for one panel.

    The crop is centred on the person's body, not the face: the centre sits
    below the face by ``BODY_DROP_FACES`` face heights (limited to ``max_drop``),
    so the face stays in the upper part and the shoulders and torso are shown.
    """
    samples = analysis["face_samples"]
    keys: List[Tuple[float, float, float]] = []
    anchor = start
    drop = 0.0
    held_since = -1e9
    last_key = -1e9
    for t, faces in samples:
        if faces:
            near = min(faces, key=lambda f: (_centre(f)[0] - anchor[0]) ** 2 + (_centre(f)[1] - anchor[1]) ** 2)
            target = near
            if mode == "speaker" and len(faces) > 1:
                best = max(faces, key=lambda f: _activity(analysis, f, t))
                current = _activity(analysis, near, t)
                if (
                    best is not near
                    and t - held_since >= SWITCH_MIN_HOLD_SECONDS
                    and _activity(analysis, best, t) > max(current, 1e-3) * SWITCH_ADVANTAGE
                ):
                    target = best
                    held_since = t
            cx, cy = _centre(target)
            new_drop = min(max_drop, target[3] * BODY_DROP_FACES)
            # A face far from the last position is another person, not movement.
            if mode == "face" and abs(cx - anchor[0]) > max_jump:
                cx, cy = anchor
            anchor = (cx, cy)
            drop = new_drop
        if t - last_key >= KEY_EVERY_SECONDS or not keys:
            keys.append((t, anchor[0], anchor[1] + drop))
            last_key = t
    return keys


def _pieces(keys: List[Tuple[float, float]], hold_switches: bool) -> List[Tuple[float, float, float, float]]:
    pieces: List[Tuple[float, float, float, float]] = []
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if hold_switches and abs(v1 - v0) > 1:
            ramp_start = max(t0, t1 - SWITCH_RAMP_SECONDS)
            if ramp_start > t0:
                pieces.append((t0, ramp_start, v0, v0))
            pieces.append((ramp_start, t1, v0, v1))
        else:
            pieces.append((t0, t1, v0, v1))
    return pieces


def plan_follow(input_path: Path, width: int, height: int, spec: Dict[str, Any]) -> Dict[int, Dict[str, str]]:
    """Crop x/y expressions for every panel that follows a face or the speaker."""
    panels = spec.get("panels") or []
    wanted = [i for i, panel in enumerate(panels) if panel.get("follow") in ("face", "speaker")]
    if not wanted or width <= 0 or height <= 0:
        return {}
    try:
        analysis = analyze_speaker_clip(input_path, width, height)
    except Exception as exc:
        logger.warning("Layout follow analysis failed: %s", exc)
        return {}
    if not analysis or not analysis["face_samples"]:
        return {}
    plans: Dict[int, Dict[str, str]] = {}
    for i in wanted:
        panel = panels[i]
        crop = panel["crop"]
        cw = clamp_even(int(round(crop["w"] * width)), 2, round_to_even(width))
        ch = clamp_even(int(round(crop["h"] * height)), 2, round_to_even(height))
        start = ((crop["x"] + crop["w"] / 2) * width, (crop["y"] + crop["h"] / 2) * height)
        # Start the match from the face, which sits above the crop centre.
        mode = panel["follow"]
        keys = track_centres(analysis, mode, start, width * MAX_JUMP_FRACTION, ch * 0.25)
        if len(keys) < 2:
            continue
        max_x, max_y = max(0, width - cw), max(0, height - ch)
        xs = [(t, float(np.clip(cx - cw / 2, 0, max_x))) for t, cx, _ in keys]
        ys = [(t, float(np.clip(cy - ch / 2, 0, max_y))) for t, _, cy in keys]
        hold = mode == "speaker"
        plans[i] = {
            "x": build_crop_x_expression(_pieces(xs, hold)),
            "y": build_crop_x_expression(_pieces(ys, hold)),
        }
        logger.info("Layout panel %d follows the %s (%d keyframes)", i + 1, mode, len(keys))
    return plans
