import prisma from "@/lib/prisma";

const FAR_FUTURE = new Date("2999-01-01T00:00:00Z");

/** `REQUIRE_LOGIN=false` lets everyone in as the instance's single account. */
export function openAccessEnabled() {
  return (process.env.REQUIRE_LOGIN ?? "").trim().toLowerCase() === "false";
}

/**
 * The session used when login is off: the oldest account (so an existing
 * library stays where it is), or a new local one on an empty database.
 */
export async function openAccessSession() {
  const select = {
    id: true,
    name: true,
    email: true,
    emailVerified: true,
    image: true,
    createdAt: true,
    updatedAt: true,
    is_admin: true,
  } as const;
  const user =
    (await prisma.user.findFirst({ orderBy: { createdAt: "asc" }, select })) ??
    (await prisma.user.create({
      data: { name: "Local", email: "local@supoclip.local", emailVerified: true },
      select,
    }));

  return {
    user,
    session: {
      id: "open-access",
      token: "open-access",
      userId: user.id,
      expiresAt: FAR_FUTURE,
      createdAt: user.createdAt,
      updatedAt: user.updatedAt,
      ipAddress: null,
      userAgent: null,
    },
  };
}
