/**
 * One still frame of a video file, read in the browser: nothing is uploaded, so
 * a multi-gigabyte recording previews instantly. The browser must be able to
 * decode the file (MP4 with H.264 almost always is).
 */

export const PREVIEW_MAX_WIDTH = 1280;

/** A seek time inside the video: never negative, and a little before the end so the last frame exists. */
export function clampSeek(seconds: number, duration: number): number {
  const wanted = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  if (!Number.isFinite(duration) || duration <= 0) return wanted;
  return Math.min(wanted, Math.max(0, duration - 0.1));
}

/** Size to draw a frame at: no wider than the preview limit, never upscaled. */
export function previewSize(width: number, height: number): { width: number; height: number } {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  const scale = Math.min(1, PREVIEW_MAX_WIDTH / width);
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

function waitFor(video: HTMLVideoElement, event: "loadedmetadata" | "seeked"): Promise<void> {
  return new Promise((resolve, reject) => {
    const done = () => {
      video.removeEventListener(event, done);
      video.removeEventListener("error", failed);
      resolve();
    };
    const failed = () => {
      video.removeEventListener(event, done);
      video.removeEventListener("error", failed);
      reject(new Error("decode"));
    };
    video.addEventListener(event, done);
    video.addEventListener("error", failed);
  });
}

export async function frameFromFile(file: File, seconds: number): Promise<Blob> {
  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.muted = true;
  video.preload = "auto";
  video.playsInline = true;
  try {
    const loaded = waitFor(video, "loadedmetadata");
    video.src = url;
    await loaded;
    const target = clampSeek(seconds, video.duration);
    const seeked = waitFor(video, "seeked");
    video.currentTime = target;
    await seeked;
    const { width, height } = previewSize(video.videoWidth, video.videoHeight);
    if (!width || !height) throw new Error("decode");
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("decode");
    context.drawImage(video, 0, 0, width, height);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("decode"))), "image/jpeg", 0.9);
    });
  } finally {
    URL.revokeObjectURL(url);
    video.removeAttribute("src");
    video.load();
  }
}
