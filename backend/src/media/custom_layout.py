"""User-made vertical layouts: one or two panels, each a crop of the source.

A layout is a small JSON spec the user draws on the layout page::

    {"version": 1,
     "panels": [{"crop": {"x": .72, "y": .60, "w": .26, "h": .36}, "height": .35},
                {"crop": {"x": 0, "y": 0, "w": 1, "h": 1}, "height": .65}],
     "caption_y": 0.5}

``crop`` is a rectangle of the source frame as fractions of its width and
height. ``height`` is the share of the 9:16 output the panel takes, top to
bottom. Panels always fill the full output width. A crop whose shape differs from
its panel is centre-cropped to fit, so the page draws crops in the panel's shape
and the render shows exactly what was drawn.
"""

from typing import Any, Dict, List, Optional

from .common import UPSCALE_SHARPEN_FILTER
from .ffmpeg import clamp_even, round_to_even

OUT_W, OUT_H = 1080, 1920
MAX_PANELS = 2
MIN_PANEL_SHARE = 0.15
MIN_CROP = 0.02


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number")
    return value


def normalize_layout_spec(raw: Any) -> Dict[str, Any]:
    """Validate a spec from a client and return it in canonical form."""
    if not isinstance(raw, dict):
        raise ValueError("layout spec must be an object")
    panels_raw = raw.get("panels")
    if not isinstance(panels_raw, list) or not 1 <= len(panels_raw) <= MAX_PANELS:
        raise ValueError(f"layout needs 1 to {MAX_PANELS} panels")
    panels: List[Dict[str, Any]] = []
    for index, item in enumerate(panels_raw):
        if not isinstance(item, dict) or not isinstance(item.get("crop"), dict):
            raise ValueError(f"panel {index + 1} needs a crop")
        crop = item["crop"]
        x, y, w, h = (_number(crop.get(k), f"panel {index + 1} crop.{k}") for k in "xywh")
        if not (0 <= x < 1 and 0 <= y < 1 and MIN_CROP <= w <= 1 and MIN_CROP <= h <= 1):
            raise ValueError(f"panel {index + 1} crop is out of range")
        if x + w > 1.0001 or y + h > 1.0001:
            raise ValueError(f"panel {index + 1} crop leaves the frame")
        # The second panel's share is whatever the first leaves, so it may be omitted.
        if len(panels_raw) == 1 or (index == 1 and item.get("height") is None):
            share = 1.0 if len(panels_raw) == 1 else 0.0
        else:
            share = _number(item.get("height"), f"panel {index + 1} height")
        panels.append({
            "crop": {"x": x, "y": y, "w": min(w, 1 - x), "h": min(h, 1 - y)},
            "height": share,
        })
    if len(panels) == 2:
        first = panels[0]["height"]
        if not MIN_PANEL_SHARE <= first <= 1 - MIN_PANEL_SHARE:
            raise ValueError("each panel needs between 15% and 85% of the height")
        panels[1]["height"] = 1 - first
    caption_y = raw.get("caption_y")
    if caption_y is not None:
        caption_y = _number(caption_y, "caption_y")
        if not 0.1 <= caption_y <= 0.9:
            raise ValueError("caption_y must be between 0.1 and 0.9")
    return {"version": 1, "panels": panels, "caption_y": caption_y}


def panel_heights(spec: Dict[str, Any]) -> List[int]:
    """Output pixel height of every panel; the last takes the rounding slack."""
    panels = spec["panels"]
    if len(panels) == 1:
        return [OUT_H]
    first = min(OUT_H - 2, max(2, round_to_even(int(round(panels[0]["height"] * OUT_H)))))
    return [first, OUT_H - first]


def build_custom_layout(width: int, height: int, spec: Dict[str, Any]) -> Dict[str, Any]:
    """The ffmpeg filter graph (``[vout]``) for a normalized spec."""
    heights = panel_heights(spec)
    panels = spec["panels"]
    n = len(panels)
    graph: List[str] = []
    if n == 2:
        graph.append("[0:v]split=2[s0][s1]")
    for i, (panel, ph) in enumerate(zip(panels, heights)):
        crop = panel["crop"]
        cw = clamp_even(int(round(crop["w"] * width)), 2, round_to_even(width))
        ch = clamp_even(int(round(crop["h"] * height)), 2, round_to_even(height))
        cx = clamp_even(int(round(crop["x"] * width)), 0, max(0, width - cw))
        cy = clamp_even(int(round(crop["y"] * height)), 0, max(0, height - ch))
        source = f"[s{i}]" if n == 2 else "[0:v]"
        graph.append(
            f"{source}crop={cw}:{ch}:{cx}:{cy},"
            f"scale={OUT_W}:{ph}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={OUT_W}:{ph},{UPSCALE_SHARPEN_FILTER},setsar=1[p{i}]"
        )
    graph.append(
        "[p0][p1]vstack=inputs=2[vout]" if n == 2 else "[p0]null[vout]"
    )
    caption_y: Optional[float] = spec.get("caption_y")
    if caption_y is None:
        caption_y = heights[0] / OUT_H if n == 2 else 0.8
    return {
        "kind": "custom",
        "video_filter": ";".join(graph),
        "caption_y": caption_y,
        "heights": heights,
    }
