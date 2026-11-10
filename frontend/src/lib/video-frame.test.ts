import { afterEach, describe, expect, it, vi } from "vitest";

import { clampSeek, frameFromFile, previewSize } from "./video-frame";

describe("clampSeek", () => {
  it("stays inside the video, a little before the end", () => {
    expect(clampSeek(30, 120)).toBe(30);
    expect(clampSeek(500, 120)).toBeCloseTo(119.9);
    expect(clampSeek(-5, 120)).toBe(0);
  });

  it("copes with unknown durations and bad numbers", () => {
    expect(clampSeek(12, Number.NaN)).toBe(12);
    expect(clampSeek(12, 0)).toBe(12);
    expect(clampSeek(Number.NaN, 60)).toBe(0);
  });
});

describe("previewSize", () => {
  it("scales wide frames down and never up", () => {
    expect(previewSize(1920, 1080)).toEqual({ width: 1280, height: 720 });
    expect(previewSize(640, 360)).toEqual({ width: 640, height: 360 });
    expect(previewSize(0, 0)).toEqual({ width: 0, height: 0 });
  });
});

describe("frameFromFile", () => {
  const realCreate = document.createElement.bind(document);
  afterEach(() => vi.restoreAllMocks());

  function fakeVideo(options: { fail?: boolean; width?: number; height?: number; duration?: number }) {
    const listeners = new Map<string, Set<() => void>>();
    const video = {
      muted: false, preload: "", playsInline: false, duration: options.duration ?? 100,
      videoWidth: options.width ?? 1920, videoHeight: options.height ?? 1080,
      _time: 0,
      addEventListener: (name: string, handler: () => void) => {
        if (!listeners.has(name)) listeners.set(name, new Set());
        listeners.get(name)!.add(handler);
      },
      removeEventListener: (name: string, handler: () => void) => listeners.get(name)?.delete(handler),
      removeAttribute: vi.fn(),
      load: vi.fn(),
      set currentTime(value: number) { video._time = value; setTimeout(() => emit("seeked")); },
      get currentTime() { return video._time; },
      set src(_value: string) { setTimeout(() => emit(options.fail ? "error" : "loadedmetadata")); },
    };
    const emit = (name: string) => [...(listeners.get(name) ?? [])].forEach((handler) => handler());
    return video;
  }

  function mockDom(video: ReturnType<typeof fakeVideo>) {
    const drawImage = vi.fn();
    const canvas = {
      width: 0, height: 0,
      getContext: () => ({ drawImage }),
      toBlob: (callback: (blob: Blob | null) => void) => callback(new Blob(["jpeg"], { type: "image/jpeg" })),
    };
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) =>
      tag === "video" ? video : tag === "canvas" ? canvas : realCreate(tag)) as typeof document.createElement);
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    return { canvas, drawImage };
  }

  it("seeks, draws at the preview size and returns a JPEG", async () => {
    const video = fakeVideo({});
    const { canvas, drawImage } = mockDom(video);
    const blob = await frameFromFile(new File(["x"], "game.mp4"), 30);
    expect(video.currentTime).toBe(30);
    expect([canvas.width, canvas.height]).toEqual([1280, 720]);
    expect(drawImage).toHaveBeenCalledWith(video, 0, 0, 1280, 720);
    expect(blob.type).toBe("image/jpeg");
  });

  it("asks for a time inside short videos", async () => {
    const video = fakeVideo({ duration: 10 });
    mockDom(video);
    await frameFromFile(new File(["x"], "short.mp4"), 600);
    expect(video.currentTime).toBeCloseTo(9.9);
  });

  it("fails when the browser cannot decode the file", async () => {
    mockDom(fakeVideo({ fail: true }));
    await expect(frameFromFile(new File(["x"], "odd.mkv"), 0)).rejects.toThrow("decode");
  });
});
