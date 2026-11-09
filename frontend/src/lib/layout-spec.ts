/**
 * The layout page's model. Mirrors backend/src/media/custom_layout.py: a layout is
 * one or two panels stacked top to bottom, each showing a crop of the source.
 * Crops are fractions of the frame. A crop is always drawn in the shape of its
 * panel, so what the page shows is what the render produces.
 */

export const OUT_W = 1080;
export const OUT_H = 1920;
export const MIN_SHARE = 0.15;
export const MIN_CROP_W = 0.08;

export type Crop = { x: number; y: number; w: number; h: number };
export type PanelCount = 1 | 2;
export type LayoutSpec = {
  version: 1;
  panels: { crop: Crop; height: number }[];
  caption_y: number | null;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** Output pixel height of each panel; the last takes the rounding slack (all even, like the render). */
export function panelHeights(count: PanelCount, firstShare: number): number[] {
  if (count === 1) return [OUT_H];
  const share = clamp(firstShare, MIN_SHARE, 1 - MIN_SHARE);
  const first = Math.max(2, 2 * Math.round((share * OUT_H) / 2));
  return [first, OUT_H - first];
}

/** Width over height a crop must have, in source pixels, to fill a panel without further cropping. */
export function panelRatio(panelHeight: number): number {
  return OUT_W / panelHeight;
}

/** Height (fraction) of a crop of width `w` (fraction) in the shape of a panel, for a frame `frameAspect` wide over tall. */
export function cropHeight(w: number, ratio: number, frameAspect: number): number {
  return (w * frameAspect) / ratio;
}

/** Largest width (fraction) that keeps a crop at (x, y) in the panel's shape and inside the frame. */
function maxWidth(x: number, y: number, ratio: number, frameAspect: number): number {
  return Math.min(1 - x, ((1 - y) * ratio) / frameAspect);
}

/** The crop with its height re-derived for the panel's shape, shrunk if it no longer fits. */
export function fitCrop(crop: Crop, ratio: number, frameAspect: number): Crop {
  const x = clamp(crop.x, 0, 1 - MIN_CROP_W);
  const y = clamp(crop.y, 0, 0.9);
  const w = clamp(crop.w, MIN_CROP_W, Math.max(MIN_CROP_W, maxWidth(x, y, ratio, frameAspect)));
  return { x, y, w, h: cropHeight(w, ratio, frameAspect) };
}

/** Move a crop by a fraction of the frame, staying inside it. */
export function moveCrop(crop: Crop, dx: number, dy: number): Crop {
  return {
    ...crop,
    x: clamp(crop.x + dx, 0, 1 - crop.w),
    y: clamp(crop.y + dy, 0, 1 - crop.h),
  };
}

/** Resize from the bottom-right corner, keeping the panel's shape. */
export function resizeCrop(crop: Crop, w: number, ratio: number, frameAspect: number): Crop {
  return fitCrop({ ...crop, w }, ratio, frameAspect);
}

/** A starting crop: as wide as `fraction` of the frame, centred, in the panel's shape. */
export function defaultCrop(ratio: number, frameAspect: number, fraction = 0.5): Crop {
  const w = clamp(fraction, MIN_CROP_W, 1);
  const fitted = fitCrop({ x: 0, y: 0, w, h: 0 }, ratio, frameAspect);
  return {
    ...fitted,
    x: clamp((1 - fitted.w) / 2, 0, 1),
    y: clamp((1 - fitted.h) / 2, 0, 1),
  };
}

export function buildSpec(
  count: PanelCount,
  firstShare: number,
  crops: Crop[],
  captionY: number | null,
): LayoutSpec {
  const share = clamp(firstShare, MIN_SHARE, 1 - MIN_SHARE);
  const panels = crops.slice(0, count).map((crop, index) => ({
    crop: { x: crop.x, y: crop.y, w: crop.w, h: crop.h },
    height: count === 1 ? 1 : index === 0 ? share : 1 - share,
  }));
  return { version: 1, panels, caption_y: captionY };
}

/** Editor state from a saved spec. */
export function fromSpec(spec: LayoutSpec): { count: PanelCount; firstShare: number; crops: Crop[]; captionY: number | null } {
  const count: PanelCount = spec.panels.length === 2 ? 2 : 1;
  return {
    count,
    firstShare: count === 2 ? spec.panels[0].height : 0.5,
    crops: spec.panels.map((panel) => ({ ...panel.crop })),
    captionY: spec.caption_y ?? null,
  };
}
