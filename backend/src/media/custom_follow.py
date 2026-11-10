"""Panels of a custom layout that follow a face or the person speaking.

A panel with ``follow`` set keeps its crop size but its position moves:

- ``face``: the crop stays on the face that starts closest to where the user
  placed it.
- ``speaker``: the crop cuts to whichever visible face moves its mouth the most
  (the person talking), holding each choice for a minimum time.

The camera is steady: it only moves when the person leaves a dead zone around
the crop centre (then it eases after them), and it cuts quickly when the
speaker changes. The eyes are placed on a fixed line near the top third of the
panel, so the face sits high and the body fills the rest.

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
SWITCH_MIN_HOLD_SECONDS = 1.0
SWITCH_ADVANTAGE = 1.25
SWITCH_RAMP_SECONDS = 0.25
DRIFT_RAMP_SECONDS = 0.6
MAX_JUMP_FRACTION = 0.45
EYE_LINE = 0.34  # eyes sit this fraction of the panel height from its top
EYE_IN_FACE = 0.4  # eye line as a fraction of the face box height
DEAD_X = 0.12  # of the crop width
DEAD_Y = 0.10  # of the crop height
SMOOTH_SAMPLES = 5

Face = Tuple[float, float, float, float]


def _centre(face: Face) -> Tuple[float, float]:
    return face[0] + face[2] / 2, face[1] + face[3] / 2


def _activity(analysis: Dict[str, Any], face: Face, t: float) -> float:
    """Mouth movement around a face, ignoring whole-head movement."""
    motion = analysis["motion"]
    fps = analysis["motion_fps"]
    cell = analysis["motion_cell"]
    a, b = max(0, int((t - 0.5) * fps)), min(len(motion), int((t + 0.5) * fps) + 1)
    if b <= a:
        return 0.0
    x0, x1 = max(0, int(face[0] / cell)), max(int(face[0] / cell) + 1, int((face[0] + face[2]) / cell))

    def band(top: float, bottom: float) -> float:
        y0 = max(0, int((face[1] + face[3] * top) / cell))
        y1 = max(y0 + 1, int((face[1] + face[3] * bottom) / cell))
        region = motion[a:b, y0:y1, x0:x1]
        return float(region.mean()) if region.size else 0.0

    # Moving the whole head shows in the forehead too; only the mouth moves on its own.
    mouth = band(0.6, 1.05) - 0.6 * band(0.0, 0.4)
    # Nearer people (bigger faces) are usually the ones on the microphone.
    return max(0.0, mouth) * float(face[3]) ** 0.5


def pick_targets(
    analysis: Dict[str, Any], mode: str, start: Tuple[float, float], max_jump: float
) -> List[Tuple[float, float, float, bool]]:
    """(time, eye x, eye y, switched) for the person to frame at each sample."""
    anchor = start
    held_since = -1e9
    out: List[Tuple[float, float, float, bool]] = []
    eye = (start[0], start[1])
    for t, faces in analysis["face_samples"]:
        switched = False
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
                    switched = True
            cx, cy = _centre(target)
            # A face far from the last position is another person, not movement.
            if mode == "face" and abs(cx - anchor[0]) > max_jump:
                cx, cy = anchor
                target = near
            anchor = (cx, cy)
            eye = (cx, target[1] + target[3] * EYE_IN_FACE)
        out.append((t, eye[0], eye[1], switched))
    return out


def _median(values: List[float], size: int = SMOOTH_SAMPLES) -> List[float]:
    half = size // 2
    return [float(np.median(values[max(0, i - half): i + half + 1])) for i in range(len(values))]


def steady_camera(
    targets: List[Tuple[float, float, float, bool]], cw: int, ch: int
) -> List[Tuple[float, float, float, float, bool]]:
    """(time, crop centre x, crop centre y, ramp seconds, cut) keyframes.

    The camera holds still while the eyes stay inside a dead zone, eases after
    them when they leave it, and cuts when the speaker changes.
    """
    if not targets:
        return []
    ts = [t for t, _, _, _ in targets]
    # Smooth each stretch between speaker changes separately so a cut stays sharp.
    xs, ys = [], []
    start = 0
    for i in range(1, len(targets) + 1):
        if i == len(targets) or targets[i][3]:
            xs += _median([targets[j][1] for j in range(start, i)])
            ys += _median([targets[j][2] for j in range(start, i)])
            start = i
    dead_x, dead_y = DEAD_X * cw, DEAD_Y * ch
    keys: List[Tuple[float, float, float, float, bool]] = []
    # The eye line sits EYE_LINE down the panel, so the crop centre is below the eyes.
    drop = (0.5 - EYE_LINE) * ch
    cam_x, cam_y = xs[0], ys[0] + drop
    keys.append((ts[0], cam_x, cam_y, 0.0, False))
    for i in range(1, len(targets)):
        want_x, want_y = xs[i], ys[i] + drop
        cut = targets[i][3]
        if cut:
            cam_x, cam_y = want_x, want_y
            keys.append((ts[i], cam_x, cam_y, SWITCH_RAMP_SECONDS, True))
            continue
        moved = False
        if abs(want_x - cam_x) > dead_x:
            cam_x = want_x - dead_x * 0.5 * np.sign(want_x - cam_x)
            moved = True
        if abs(want_y - cam_y) > dead_y:
            cam_y = want_y - dead_y * 0.5 * np.sign(want_y - cam_y)
            moved = True
        if moved:
            keys.append((ts[i], float(cam_x), float(cam_y), DRIFT_RAMP_SECONDS, False))
    keys.append((ts[-1] + 0.5, keys[-1][1], keys[-1][2], 0.0, False))
    return keys


def _pieces(keys: List[Tuple[float, float, float, bool]]) -> List[Tuple[float, float, float, float]]:
    """Linear pieces (start, end, v0, v1): hold, then ease over the key's ramp."""
    pieces: List[Tuple[float, float, float, float]] = []
    for (t0, v0, _, _), (t1, v1, ramp, _) in zip(keys, keys[1:]):
        ramp_start = max(t0, t1 - ramp)
        if ramp_start > t0:
            pieces.append((t0, ramp_start, v0, v0))
        pieces.append((ramp_start, t1, v0, v1) if t1 > ramp_start else (t0, t1, v0, v1))
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
        mode = panel["follow"]
        targets = pick_targets(analysis, mode, start, width * MAX_JUMP_FRACTION)
        keys = steady_camera(targets, cw, ch)
        if len(keys) < 2:
            continue
        max_x, max_y = max(0, width - cw), max(0, height - ch)
        xs = [(t, float(np.clip(cx - cw / 2, 0, max_x)), ramp, cut) for t, cx, _, ramp, cut in keys]
        ys = [(t, float(np.clip(cy - ch / 2, 0, max_y)), ramp, cut) for t, _, cy, ramp, cut in keys]
        plans[i] = {
            "x": build_crop_x_expression(_pieces(xs)),
            "y": build_crop_x_expression(_pieces(ys)),
        }
        logger.info("Layout panel %d follows the %s (%d camera moves)", i + 1, mode, len(keys))
    return plans
