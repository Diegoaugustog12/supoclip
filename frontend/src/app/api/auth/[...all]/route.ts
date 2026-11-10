import { auth } from "@/lib/auth";
import { openAccessEnabled } from "@/server/open-access";
import { toNextJsHandler } from "better-auth/next-js";

const handlers = toNextJsHandler(auth.handler);

export const POST = handlers.POST;

export async function GET(request: Request) {
  // The browser asks here who is signed in; with login off, answer with the
  // instance's single account instead of "nobody".
  if (openAccessEnabled() && new URL(request.url).pathname.endsWith("/get-session")) {
    return Response.json(await auth.api.getSession({ headers: request.headers }));
  }
  return handlers.GET(request);
}
