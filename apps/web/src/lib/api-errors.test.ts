import { describe, it, expect, vi, beforeEach } from "vitest";
import { TEST_USER, jobParams } from "@/test/helpers";
import { routeError, isUnauthorized, UnauthorizedError } from "@/lib/api-errors";

describe("routeError", () => {
  it("maps a missing session to 401, not the fallback", async () => {
    const res = routeError(new UnauthorizedError(), "Failed to fetch jobs");
    expect(res.status).toBe(401);
    await expect(res.json()).resolves.toEqual({ error: "Unauthorized" });
  });

  it("still recognizes the plain Error the old code threw", () => {
    // getRequiredUser threw `new Error("Unauthorized")`; routes string-matched
    // the message. Both forms must keep working during the migration.
    expect(isUnauthorized(new Error("Unauthorized"))).toBe(true);
    expect(routeError(new Error("Unauthorized"), "x").status).toBe(401);
  });

  it("uses the fallback for anything else", async () => {
    const res = routeError(new Error("connection reset"), "Download failed");
    expect(res.status).toBe(500);
    await expect(res.json()).resolves.toEqual({ error: "Download failed" });
  });

  it("does not treat unrelated errors as auth failures", () => {
    expect(isUnauthorized(new Error("Unauthorized user action"))).toBe(false);
    expect(isUnauthorized("Unauthorized")).toBe(false);
    expect(isUnauthorized(null)).toBe(false);
  });

  it("honours a custom fallback status", () => {
    expect(routeError(new Error("nope"), "Bad input", 400).status).toBe(400);
  });
});

// The routes below all wrapped their handler in a bare `catch { ... 500 }`, so
// an expired session produced a server-error message instead of a 401.
vi.mock("@/lib/prisma", () => ({
  prisma: {
    job: { findMany: vi.fn(), findFirst: vi.fn(), count: vi.fn() },
    auditEntry: { create: vi.fn() },
  },
}));
vi.mock("@/lib/session", () => ({ getRequiredUser: vi.fn() }));
vi.mock("@/lib/retention", () => ({ purgeExpiredJobFiles: vi.fn() }));
vi.mock("@/lib/job-reaper", () => ({ reapStuckConvertingJobs: vi.fn() }));

import { GET as listJobs } from "@/app/api/jobs/route";
import { GET as getJob } from "@/app/api/jobs/[jobId]/route";
import { getRequiredUser } from "@/lib/session";

const auth = vi.mocked(getRequiredUser);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("authenticated routes return 401 for a missing session", () => {
  it("GET /api/jobs", async () => {
    auth.mockRejectedValue(new Error("Unauthorized"));
    const res = await listJobs();
    expect(res.status).toBe(401);
  });

  it("GET /api/jobs/[jobId]", async () => {
    auth.mockRejectedValue(new Error("Unauthorized"));
    const res = await getJob(
      new Request("http://localhost/api/jobs/j1"),
      jobParams("j1")
    );
    expect(res.status).toBe(401);
  });

  it("still returns 500 for a genuine failure", async () => {
    auth.mockResolvedValue(TEST_USER as never);
    const { prisma } = await import("@/lib/prisma");
    vi.mocked(prisma, true).job.findMany.mockRejectedValue(
      new Error("db exploded") as never
    );
    const res = await listJobs();
    expect(res.status).toBe(500);
  });
});
