import { NextResponse } from "next/server";

import { createProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

/** Five seconds of a YouTube link, as an MP4 (or the backend's JSON error). */
export async function POST(request: Request) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const upstream = await fetchBackend("/layouts/preview-clip", {
    method: "POST",
    userId: session.user.id,
    extraHeaders: { "Content-Type": "application/json" },
    body: (await request.text()) || "{}",
    cache: "no-store",
  });
  return createProxyResponse(upstream);
}
