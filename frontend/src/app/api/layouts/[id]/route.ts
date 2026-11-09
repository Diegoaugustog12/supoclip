import { NextResponse } from "next/server";

import { createTextProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

type Params = { params: Promise<{ id: string }> };

export async function PUT(request: Request, { params }: Params) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const upstream = await fetchBackend(`/layouts/${encodeURIComponent(id)}`, {
    method: "PUT",
    userId: session.user.id,
    extraHeaders: { "Content-Type": "application/json" },
    body: (await request.text()) || "{}",
    cache: "no-store",
  });
  return createTextProxyResponse(upstream);
}

export async function DELETE(_request: Request, { params }: Params) {
  const session = await getServerSession();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const upstream = await fetchBackend(`/layouts/${encodeURIComponent(id)}`, {
    method: "DELETE",
    userId: session.user.id,
    cache: "no-store",
  });
  return createTextProxyResponse(upstream);
}
