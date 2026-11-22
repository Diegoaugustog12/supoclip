import { NextResponse } from "next/server";

import { createTextProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

type Context = { params: Promise<{ path: string[] }> };

async function proxy(request: Request, { params }: Context) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { path } = await params;
  const search = new URL(request.url).search;
  const body = request.method === "GET" ? undefined : (await request.text()) || "{}";
  const upstream = await fetchBackend(`/automations/${path.map(encodeURIComponent).join("/")}${search}`, {
    method: request.method,
    userId: session.user.id,
    extraHeaders: body ? { "Content-Type": "application/json" } : undefined,
    body,
    cache: "no-store",
  });
  return createTextProxyResponse(upstream);
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
