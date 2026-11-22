import { describe, expect, it } from "vitest";

import {
  buildSpec,
  cropHeight,
  defaultCrop,
  fitCrop,
  fromSpec,
  moveCrop,
  panelHeights,
  panelRatio,
  resizeCrop,
  resizeFree,
} from "./layout-spec";

const FRAME = 16 / 9;

describe("panel geometry", () => {
  it("fills the output with even heights", () => {
    const heights = panelHeights(2, 0.333);
    expect(heights[0] + heights[1]).toBe(1920);
    expect(heights.every((h) => h % 2 === 0)).toBe(true);
    expect(panelHeights(1, 0.5)).toEqual([1920]);
  });

  it("keeps each panel between 15% and 85%", () => {
    expect(panelHeights(2, 0.01)[0]).toBe(288);
    expect(panelHeights(2, 0.99)[0]).toBe(1632);
  });
});

describe("crops keep the panel's shape", () => {
  const ratio = panelRatio(640); // 1080 / 640

  it("derives the height from the width", () => {
    const crop = fitCrop({ x: 0.1, y: 0.1, w: 0.4, h: 0 }, ratio, FRAME);
    expect(crop.h).toBeCloseTo(cropHeight(0.4, ratio, FRAME));
    // shape in source pixels equals the panel's
    expect((crop.w * FRAME) / crop.h).toBeCloseTo(ratio);
  });

  it("shrinks a crop that would leave the frame", () => {
    const crop = fitCrop({ x: 0.5, y: 0.9, w: 0.5, h: 0 }, ratio, FRAME);
    expect(crop.x + crop.w).toBeLessThanOrEqual(1.000001);
    expect(crop.y + crop.h).toBeLessThanOrEqual(1.000001);
  });

  it("moves inside the frame only", () => {
    const crop = defaultCrop(ratio, FRAME, 0.3);
    const moved = moveCrop(crop, 5, 5);
    expect(moved.x + moved.w).toBeCloseTo(1);
    expect(moved.y + moved.h).toBeCloseTo(1);
    expect(moveCrop(crop, -5, -5)).toMatchObject({ x: 0, y: 0 });
  });

  it("resizes without changing the shape", () => {
    const crop = defaultCrop(ratio, FRAME, 0.3);
    const bigger = resizeCrop(crop, 0.5, ratio, FRAME);
    expect((bigger.w * FRAME) / bigger.h).toBeCloseTo(ratio);
  });

  it("never goes below the minimum width", () => {
    expect(resizeCrop(defaultCrop(ratio, FRAME), 0, ratio, FRAME).w).toBeGreaterThanOrEqual(0.08);
  });
});

describe("spec round trip", () => {
  it("builds and reads back a two panel spec", () => {
    const crops = [
      defaultCrop(panelRatio(640), FRAME, 0.3),
      defaultCrop(panelRatio(1280), FRAME, 0.9),
    ];
    const spec = buildSpec(2, 1 / 3, crops, 0.5);
    expect(spec.panels).toHaveLength(2);
    expect(spec.panels[0].height + spec.panels[1].height).toBeCloseTo(1);
    const state = fromSpec(spec);
    expect(state.count).toBe(2);
    expect(state.firstShare).toBeCloseTo(1 / 3);
    expect(state.captionY).toBe(0.5);
  });

  it("a one panel spec ignores the second crop and takes the full height", () => {
    const crop = defaultCrop(panelRatio(1920), FRAME);
    const spec = buildSpec(1, 0.4, [crop, crop], null);
    expect(spec.panels).toHaveLength(1);
    expect(spec.panels[0].height).toBe(1);
    expect(spec.caption_y).toBeNull();
  });
});

describe("caption and title styles", () => {
  it("are saved with the spec and read back", () => {
    const crop = defaultCrop(panelRatio(1920), FRAME);
    const spec = buildSpec(1, 0.5, [crop], null, { size: 40, max_words: 3, animation: "pop" }, { y: 0.2, enabled: false });
    expect(spec.caption).toEqual({ size: 40, max_words: 3, animation: "pop" });
    const state = fromSpec(spec);
    expect(state.caption.max_words).toBe(3);
    expect(state.title).toEqual({ y: 0.2, enabled: false });
  });

  it("an older spec without styles reads back empty", () => {
    const state = fromSpec({ version: 1, panels: [{ crop: { x: 0, y: 0, w: 1, h: 1 }, height: 1 }], caption_y: null });
    expect(state.caption).toEqual({});
    expect(state.title).toEqual({});
  });
});

describe("contain panels", () => {
  it("keep a free-shaped crop inside the frame", () => {
    const free = fitCrop({ x: 0.2, y: 0.1, w: 0.9, h: 0.95 }, panelRatio(1280), FRAME, "contain");
    expect(free.x + free.w).toBeLessThanOrEqual(1.000001);
    expect(free.y + free.h).toBeLessThanOrEqual(1.000001);
    // not forced to the panel's shape
    expect((free.w * FRAME) / free.h).not.toBeCloseTo(panelRatio(1280));
  });

  it("resize both sides and never below the minimum", () => {
    const crop = resizeFree({ x: 0.1, y: 0.1, w: 0.3, h: 0.3 }, 0.6, 0.2);
    expect(crop.w).toBeCloseTo(0.6);
    expect(crop.h).toBeCloseTo(0.2);
    expect(resizeFree(crop, 0, 0).w).toBeGreaterThanOrEqual(0.08);
  });

  it("the fit is saved per panel and read back", () => {
    const full = { x: 0, y: 0, w: 1, h: 1 };
    const spec = buildSpec(2, 0.35, [full, full], null, {}, {}, ["cover", "contain"]);
    expect(spec.panels.map((panel) => panel.fit)).toEqual(["cover", "contain"]);
    expect(fromSpec(spec).fits).toEqual(["cover", "contain"]);
    expect(fromSpec({ ...spec, panels: spec.panels.map(({ crop, height }) => ({ crop, height })) }).fits).toEqual(["cover", "cover"]);
  });
});
