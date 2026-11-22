/** Characters a file name cannot hold on common systems. */
const FORBIDDEN = /[\u0000-\u001f"/\\<>:|?*]+/g;

/** The file name a downloaded clip gets: its title, plus the length of a shortened copy. */
export function clipDownloadName(
  clip: { hook_title?: string | null; filename: string; workflow_meta?: { shortened_to?: number } | null },
  suffix = "",
): string {
  const stem = (clip.hook_title ?? "").replace(FORBIDDEN, "").replace(/\s+/g, " ").trim()
    || clip.filename.replace(/\.mp4$/i, "");
  const seconds = clip.workflow_meta?.shortened_to;
  const length = stem && seconds ? ` - ${seconds >= 60 && seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`}` : "";
  return `${(stem + length).slice(0, 180)}${suffix}.mp4`;
}
