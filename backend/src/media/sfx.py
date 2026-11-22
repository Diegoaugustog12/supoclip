"""Sound effects for styled workflow clips.

The sounds are synthesised by ffmpeg (no files, no licences) and mixed under
the finished clip's audio in one pass, copying the picture. A styled clip
places them from its planned beats: ``whoosh`` where one beat hands over to the next,
and for comedy a ``ding`` as the beat's last line lands. The mix is optional:
if it fails the clip is kept as rendered.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

# lavfi source for each sound, and the gain it is mixed at.
SOUNDS: dict[str, tuple[str, float]] = {
    "whoosh": (
        "anoisesrc=d=0.4:c=pink:a=0.6,highpass=f=400,lowpass=f=3500,afade=t=in:d=0.15,afade=t=out:st=0.15:d=0.25",
        0.55,
    ),
    "ding": ("sine=f=1568:d=0.6,afade=t=out:st=0.05:d=0.55", 0.35),
    "impact": ("sine=f=70:d=0.45,afade=t=out:st=0.03:d=0.42", 0.9),
}

# Which sounds each style uses: (at a beat's start, at its end).
STYLE_SOUNDS: dict[str, tuple[Optional[str], Optional[str]]] = {
    "humor": ("whoosh", "ding"),
    "hype": ("whoosh", None),
}
# A sound never lands closer than this to another, or to the clip's start.
MIN_GAP_SECONDS = 0.6
START_GUARD_SECONDS = 0.3
MAX_CUES = 40


def _output_time(source_time: float, keep_ranges: Sequence[tuple[float, float]], offsets: Sequence[float]) -> Optional[float]:
    """Where a source time plays on the clip, or None when it was cut."""
    for (start, end), offset in zip(keep_ranges, offsets):
        if start - 0.05 <= source_time <= end + 0.05:
            return offset + min(max(source_time, start), end) - start
    return None


def sfx_cues(
    meta: Optional[dict[str, Any]],
    keep_ranges: Sequence[tuple[float, float]],
    offsets: Sequence[float],
) -> list[dict[str, Any]]:
    """Cues ({"kind", "time"} on the clip timeline) for a styled subject clip, else []."""
    if not isinstance(meta, dict):
        return []
    sounds = STYLE_SOUNDS.get(str(meta.get("style") or ""))
    moments = meta.get("moments")
    if not sounds or not isinstance(moments, list) or not keep_ranges or len(offsets) != len(keep_ranges):
        return []
    at_start, at_end = sounds
    cues: list[tuple[float, str]] = []
    for position, moment in enumerate(moments):
        try:
            begin, finish = float(moment["range"][0]), float(moment["range"][1])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if at_start and position > 0:
            when = _output_time(begin, keep_ranges, offsets)
            if when is not None:
                cues.append((max(0.0, when - 0.15), at_start))
        if at_end:
            when = _output_time(finish, keep_ranges, offsets)
            if when is not None:
                cues.append((max(0.0, when - 0.1), at_end))
    cues.sort()
    kept: list[dict[str, Any]] = []
    last = -MIN_GAP_SECONDS
    for when, kind in cues:
        if when < START_GUARD_SECONDS or when - last < MIN_GAP_SECONDS:
            continue
        kept.append({"kind": kind, "time": round(when, 3)})
        last = when
    return kept[:MAX_CUES]


def apply_sfx(clip_path: Path, cues: Sequence[dict[str, Any]]) -> bool:
    """Mix the cues into ``clip_path`` in place. False (clip untouched) on any failure."""
    cues = [cue for cue in cues if cue.get("kind") in SOUNDS]
    if not cues:
        return False
    command: list[str] = ["ffmpeg", "-y", "-i", str(clip_path)]
    graph: list[str] = []
    labels: list[str] = []
    for number, cue in enumerate(cues, start=1):
        source, gain = SOUNDS[cue["kind"]]
        command += ["-f", "lavfi", "-i", source]
        delay = max(0, int(round(float(cue["time"]) * 1000)))
        graph.append(f"[{number}:a]volume={gain},adelay={delay}|{delay}[s{number}]")
        labels.append(f"[s{number}]")
    graph.append(
        "[0:a]" + "".join(labels) + f"amix=inputs={len(cues) + 1}:normalize=0:dropout_transition=0:duration=first[a]"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="supoclip_sfx_") as temp_dir:
            mixed = Path(temp_dir) / "mixed.mp4"
            result = subprocess.run(
                [
                    *command,
                    "-filter_complex", ";".join(graph),
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(mixed),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0 or not mixed.exists() or mixed.stat().st_size == 0:
                logger.warning("Sound effects mix failed; keeping the clip as rendered: %s", result.stderr[-400:])
                return False
            shutil.move(str(mixed), str(clip_path))
        return True
    except Exception:
        logger.warning("Sound effects mix failed; keeping the clip as rendered", exc_info=True)
        return False
