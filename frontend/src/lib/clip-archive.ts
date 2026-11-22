import { triggerFileDownload } from "@/lib/clip-export";

export type ClipArchivePreflight = {
  filename: string;
  clipCount: number;
};

export function clipArchivePath(taskApiUrl: string, taskId: string): string {
  return `${taskApiUrl}/${encodeURIComponent(taskId)}/clips/zip`;
}

/** `?ids=a,b` limiting the archive to the picked clips; empty for the whole task. */
function selectionQuery(ids?: readonly string[]): string {
  return ids?.length ? `?ids=${ids.map(encodeURIComponent).join(",")}` : "";
}

/**
 * Download every clip of a task as one ZIP.
 *
 * The archive is streamed by the backend, so the browser's own download
 * manager fetches it (no blob in memory). A preflight request runs the same
 * checks first (access, files present, no other ZIP download running), so
 * errors show up in the page instead of as a failed or JSON download.
 */
export async function downloadAllClips({
  taskApiUrl,
  taskId,
  clipIds,
  readError,
  fallbackMessage,
  request = fetch,
  trigger = triggerFileDownload,
}: {
  taskApiUrl: string;
  taskId: string;
  /** Only these clips; every clip of the task when omitted. */
  clipIds?: readonly string[];
  readError: (response: Response) => Promise<string>;
  fallbackMessage: string;
  request?: typeof fetch;
  trigger?: (href: string, filename: string) => void;
}): Promise<ClipArchivePreflight> {
  const path = clipArchivePath(taskApiUrl, taskId);
  const query = selectionQuery(clipIds);
  const response = await request(`${path}/preflight${query}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(fallbackMessage);
  }
  const { filename, clip_count: clipCount } = (payload ?? {}) as { filename?: unknown; clip_count?: unknown };
  if (typeof filename !== "string" || !filename || typeof clipCount !== "number" || clipCount < 1) {
    throw new Error(fallbackMessage);
  }
  trigger(`${path}${query}`, filename);
  return { filename, clipCount };
}
