import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER } from "@/test/helpers";

// The real module builds NextAuth (Prisma adapter, bcrypt) at import; only the
// session lookup matters here.
vi.mock("@/lib/auth", () => ({ auth: vi.fn() }));

import { getRequiredUser } from "@/lib/session";
import { auth } from "@/lib/auth";
import { isUnauthorized, routeError } from "@/lib/api-errors";

const mockAuth = vi.mocked(auth);

beforeEach(() => {
  vi.resetAllMocks();
});

describe("getRequiredUser", () => {
  it("returns the signed-in user", async () => {
    mockAuth.mockResolvedValue({ user: TEST_USER, expires: "2099-01-01" } as never);
    await expect(getRequiredUser()).resolves.toEqual(TEST_USER);
  });

  it.each([
    ["no session", null],
    ["a session without a user", { expires: "2099-01-01" }],
    ["a user without an id", { user: { email: TEST_USER.email }, expires: "2099-01-01" }],
    ["an empty user id", { user: { id: "" }, expires: "2099-01-01" }],
  ])("refuses %s with an error every route reads as 401", async (_label, session) => {
    mockAuth.mockResolvedValue(session as never);
    const error = await getRequiredUser().catch((e: unknown) => e);

    // Routes recognize a missing session two ways: the shared helper, and —
    // in the ones not yet migrated to it — a direct message comparison.
    expect(isUnauthorized(error)).toBe(true);
    expect((error as Error).message).toBe("Unauthorized");
    expect(routeError(error, "Failed").status).toBe(401);
  });
});
